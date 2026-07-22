#!/usr/bin/env python
"""一键启动 ForgeX Web UI。

Usage:
    python run_web.py
    python run_web.py --port 9090
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agent.web.run import main

if __name__ == "__main__":
    main()
