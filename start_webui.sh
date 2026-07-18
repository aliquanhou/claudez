#!/bin/bash
# ClaudeZ v2.2 — Web UI Launcher
cd "$(dirname "$0")"
echo ""
echo "  ⚡ ClaudeZ v2.2 — Web UI Launcher"
echo "  ==================================="
echo ""
echo "  Make sure to set your API key:"
echo "    export CLAUDEZ_API_KEY=sk-your-key-here"
echo ""
python3 main.py --web --port 8080
