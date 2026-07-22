#!/usr/bin/env python
"""ForgeX v0.4.1 — 一键启动动态端口 Web UI。

Usage:
    python run_web.py                    # 自动找可用端口 (8080→8089)
    python run_web.py --port 9090        # 指定端口
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.web.run import main

if __name__ == "__main__":
    main()
