"""ForgeX Web UI — Uvicorn 启动入口（v0.4.1 动态端口）。"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import webbrowser
from pathlib import Path


def _find_available_port(start_port: int = 8080, max_attempts: int = 10) -> int:
    """从 start_port 开始扫描可用端口。"""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port + max_attempts


def main():
    # 加载配置
    config_path = Path(__file__).parent.parent.parent / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    # 初始化 Agent
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from agent.core import Agent, _HAS_COGNITION, _HAS_EXECUTION

    agent = Agent(config)

    print(f"  ForgeX v0.4.1 Web UI")
    print(f"  Cognition: {'ON' if _HAS_COGNITION else 'OFF'}")
    print(f"  Execution: {'ON' if _HAS_EXECUTION else 'OFF'}")
    print(f"  Model: {config.get('model', 'default')}")
    print()

    # 创建 FastAPI 应用
    from .server import _build_app
    app = _build_app(agent)

    # 动态端口
    host = "0.0.0.0"
    port = _find_available_port()
    url = f"http://localhost:{port}"

    print(f"  Listening on http://{host}:{port}")
    print(f"  Open {url} in browser")
    print()

    # 自动打开浏览器
    try:
        webbrowser.open(url)
    except Exception:
        pass

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
