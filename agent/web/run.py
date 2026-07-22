"""ForgeX Web UI — Uvicorn 启动入口。"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path


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

    print(f"  ForgeX v0.4.0 Web UI")
    print(f"  Cognition: {'ON' if _HAS_COGNITION else 'OFF'}")
    print(f"  Execution: {'ON' if _HAS_EXECUTION else 'OFF'}")
    print(f"  Model: {config.get('model', 'default')}")
    print()

    # 创建 FastAPI 应用
    from .server import create_app
    app = create_app(agent)

    # 启动
    import uvicorn
    host = "0.0.0.0"
    port = 8080
    print(f"  Listening on http://{host}:{port}")
    print(f"  Open http://localhost:{port} in browser")
    print()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
