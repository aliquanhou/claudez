"""webhook — 远程触发服务。

通过 HTTP/FastAPI 端点远程触发 Agent 执行任务。
支持：
  - POST /webhook — 触发任务执行
  - GET /webhook/{task_id} — 查询任务状态
  - GET /health — 健康检查
  - 可选的 API Key 认证
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# ── Webhook 任务 ──

@dataclass
class WebhookTask:
    """Webhook 触发的任务。"""
    id: str
    prompt: str
    status: str = "pending"  # pending | running | completed | failed
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0
    source_ip: str = ""
    headers: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "prompt": self.prompt[:200],
            "status": self.status,
            "result": self.result if self.status == "completed" else "",
            "error": self.error if self.status == "failed" else "",
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class WebhookManager:
    """Webhook 任务管理器。"""

    def __init__(self):
        self._tasks: dict[str, WebhookTask] = {}
        self._lock = threading.Lock()
        self._api_key: str = os.environ.get("CLAUDEZ_WEBHOOK_KEY", "")

    def set_api_key(self, key: str):
        self._api_key = key

    def verify_key(self, key: str) -> bool:
        if not self._api_key:
            return True  # 无 API Key 时不验证
        return key == self._api_key

    def create_task(self, prompt: str, source_ip: str = "",
                    headers: dict | None = None) -> WebhookTask:
        task = WebhookTask(
            id=str(uuid.uuid4())[:12],
            prompt=prompt,
            source_ip=source_ip,
            headers=headers or {},
        )
        with self._lock:
            self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> WebhookTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update_task(self, task_id: str, **kwargs):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                for k, v in kwargs.items():
                    setattr(task, k, v)

    def list_tasks(self, limit: int = 20) -> list[dict]:
        with self._lock:
            tasks = sorted(
                self._tasks.values(),
                key=lambda t: t.created_at,
                reverse=True,
            )
            return [t.to_dict() for t in tasks[:limit]]


# 全局管理器
_manager = WebhookManager()


def get_webhook_manager() -> WebhookManager:
    return _manager


# ── 后台执行 ──

def _execute_task_async(task: WebhookTask):
    """在后台线程中执行任务。"""
    try:
        from agent.core import Agent

        _manager.update_task(task.id, status="running")

        agent = Agent({
            "model": os.environ.get("CLAUDEZ_MODEL", "claude-sonnet-4-20250514"),
            "workflow_mode": "agent",
            "max_tool_calls_per_turn": 25,
        })

        result = agent.run(task.prompt)

        _manager.update_task(
            task.id,
            status="completed",
            result=result,
            completed_at=time.time(),
        )
    except Exception as e:
        import traceback
        _manager.update_task(
            task.id,
            status="failed",
            error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
            completed_at=time.time(),
        )


# ── FastAPI 应用 ──

def create_webhook_app():
    """创建 FastAPI 应用。"""
    try:
        from fastapi import FastAPI, Request, HTTPException
        from fastapi.responses import JSONResponse
        from pydantic import BaseModel
    except ImportError:
        raise ImportError(
            "需要安装 fastapi 和 uvicorn: pip install fastapi uvicorn"
        )

    app = FastAPI(
        title="ClaudeZ Webhook",
        description="远程触发 ClaudeZ Agent 执行任务",
        version="2.1.0",
    )

    class TriggerRequest(BaseModel):
        prompt: str
        async_mode: bool = True

    class TriggerResponse(BaseModel):
        task_id: str
        status: str
        message: str

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "claudez-webhook"}

    @app.post("/webhook", response_model=TriggerResponse)
    async def trigger(request: TriggerRequest, http_request: Request):
        """触发 Agent 执行任务。"""
        # API Key 验证
        api_key = http_request.headers.get("X-API-Key", "")
        if not _manager.verify_key(api_key):
            raise HTTPException(status_code=401, detail="无效的 API Key")

        if not request.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt 不能为空")

        task = _manager.create_task(
            prompt=request.prompt,
            source_ip=http_request.client.host if http_request.client else "",
            headers=dict(http_request.headers),
        )

        if request.async_mode:
            # 后台执行
            thread = threading.Thread(
                target=_execute_task_async,
                args=(task,),
                daemon=True,
            )
            thread.start()
            return TriggerResponse(
                task_id=task.id,
                status="started",
                message=f"任务已提交 (task_id: {task.id})",
            )
        else:
            # 同步执行
            _execute_task_async(task)
            return TriggerResponse(
                task_id=task.id,
                status=task.status,
                message=task.result or task.error,
            )

    @app.get("/webhook/{task_id}")
    async def get_task_status(task_id: str):
        """查询任务状态。"""
        task = _manager.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"未找到任务: {task_id}")
        return task.to_dict()

    @app.get("/webhook/tasks")
    async def list_tasks(limit: int = 20):
        """列出最近的任务。"""
        return {"tasks": _manager.list_tasks(limit)}

    return app


# ── 启动服务器 ──

def start_webhook_server(host: str = "127.0.0.1", port: int = 8765):
    """启动 Webhook 服务器。"""
    app = create_webhook_app()

    try:
        import uvicorn
        print(f"[Webhook] 启动服务器: http://{host}:{port}")
        print(f"[Webhook] 健康检查: http://{host}:{port}/health")
        print(f"[Webhook] 触发端点: POST http://{host}:{port}/webhook")
        uvicorn.run(app, host=host, port=port)
    except ImportError:
        print("[Webhook] 需要安装 uvicorn: pip install uvicorn")
        raise
