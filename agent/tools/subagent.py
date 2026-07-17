"""tools/subagent — 子 Agent 工具。

支持：
  - 同步模式：子 Agent 在前台运行，返回结果
  - 后台模式：子 Agent 在后台运行，返回 task_id，可查询状态
  - 嵌套 Agent：子 Agent 可以调用工具（包括创建子子 Agent）
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .registry import tool


# ── 后台任务存储 ──

@dataclass
class SubAgentTask:
    """子 Agent 后台任务。"""
    id: str
    prompt: str
    agent_type: str
    model: str
    status: str = "pending"  # pending | running | completed | failed
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0
    thread: threading.Thread | None = None


class SubAgentManager:
    """子 Agent 后台任务管理器。"""

    def __init__(self):
        self._tasks: dict[str, SubAgentTask] = {}
        self._lock = threading.Lock()

    def create_task(self, prompt: str, agent_type: str = "agent",
                    model: str = "") -> SubAgentTask:
        """创建后台任务。"""
        task_id = str(uuid.uuid4())[:8]
        task = SubAgentTask(
            id=task_id,
            prompt=prompt,
            agent_type=agent_type,
            model=model,
            created_at=time.time(),
        )
        with self._lock:
            self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> SubAgentTask | None:
        """获取任务。"""
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs):
        """更新任务状态。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                for k, v in kwargs.items():
                    setattr(task, k, v)

    def list_tasks(self) -> list[dict]:
        """列出所有任务。"""
        with self._lock:
            return [
                {
                    "id": t.id,
                    "prompt": t.prompt[:100],
                    "agent_type": t.agent_type,
                    "status": t.status,
                    "created_at": t.created_at,
                    "completed_at": t.completed_at,
                }
                for t in self._tasks.values()
            ]

    def cleanup_old_tasks(self, max_age: float = 3600):
        """清理过期任务。"""
        now = time.time()
        with self._lock:
            to_delete = [
                tid for tid, t in self._tasks.items()
                if t.status in ("completed", "failed")
                and now - t.completed_at > max_age
            ]
            for tid in to_delete:
                del self._tasks[tid]


# 全局管理器
_manager = SubAgentManager()


def _run_subagent_async(task: SubAgentTask):
    """在后台线程中运行子 Agent。"""
    try:
        from agent.core import Agent
        from agent.session import create_isolated_session

        _manager.update_task(task.id, status="running")

        # 继承父 Agent 的配置
        import json as _json, os as _os
        _cfg_paths = ["config.json"]
        _cfg = {}
        for _p in _cfg_paths:
            if _os.path.exists(_p):
                with open(_p, "r", encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
                break

        config = {
            "model": task.model or _cfg.get("model", "deepseek-chat"),
            "provider": _cfg.get("provider", "deepseek"),
            "api_key": _cfg.get("api_key", ""),
            "base_url": _cfg.get("base_url", "https://api.deepseek.com/v1"),
            "workflow_mode": task.agent_type,
            "max_tool_calls_per_turn": 15,
            "enable_memory": False,
            "disable_thinking": _cfg.get("disable_thinking", True),
        }
        isolated_session = create_isolated_session()
        agent = Agent(config, session=isolated_session)

        # 运行
        result = agent.run(task.prompt)

        _manager.update_task(
            task.id,
            status="completed",
            result=result,
            completed_at=time.time(),
        )
    except Exception as e:
        _manager.update_task(
            task.id,
            status="failed",
            error=f"{type(e).__name__}: {e}",
            completed_at=time.time(),
        )


# ═══════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════

@tool(category="agent", timeout=300)
def subagent(prompt: str, agent_type: str = "agent",
             model: str = "", mode: str = "sync",
             task_id: str = "") -> str:
    """创建子 Agent 执行任务。

    子 Agent 拥有独立的会话和工具调用能力。
    支持同步（等待结果）和后台（异步执行）两种模式。

    Args:
        prompt: 子 Agent 的任务描述
        agent_type: 工作流模式（agent | chat | research | coding | debug）
        model: 模型名称（空则使用父 Agent 的模型）
        mode: 运行模式（sync=同步等待结果 | background=后台运行）
        task_id: 查询后台任务状态时使用（mode=status 时）
    """
    # 查询模式
    if mode == "status":
        if not task_id:
            return "[错误] 查询状态需要提供 task_id"
        task = _manager.get_task(task_id)
        if not task:
            return f"[错误] 未找到任务: {task_id}"
        return json.dumps({
            "id": task.id,
            "status": task.status,
            "result": task.result if task.status == "completed" else "",
            "error": task.error if task.status == "failed" else "",
            "created_at": task.created_at,
            "completed_at": task.completed_at,
        }, ensure_ascii=False)

    # 列出所有任务
    if mode == "list":
        tasks = _manager.list_tasks()
        if not tasks:
            return "(无后台任务)"
        lines = ["后台任务列表:"]
        for t in tasks:
            lines.append(f"  [{t['status']}] {t['id']}: {t['prompt']}")
        return "\n".join(lines)

    # 后台模式
    if mode == "background":
        task = _manager.create_task(prompt, agent_type, model)
        thread = threading.Thread(
            target=_run_subagent_async,
            args=(task,),
            daemon=True,
        )
        task.thread = thread
        thread.start()
        return json.dumps({
            "task_id": task.id,
            "status": "started",
            "message": f"子 Agent 已在后台启动 (task_id: {task.id})",
        }, ensure_ascii=False)

    # 同步模式（默认）
    try:
        from agent.core import Agent
        from agent.session import create_isolated_session

        # 继承父 Agent 的关键配置（subagent 函数定义在模块顶层，无法访问父 Agent 实例）
        # 通过全局 config 获取 api_key/base_url
        import json as _json
        _cfg_paths = ["config.json"]
        _cfg = {}
        for _p in _cfg_paths:
            import os as _os
            if _os.path.exists(_p):
                with open(_p, "r", encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
                break

        config = {
            "model": model or _cfg.get("model", "deepseek-chat"),
            "provider": _cfg.get("provider", "deepseek"),
            "api_key": _cfg.get("api_key", ""),
            "base_url": _cfg.get("base_url", "https://api.deepseek.com/v1"),
            "workflow_mode": agent_type,
            "max_tool_calls_per_turn": 15,
            "enable_memory": False,
            "disable_thinking": _cfg.get("disable_thinking", True),
        }
        isolated_session = create_isolated_session()
        agent = Agent(config, session=isolated_session)
        result = agent.run(prompt)
        return result
    except Exception as e:
        import traceback as _tb
        return f"[子 Agent 错误] {type(e).__name__}: {e}\n{_tb.format_exc()[:300]}"
