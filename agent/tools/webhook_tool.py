"""tools/webhook_tool — Webhook 远程触发工具。

让 Agent 可以：
  - 启动/停止 Webhook 服务器
  - 查看任务状态
  - 设置 API Key
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .registry import tool
from ..webhook import (
    WebhookManager, get_webhook_manager, create_webhook_app,
)


# ── 服务器状态 ──

_server_thread: threading.Thread | None = None
_server_running: bool = False
_server_host: str = "127.0.0.1"
_server_port: int = 8765


@tool(category="webhook", timeout=30)
def webhook(action: str = "start", host: str = "127.0.0.1",
            port: int = 8765, api_key: str = "",
            task_id: str = "") -> str:
    """Webhook 远程触发 — 启动 HTTP 服务接收远程任务。

    通过 FastAPI 提供 REST API，支持远程触发 Agent 执行。

    Args:
        action: 操作类型
            start — 启动 Webhook 服务器
            stop — 停止 Webhook 服务器
            status — 查看服务器状态
            set_key — 设置 API Key
            tasks — 列出最近的任务
            task — 查看单个任务详情
        host: 监听地址（start 时使用）
        port: 监听端口（start 时使用）
        api_key: API Key（set_key 时使用）
        task_id: 任务 ID（task 时使用）
    """
    global _server_thread, _server_running, _server_host, _server_port

    manager = get_webhook_manager()

    # ── 启动服务器 ──
    if action == "start":
        if _server_running:
            return f"[信息] Webhook 服务器已在运行: http://{_server_host}:{_server_port}"

        if api_key:
            manager.set_api_key(api_key)

        _server_host = host
        _server_port = port

        def run_server():
            global _server_running
            _server_running = True
            try:
                import uvicorn
                app = create_webhook_app()
                uvicorn.run(app, host=host, port=port, log_level="warning")
            except Exception as e:
                print(f"[Webhook] 服务器错误: {e}")
            finally:
                _server_running = False

        _server_thread = threading.Thread(target=run_server, daemon=True)
        _server_thread.start()

        return json.dumps({
            "url": f"http://{host}:{port}",
            "health": f"http://{host}:{port}/health",
            "trigger": f"POST http://{host}:{port}/webhook",
            "api_key": api_key or "(未设置)",
            "message": f"Webhook 服务器已启动: http://{host}:{port}",
        }, ensure_ascii=False)

    # ── 停止服务器 ──
    if action == "stop":
        if not _server_running:
            return "[信息] Webhook 服务器未运行"
        # 通过请求 /shutdown 停止
        try:
            import requests
            requests.post(f"http://{_server_host}:{_server_port}/shutdown", timeout=2)
        except Exception:
            pass
        _server_running = False
        return "[完成] Webhook 服务器已停止"

    # ── 查看状态 ──
    if action == "status":
        if _server_running:
            return (
                f"Webhook 服务器状态: 运行中\n"
                f"地址: http://{_server_host}:{_server_port}\n"
                f"健康检查: http://{_server_host}:{_server_port}/health\n"
                f"触发端点: POST http://{_server_host}:{_server_port}/webhook\n"
                f"API Key: {'已设置' if manager._api_key else '未设置'}"
            )
        return "Webhook 服务器状态: 未运行"

    # ── 设置 API Key ──
    if action == "set_key":
        if not api_key:
            return "[错误] 需要 api_key 参数"
        manager.set_api_key(api_key)
        return f"[完成] API Key 已设置"

    # ── 列出任务 ──
    if action == "tasks":
        tasks = manager.list_tasks(20)
        if not tasks:
            return "(无任务记录)"
        lines = ["最近任务:"]
        for t in tasks:
            lines.append(f"  [{t['status']}] {t['id']}: {t['prompt'][:60]}...")
        return "\n".join(lines)

    # ── 查看单个任务 ──
    if action == "task":
        if not task_id:
            return "[错误] 需要 task_id 参数"
        task = manager.get_task(task_id)
        if not task:
            return f"[错误] 未找到任务: {task_id}"
        return json.dumps(task.to_dict(), ensure_ascii=False, indent=2)

    return f"[错误] 未知操作: {action}"
