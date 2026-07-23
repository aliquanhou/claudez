"""ForgeX Web UI — Uvicorn 启动入口（v2.0 加载配置）。"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import webbrowser
from pathlib import Path


def _find_available_port(start_port: int = 8080, max_attempts: int = 10) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port + max_attempts


def main():
    config_path = Path(__file__).parent.parent.parent / "config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from agent.core import Agent
    from .server import _build_app

    agent = Agent(config)
    app = _build_app(agent)

    host = "0.0.0.0"
    port = _find_available_port()
    url = f"http://localhost:{port}"

    print(f"  ClaudeZ 2.0 WebUI")
    print(f"  Model: {config.get('model', 'default')}")
    print(f"  API Key: {'已配置' if config.get('api_key') else '缺失'}")
    print(f"  Listening on {url}")
    print()

    try:
        webbrowser.open(url)
    except Exception:
        pass

    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
