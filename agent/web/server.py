"""ForgeX Web UI — FastAPI 服务器。

API:
  POST /chat    → 发送消息并执行
  GET  /status  → 当前系统状态
  GET  /health  → 健康检查
  GET  /        → index.html
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .models import ChatRequest, ChatResponse, StatusResponse

_log = logging.getLogger("forgex.web")

HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


def create_app(agent) -> FastAPI:
    """创建 FastAPI 应用，挂载 agent 实例。"""
    app = FastAPI(title="ForgeX Web UI", version="0.4.0")

    # 挂载静态文件
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # 线程安全锁
    _lock = threading.Lock()

    @app.get("/")
    async def index():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path))
        return {"error": "index.html not found"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        """接收用户消息，调用 Agent.run()，返回结果。"""
        if not req.message or not req.message.strip():
            return ChatResponse(response="[错误] 消息不能为空")

        with _lock:
            try:
                t0 = time.time()
                result = agent.run(req.message)
                duration = time.time() - t0
                _log.info("chat msg_len=%d duration=%.1fs", len(req.message), duration)
            except Exception as e:
                _log.error("chat error: %s", e)
                return ChatResponse(response=f"[错误] {e}")

        # 提取状态
        phase, intent, decisions, turn_count = _read_state(agent)
        return ChatResponse(
            response=result,
            phase=phase,
            intent=intent,
            decisions=decisions,
            turn_count=turn_count,
        )

    @app.get("/status", response_model=StatusResponse)
    async def status():
        """返回当前系统状态。"""
        return _build_status(agent)

    @app.get("/health")
    async def health():
        return {"status": "ok", "timestamp": time.time()}

    return app


def _read_state(agent) -> tuple[str, str, int, int]:
    """从 agent 中读取关键状态。"""
    phase = ""
    intent = ""
    decisions = 0
    turn_count = 0

    try:
        if agent.task_manager is not None:
            task = agent.task_manager.get_current_task()
            if task:
                phase = task.current_phase.value
                decisions = len(task.decisions)
                turn_count = task.turn_count
    except Exception:
        pass

    try:
        if agent.intent_resonator is not None:
            iv = agent.intent_resonator.get_intent()
            if iv:
                intent = f"{iv.primary_intent.value} ({iv.confidence:.0%})"
    except Exception:
        pass

    return phase, intent, decisions, turn_count


def _build_status(agent) -> StatusResponse:
    """构建完整状态响应。"""
    status = StatusResponse()

    try:
        from agent.core import _HAS_COGNITION as hc, _HAS_EXECUTION as he
        status.cognition = hc
        status.execution = he
    except Exception:
        pass

    phase, intent, decisions, turn_count = _read_state(agent)
    status.phase = phase
    status.intent = intent
    status.decisions_count = decisions
    status.turn_count = turn_count

    try:
        if agent.task_manager is not None:
            task = agent.task_manager.get_current_task()
            if task:
                status.goal = task.user_goal[:200]
                status.modified_files = task.modified_files[-10:]
                status.decisions = [
                    {"description": d.description[:100], "rationale": (d.rationale or "")[:100]}
                    for d in task.decisions[-5:]
                ]
    except Exception:
        pass

    try:
        if agent.workspace_scanner is not None:
            info = agent.workspace_scanner.get_info()
            if info:
                status.workspace_files = info.file_count
                status.project_type = info.project_type or ""
    except Exception:
        pass

    return status
