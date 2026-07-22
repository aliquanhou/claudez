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


def _build_app(agent) -> FastAPI:
    app = FastAPI(title="ForgeX Cockpit", version="0.4.1")

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

                def _on_tool_start(name, args):
                    T("SRV-CB", f"on_tool_start name={name}")
                    _broadcast("tool_start", {"name": name, "args": args})
                    _broadcast("status_update", _read_status(agent))
                    if name in ("write", "edit"):
                        fp = args.get("file_path", "")
                        if fp and fp not in _changed_files:
                            _changed_files[fp] = _snap(fp)
                    if _orig_on_tool_start:
                        _orig_on_tool_start(name, args)

                def _on_tool_call(name, args, result, duration):
                    success = not (result.startswith("[错误]") or result.startswith("[超时]") or result.startswith("[权限拒绝]"))
                    T("SRV-CB", f"on_tool_call name={name} success={success}")
                    _broadcast("tool_result", {
                        "name": name, "duration_ms": duration,
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
    except Exception:
        pass

    return status
