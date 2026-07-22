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

_log = logging.getLogger("forgex.web")
HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


class SendBody(BaseModel):
    text: str


def _build_app(agent) -> FastAPI:
    app = FastAPI(title="ForgeX Cockpit", version="0.4.0")

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
                # 立即推送 thought 和状态
                _broadcast("thought", {"text": "正在处理你的请求..."})
                _broadcast("status_update", _read_status(agent))

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
                    _broadcast("token", {"text": chunk})
                    if _orig_on_stream:
                        _orig_on_stream(chunk)

                def _on_tool_start(name, args):
                    _broadcast("tool_start", {"name": name, "args": args})
                    _broadcast("status_update", _read_status(agent))
                    if name in ("write", "edit"):
                        fp = args.get("file_path", "")
                        if fp and fp not in _changed_files:
                            _changed_files[fp] = _snap(fp)
                    if _orig_on_tool_start:
                        _orig_on_tool_start(name, args)

                def _on_tool_call(name, args, result, duration):
                    success = not result.startswith("[")
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
                    if role == "assistant":
                        _broadcast("status_update", _read_status(agent))
                    if _orig_on_message:
                        _orig_on_message(role, content)

                agent.on_stream = _on_stream
                agent.on_tool_start = _on_tool_start
                agent.on_tool_call = _on_tool_call
                agent.on_message = _on_message

                # 执行（同步，无内部线程）
                result = agent.run(body.text)

                # 恢复回调
                agent.on_stream = _orig_on_stream
                agent.on_tool_start = _orig_on_tool_start
                agent.on_tool_call = _orig_on_tool_call
                agent.on_message = _orig_on_message

                # 推送完成
                _broadcast("status_update", _read_status(agent))
                if result.startswith("["):
                    _broadcast("error", {"text": result})
                else:
                    _broadcast("done", {"text": result})

            except Exception as e:
                _broadcast("error", {"text": str(e)})
            finally:
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
