"""ForgeX Web UI v2 — FastAPI 服务器 + SSE 流式。

API:
  GET  /              → cockpit.html (驾驶舱 UI)
  GET  /api/stream    → SSE 事件流
  POST /api/send      → 发送消息
  GET  /api/status    → 当前状态快照
  GET  /api/tools     → 已注册工具列表
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue as q_module
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent._trace import T

_log = logging.getLogger("forgex.web")
HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


class SendBody(BaseModel):
    text: str


class LLMConfigBody(BaseModel):
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    disable_thinking: bool | None = None
    provider: str | None = None


class WorkspaceBody(BaseModel):
    path: str = ""
    name: str = ""


class ConfigUpdateBody(BaseModel):
    """配置更新请求体 — 所有字段可选，仅更新传入的字段。"""
    model: str | None = None
    provider: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    api_timeout: int | None = None
    disable_thinking: bool | None = None
    enable_caching: bool | None = None
    max_cache_keys: int | None = None
    max_context_tokens: int | None = None
    max_context_messages: int | None = None
    context_compress_at: float | None = None
    parallel_tools: bool | None = None
    tool_timeout: float | None = None
    max_tool_calls_per_turn: int | None = None
    max_consecutive_errors: int | None = None
    sandbox_mode: str | None = None
    sandbox_danger_threshold: int | None = None
    workflow_mode: str | None = None
    pipeline_max_retries: int | None = None
    enable_nudge: bool | None = None
    enable_memory: bool | None = None
    memory_search_top_k: int | None = None
    permission_mode: str | None = None
    confirmed: bool = False  # v2.0: 高危操作二次确认标记


# 高危操作白名单（需要二次确认）
_HIGH_RISK_CONFIG_KEYS = {"sandbox_mode", "permission_mode", "enable_caching", "model", "api_key", "base_url"}


# 工作空间根目录（模块级，供 _build_app 内路由函数访问）
_WORKSPACE_ROOT = os.path.abspath("D:/ForgeX")


def _build_app(agent) -> FastAPI:
    # 初始化工作空间（同步到 Agent）
    try:
        agent.set_workspace_root(_WORKSPACE_ROOT)
    except Exception:
        pass

    app = FastAPI(title="ForgeX Cockpit", version="1.0.0")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # SSE 状态
    _sse_queues: list[q_module.Queue] = []
    _sse_lock = threading.Lock()
    _agent_busy_lock = threading.Lock()

    # ── 辅助: 广播 SSE 事件 ──
    def _broadcast(event: str, data: dict):
        payload = json.dumps(data, ensure_ascii=False)
        with _sse_lock:
            dead: list[q_module.Queue] = []
            for q in _sse_queues:
                try:
                    q.put_nowait({"event": event, "data": payload})
                except q_module.Full:
                    dead.append(q)
            for q in dead:
                _sse_queues.remove(q)

    # ── 页面 ──
    @app.get("/")
    async def index():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path))
        return {"error": "index.html not found"}

    # ── SSE 流 ──
    @app.get("/api/stream")
    async def sse_stream(request: Request):
        queue: q_module.Queue = q_module.Queue(maxsize=1000)
        with _sse_lock:
            _sse_queues.append(queue)

        async def event_generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = queue.get(timeout=2)
                        yield msg
                    except q_module.Empty:
                        yield {"event": "ping", "data": "{}"}
            finally:
                with _sse_lock:
                    if queue in _sse_queues:
                        _sse_queues.remove(queue)

        return EventSourceResponse(event_generator())

    # ── 发送消息（直接回调，无 run_stream 线程） ──
    @app.post("/api/send")
    async def api_send(body: SendBody):
        if not body.text or not body.text.strip():
            return {"status": "error", "message": "消息为空"}

        # 防并发锁：非阻塞获取，失败说明上一请求仍在执行
        if not _agent_busy_lock.acquire(blocking=False):
            return {"status": "busy", "message": "Agent 正在处理上一个请求"}

        def _run():
            try:
                T("SRV-RUN", "entered _run thread")
                # 立即推送 thought 和状态
                _broadcast("thought", {"text": "正在处理你的请求..."})
                _broadcast("status_update", _read_status(agent))
                T("SRV-RUN", "thought broadcast done")

                # 挂载回调
                _orig_on_stream = agent.on_stream
                _orig_on_tool_start = agent.on_tool_start
                _orig_on_tool_call = agent.on_tool_call
                _orig_on_message = agent.on_message
                _changed_files = {}

                def _snap(fp):
                    try:
                        with open(fp, "r", encoding="utf-8", errors="replace") as _f:
                            return _f.read()
                    except Exception:
                        return ""

                def _on_stream(chunk):
                    T("SRV-CB", f"on_stream chunk_len={len(chunk)}")
                    _broadcast("token", {"text": chunk})
                    if _orig_on_stream:
                        _orig_on_stream(chunk)

                # 工具调用序列号（唯一标识一次调用）
                _tool_seq = [0]

                def _on_tool_start(name, args):
                    _tool_seq[0] += 1
                    tid = int(time.time() * 1000) + _tool_seq[0]
                    T("SRV-CB", f"on_tool_start name={name} tid={tid}")
                    _broadcast("tool_start", {
                        "tool_id": tid,
                        "name": name, "args": args,
                        "time": time.time(),
                    })
                    _broadcast("status_update", _read_status(agent))
                    if name in ("write", "edit"):
                        fp = args.get("file_path", "")
                        if fp and fp not in _changed_files:
                            _changed_files[fp] = _snap(fp)
                    if _orig_on_tool_start:
                        _orig_on_tool_start(name, args)

                def _on_tool_output(name, line):
                    _broadcast("tool_output", {
                        "tool_id": _tool_seq[0],
                        "name": name, "line": line,
                    })

                def _on_tool_call(name, args, result, duration):
                    success = not (result.startswith("[错误]") or result.startswith("[超时]") or result.startswith("[权限拒绝]"))
                    T("SRV-CB", f"on_tool_call name={name} success={success}")
                    _broadcast("tool_result", {
                        "tool_id": _tool_seq[0],
                        "name": name,
                        "args": args,
                        "result": str(result),
                        "duration_ms": duration,
                        "success": success,
                    })
                    if name in ("write", "edit") and success:
                        fp = args.get("file_path", "")
                        if fp in _changed_files:
                            after = _snap(fp)
                            _broadcast("step_diff", {
                                "file": fp,
                                "before": _changed_files[fp],
                                "after": after,
                            })
                            del _changed_files[fp]
                    _broadcast("status_update", _read_status(agent))
                    if _orig_on_tool_call:
                        _orig_on_tool_call(name, args, result, duration)

                def _on_message(role, content):
                    T("SRV-CB", f"on_message role={role} len={len(content)}")
                    if role == "assistant":
                        _broadcast("status_update", _read_status(agent))
                    if _orig_on_message:
                        _orig_on_message(role, content)

                T("SRV-RUN", "mounting callbacks")
                agent.on_stream = _on_stream
                agent.on_tool_start = _on_tool_start
                agent.on_tool_call = _on_tool_call
                agent.on_tool_output = _on_tool_output
                agent.on_message = _on_message
                T("SRV-RUN", "callbacks mounted, calling agent.run()")

                # 执行（同步，无内部线程）
                T("SRV-RUN", "agent.run() starting...")
                result = agent.run(body.text)
                T("SRV-RUN", f"agent.run() returned len={len(result)}")

                # 恢复回调
                agent.on_stream = _orig_on_stream
                agent.on_tool_start = _orig_on_tool_start
                agent.on_tool_call = _orig_on_tool_call
                agent.on_message = _orig_on_message

                # 推送完成
                T("SRV-RUN", f"broadcasting result prefix={result[:60]}")
                _broadcast("status_update", _read_status(agent))
                if result.startswith("[错误]") or result.startswith("[超时]") or result.startswith("[权限拒绝]") or result.startswith("[API"):
                    _broadcast("error", {"text": result})
                else:
                    _broadcast("done", {"text": result})

            except Exception as e:
                T("SRV-RUN", f"EXCEPTION: {type(e).__name__}: {e}")
                _broadcast("error", {"text": str(e)})
            finally:
                T("SRV-RUN", "release busy lock")
                _agent_busy_lock.release()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return {"status": "ok"}

    # ── 状态快照 ──
    @app.get("/api/status")
    async def api_status():
        return _read_status(agent)

    # ── 工具列表 ──
    @app.get("/api/tools")
    async def api_tools():
        try:
            from agent.tools import get_all_tools
            tools = get_all_tools()
            return {"tools": [{"name": t.get("function", {}).get("name", "?"),
                               "description": (t.get("function", {}).get("description", "") or "")[:80]}
                              for t in tools]}
        except Exception as e:
            return {"tools": [], "error": str(e)}

    # ── 文件树 ──
    @app.get("/api/files")
    async def api_files():
        try:
            scanner = getattr(agent, 'workspace_scanner', None)
            if scanner is None:
                return {"tree": {}, "file_count": 0, "project_type": ""}
            info = scanner.get_info()
            return {
                "tree": info.file_tree if info else {},
                "file_count": info.file_count if info else 0,
                "dir_count": info.dir_count if info else 0,
                "project_type": info.project_type if info else "",
                "languages": info.languages if info else [],
                "key_files": info.key_files if info else [],
            }
        except Exception as e:
            return {"tree": {}, "file_count": 0, "error": str(e)}

    # ── LLM 配置 ──
    @app.get("/api/config")
    async def api_get_config():
        cfg = agent.config
        return {
            "model": cfg.get("model", ""),
            "provider": cfg.get("provider", ""),
            "temperature": cfg.get("temperature", 0.0),
            "max_tokens": cfg.get("max_tokens", 4096),
            "api_timeout": cfg.get("api_timeout", 30),
            "workflow_mode": cfg.get("workflow_mode", "agent"),
            "disable_thinking": cfg.get("disable_thinking", True),
        }

    @app.post("/api/config/llm")
    async def api_update_llm(body: LLMConfigBody):
        changed = []
        if body.model is not None:
            agent.config["model"] = body.model
            changed.append("model")
        if body.temperature is not None:
            agent.config["temperature"] = body.temperature
            changed.append("temperature")
        if body.max_tokens is not None:
            agent.config["max_tokens"] = body.max_tokens
            changed.append("max_tokens")
        if body.disable_thinking is not None:
            agent.config["disable_thinking"] = body.disable_thinking
            changed.append("disable_thinking")
        if body.provider is not None:
            agent.config["provider"] = body.provider
            from agent.providers import create_provider
            agent.provider = create_provider(agent.config)
            agent._setup_provider_callbacks()
            changed.append("provider")
        _log.info("config_updated: %s", ", ".join(changed))
        return {"status": "updated", "changed": changed}

    # ── 工作空间管理 ──
    @app.get("/api/workspace")
    async def api_get_workspace():
        """获取当前工作空间信息。"""
        path = _WORKSPACE_ROOT
        exists = os.path.isdir(path)
        return {
            "path": path,
            "exists": exists,
            "file_count": len(os.listdir(path)) if exists else 0,
        }

    @app.post("/api/workspace/set")
    async def api_set_workspace(body: WorkspaceBody):
        """设置工作空间路径（导入已有目录）。"""
        global _WORKSPACE_ROOT
        if not body.path:
            return {"success": False, "error": "路径不能为空"}
        target = os.path.abspath(body.path)
        if not os.path.isdir(target):
            try:
                os.makedirs(target, exist_ok=True)
            except Exception as e:
                return {"success": False, "error": f"无法创建目录: {e}"}
        _WORKSPACE_ROOT = target
        # 通知 Agent 切换工作目录
        try:
            agent.set_workspace_root(target)
        except Exception as e:
            _log.warning("agent.set_workspace_root failed: %s", e)
        # 广播状态更新
        _broadcast("status_update", _read_status(agent))
        T("WORKSPACE", f"set to {target}")
        return {"success": True, "path": target}

    @app.post("/api/workspace/create")
    async def api_create_workspace(body: WorkspaceBody):
        """在工作空间目录下创建新项目。"""
        global _WORKSPACE_ROOT
        base = os.path.dirname(_WORKSPACE_ROOT)
        name = (body.name or "new-project").strip()
        if not name:
            return {"success": False, "error": "名称不能为空"}
        target = os.path.join(base, name)
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            return {"success": False, "error": f"创建失败: {e}"}
        _WORKSPACE_ROOT = target
        try:
            agent.set_workspace_root(target)
        except Exception as e:
            _log.warning("agent.set_workspace_root failed: %s", e)
        _broadcast("status_update", _read_status(agent))
        T("WORKSPACE", f"created {target}")
        return {"success": True, "path": target}

    # ── 停止执行 ──
    @app.post("/api/stop")
    async def api_stop():
        agent.stop()
        try:
            _agent_busy_lock.release()
        except RuntimeError:
            pass
        _broadcast("error", {"text": "[已中断]"})
        _broadcast("status_update", _read_status(agent))
        T("SRV-STOP", "agent stopped")
        return {"status": "stopped"}

    # ── 主机工具链探测 ──
    @app.get("/api/env/tools")
    async def api_env_tools():
        try:
            from agent.tools.env_probe import get_env_probe
            probe = get_env_probe()
            data = probe.to_dict()
            return data
        except Exception as e:
            return {"os": "", "total_available": 0, "tools": {}, "error": str(e)}

    # ═══════════════════════════════════════════════
    # WebUI 2.0 — 四大可视化模块 API
    # ═══════════════════════════════════════════════

    # ── S4: 流水线状态看板 ──
    @app.get("/api/pipeline/status")
    async def api_pipeline_status():
        """获取流水线当前执行状态。"""
        try:
            orch = getattr(agent, '_pipeline_orch', None)
            if orch is None:
                return {"active": False, "message": "无活跃流水线"}
            task = orch.get_task()
            if task is None:
                return {"active": False, "message": "无活跃任务"}
            return {
                "active": True,
                "task_id": task.id,
                "goal": task.goal[:200],
                "phase": task.phase.value,
                "plan_text": task.plan_text[:500] if task.plan_text else "",
                "verdict": task.verdict,
                "retry_count": task.retry_count,
                "max_retries": task.max_retries,
                "error": task.error,
                "created_at": task.created_at,
            }
        except Exception as e:
            return {"active": False, "error": str(e)}

    @app.get("/api/pipeline/history")
    async def api_pipeline_history(limit: int = 10):
        """获取流水线历史执行记录。"""
        try:
            if not hasattr(agent, '_pipeline_history'):
                return {"history": []}
            hist = getattr(agent, '_pipeline_history', [])
            return {"history": hist[-limit:]}
        except Exception as e:
            return {"history": [], "error": str(e)}

    # ── S5: Skill & 长期记忆浏览器 ──
    @app.get("/api/skills")
    async def api_skills(query: str = ""):
        """获取技能列表（支持搜索）。"""
        try:
            sm = getattr(agent, 'skill_manager', None)
            if sm is None:
                return {"skills": []}
            if query:
                results = sm.search(query)
            else:
                results = sm.all
            return {"skills": [s.to_dict() for s in results]}
        except Exception as e:
            return {"skills": [], "error": str(e)}

    @app.get("/api/skills/{skill_id}")
    async def api_skill_detail(skill_id: str):
        """获取单个技能详情。"""
        try:
            sm = getattr(agent, 'skill_manager', None)
            if sm is None:
                return {"error": "skill_manager 未初始化"}
            skill = sm.get(skill_id)
            if skill is None:
                return {"error": "技能不存在"}
            return skill.to_dict()
        except Exception as e:
            return {"error": str(e)}

    @app.post("/api/skills/{skill_id}/execute")
    async def api_skill_execute(skill_id: str):
        """执行一个技能（触发 Pipeline）。"""
        try:
            sm = getattr(agent, 'skill_manager', None)
            if sm is None:
                return {"status": "error", "message": "skill_manager 未初始化"}
            skill = sm.get(skill_id)
            if skill is None:
                return {"status": "error", "message": "技能不存在"}
            # 记录使用
            sm.record_usage(skill_id)
            # 通过 Agent 执行
            if skill.steps:
                prompt = f"执行技能: {skill.name}\n\n{skill.description}\n\n步骤:\n"
                for i, step in enumerate(skill.steps, 1):
                    prompt += f"{i}. [{step.action}] {step.target} — {step.description}\n"
                agent.run(prompt)
            return {"status": "ok", "message": f"技能 {skill.name} 已触发执行"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.post("/api/skills/{skill_id}/toggle")
    async def api_skill_toggle(skill_id: str):
        """切换技能置顶状态。"""
        try:
            sm = getattr(agent, 'skill_manager', None)
            if sm is None:
                return {"status": "error"}
            skill = sm.get(skill_id)
            if skill is None:
                return {"status": "error", "message": "技能不存在"}
            sm.update(skill_id, is_pinned=not skill.is_pinned)
            return {"status": "ok", "pinned": not skill.is_pinned}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.delete("/api/skills/{skill_id}")
    async def api_skill_delete(skill_id: str):
        """删除技能。"""
        try:
            sm = getattr(agent, 'skill_manager', None)
            if sm is None:
                return {"status": "error"}
            ok = sm.delete(skill_id)
            return {"status": "ok" if ok else "error"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    @app.get("/api/memory/intents")
    async def api_memory_intents():
        """获取意图历史快照。"""
        try:
            ir = getattr(agent, 'intent_resonator', None)
            if ir is None:
                return {"intents": []}
            history = getattr(ir, '_history', [])
            return {"intents": [
                {
                    "timestamp": s.timestamp,
                    "chars_typed": s.chars_typed,
                    "deletions": s.deletions,
                    "file_switches": s.file_switches,
                } for s in history[-50:]
            ]}
        except Exception as e:
            return {"intents": [], "error": str(e)}

    # ── S3: TraceID 全链路日志检索 ──
    @app.get("/api/logs/traces")
    async def api_logs_traces(trace_id: str = "", limit: int = 50):
        """检索 TraceID 日志。"""
        try:
            dc = getattr(agent, 'debug', None)
            if dc is None:
                return {"traces": []}
            data = getattr(dc, 'data', {})
            # 合并所有事件类型并按时间排序
            events = []
            for tc in list(data.get("tool_calls", [])):
                events.append({
                    "trace_id": trace_id or "global",
                    "type": "tool_call",
                    "name": tc.get("name"),
                    "timestamp": tc.get("timestamp"),
                    "duration_ms": tc.get("duration_ms"),
                    "success": tc.get("success"),
                    "result_preview": tc.get("result_preview", "")[:200],
                })
            for api in list(data.get("api_calls", [])):
                events.append({
                    "trace_id": trace_id or "global",
                    "type": "api_call",
                    "model": api.get("model"),
                    "timestamp": api.get("timestamp"),
                    "tokens": api.get("usage", {}).get("total_tokens", 0),
                    "stop_reason": api.get("stop_reason"),
                })
            for err in list(data.get("errors", [])):
                events.append({
                    "trace_id": trace_id or "global",
                    "type": "error",
                    "source": err.get("source"),
                    "message": err.get("message")[:200],
                    "timestamp": err.get("timestamp"),
                })
            # 按 timestamp 排序
            events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
            return {"traces": events[:limit]}
        except Exception as e:
            return {"traces": [], "error": str(e)}

    @app.get("/api/logs/export/{trace_id}")
    async def api_logs_export(trace_id: str = ""):
        """导出单条 Trace 完整链路日志。"""
        try:
            dc = getattr(agent, 'debug', None)
            if dc is None:
                return {"error": "debug collector 不可用"}
            md = dc.export_markdown()
            return {"markdown": md, "trace_id": trace_id or "global"}
        except Exception as e:
            return {"error": str(e)}

    # ── S2: 可视化配置操作台 ──
    @app.get("/api/config/full")
    async def api_config_full():
        """获取完整配置（含 v2.0 参数）。"""
        cfg = agent.config
        return {
            # LLM
            "model": cfg.get("model", ""),
            "provider": cfg.get("provider", ""),
            "api_key": cfg.get("api_key", ""),
            "base_url": cfg.get("base_url", ""),
            "temperature": cfg.get("temperature", 0.0),
            "max_tokens": cfg.get("max_tokens", 8192),
            "top_p": cfg.get("top_p", 1.0),
            "api_timeout": cfg.get("api_timeout", 30),
            "disable_thinking": cfg.get("disable_thinking", True),
            # 缓存
            "enable_caching": cfg.get("enable_caching", False),
            "max_cache_keys": cfg.get("max_cache_keys", 100),
            # Token 窗口
            "max_context_tokens": cfg.get("max_context_tokens", 0),
            "max_context_messages": cfg.get("max_context_messages", 50),
            "context_compress_at": cfg.get("context_compress_at", 0.85),
            # 执行
            "parallel_tools": cfg.get("parallel_tools", True),
            "tool_timeout": cfg.get("tool_timeout", 60.0),
            "max_tool_calls_per_turn": cfg.get("max_tool_calls_per_turn", 25),
            "max_consecutive_errors": cfg.get("max_consecutive_errors", 5),
            # 沙箱
            "sandbox_mode": cfg.get("sandbox_mode", "disabled"),
            "sandbox_danger_threshold": cfg.get("sandbox_danger_threshold", 80),
            # 流水线
            "workflow_mode": cfg.get("workflow_mode", "agent"),
            "pipeline_max_retries": cfg.get("pipeline_max_retries", 3),
            # Nudge
            "enable_nudge": cfg.get("enable_nudge", True),
            # 记忆
            "enable_memory": cfg.get("enable_memory", True),
            "memory_search_top_k": cfg.get("memory_search_top_k", 5),
            # 权限
            "permission_mode": cfg.get("permission_mode", "auto"),
            # 统计
            "stats": {
                "llm_calls": agent.stats.get("llm_calls", 0),
                "tool_calls": agent.stats.get("tool_calls", 0),
                "tool_errors": agent.stats.get("tool_errors", 0),
                "total_tokens": agent.stats.get("total_tokens", 0),
                "cache_hits_stable": agent.stats.get("cache_hits_stable", 0),
                "cache_misses": agent.stats.get("cache_misses", 0),
                "context_compressions": agent.stats.get("context_compressions", 0),
            },
        }

    @app.post("/api/config/update")
    async def api_config_update(body: ConfigUpdateBody):
        """更新配置（高危参数需 body.confirmed=True 二次确认）。"""
        confirmed = body.confirmed
        updates = body.model_dump(exclude_none=True)
        updates.pop("confirmed", None)
        if not updates:
            return {"status": "error", "message": "没有要更新的参数"}

        # 高危参数检查
        high_risk = [k for k in updates if k in _HIGH_RISK_CONFIG_KEYS]
        if high_risk and not confirmed:
            return {
                "status": "confirm_required",
                "message": f"以下参数为高危配置，请确认: {', '.join(high_risk)}",
                "keys": high_risk,
            }

        changed = []
        needs_rebuild = False
        for key, value in updates.items():
            if key in agent.config:
                old_val = agent.config.get(key)
                agent.config[key] = value
                changed.append(f"{key}: {old_val} -> {value}")
                if key in ("provider", "api_key", "base_url", "model", "api_timeout", "max_tokens", "temperature", "top_p", "disable_thinking"):
                    needs_rebuild = True

        if needs_rebuild:
            try:
                from agent.providers import create_provider
                agent.provider = create_provider(agent.config)
                agent._setup_provider_callbacks()
                _log.info("provider_rebuilt for llm config change")
            except Exception as e:
                _log.warning("provider_rebuild_failed: %s", e)

        # 持久化到磁盘 config.json
        try:
            _config_path = Path(__file__).parent.parent.parent / "config.json"
            with open(_config_path, "w", encoding="utf-8") as f:
                json.dump(agent.config, f, ensure_ascii=False, indent=4)
            _log.info("config_persisted to %s", _config_path)
        except Exception as e:
            _log.warning("config_persist_failed: %s", e)

        _log.info("config_bulk_updated: %s", "; ".join(changed))
        return {"status": "ok", "changed": changed}

    # ── 安全校验拦截 ──
    class ValidateActionBody(BaseModel):
        action: str          # "tool_call" | "config_change" | "skill_execute"
        params: dict = {}
        intent: str = ""

    @app.post("/api/validate")
    async def api_validate_action(body: ValidateActionBody):
        """前置校验：所有下发操作经铁三角验证。"""
        result = {"allowed": True, "reason": "", "risk_level": "low"}

        try:
            # 工具调用校验
            if body.action == "tool_call":
                tool_name = body.params.get("name", "")
                tool_args = body.params.get("args", {})

                # PathValidator
                if hasattr(agent, 'path_validator') and agent.path_validator is not None:
                    safe, reason = agent._validate_tool_path(tool_name, tool_args)
                    if not safe:
                        result["allowed"] = False
                        result["reason"] = f"路径安全校验失败: {reason}"
                        result["risk_level"] = "high"
                        return result

                # DangerScore 对 bash 命令评分
                if tool_name == "bash":
                    cmd = tool_args.get("command", "")
                    from agent.sandbox.danger_score import DangerScore
                    score = DangerScore.score(cmd)
                    threshold = agent.config.get("sandbox_danger_threshold", 80)
                    if score >= threshold:
                        result["allowed"] = False
                        result["reason"] = DangerScore.get_risk_advice(score, cmd)
                        result["risk_level"] = DangerScore.get_risk_level(score)
                        return result

            # 配置变更校验（后端二次确认已由 confirmed 参数处理）
            if body.action == "config_change":
                params = body.params
                high_risk = [k for k in params if k in _HIGH_RISK_CONFIG_KEYS]
                if high_risk:
                    result["confirm_required"] = True
                    result["reason"] = f"高危参数需二次确认: {', '.join(high_risk)}"
                    result["risk_level"] = "high"

            # 技能执行校验
            if body.action == "skill_execute":
                skill_id = body.params.get("skill_id", "")
                if hasattr(agent, 'skill_manager') and agent.skill_manager is not None:
                    skill = agent.skill_manager.get(skill_id)
                    if skill and skill.steps:
                        for step in skill.steps:
                            if step.action in ("bash", "delete", "write"):
                                # 高危操作需确认
                                result["warning"] = f"技能包含 {step.action} 操作，请确认执行范围"
                                result["risk_level"] = "medium"

        except Exception as e:
            result["allowed"] = False
            result["reason"] = f"校验异常: {e}"
            result["risk_level"] = "high"

        return result

    return app


def _read_status(agent) -> dict:
    """读取 Agent 当前状态。"""
    status = {
        "phase": "", "intent": "", "goal": "",
        "decisions": 0, "turn_count": 0,
        "files_modified": 0, "workspace_files": 0,
        "project_type": "", "cognition": False, "execution": False,
        "recent_decisions": [],
    }
    try:
        from agent.core import _HAS_COGNITION as hc, _HAS_EXECUTION as he
        status["cognition"] = hc
        status["execution"] = he
    except Exception:
        pass

    try:
        if agent.task_manager is not None:
            t = agent.task_manager.get_current_task()
            if t:
                status["phase"] = t.current_phase.value
                status["goal"] = t.user_goal[:200]
                status["decisions"] = len(t.decisions)
                status["turn_count"] = t.turn_count
                status["files_modified"] = len(t.modified_files)
                status["recent_decisions"] = [
                    {"desc": d.description[:80], "ts": d.timestamp}
                    for d in t.decisions[-5:]
                ]
    except Exception:
        pass

    try:
        if agent.intent_resonator is not None:
            iv = agent.intent_resonator.get_intent()
            if iv:
                status["intent"] = iv.primary_intent.value
                status["intent_conf"] = round(iv.confidence, 2)
    except Exception:
        pass

    try:
        if agent.workspace_scanner is not None:
            info = agent.workspace_scanner.get_info()
            if info:
                status["workspace_files"] = info.file_count
                status["project_type"] = info.project_type or ""
                status["workspace_root"] = str(info.root_path)
    except Exception:
        pass

    return status
