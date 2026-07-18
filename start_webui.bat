@echo off
title ClaudeZ Web UI
cd /d "%~dp0"
echo.
echo  ⚡ ClaudeZ v2.2 — Web UI Launcher
echo  ====================================
echo.
echo  Make sure to set your API key first:
echo    set CLAUDEZ_API_KEY=sk-your-key-here
echo.
echo  Or create a config.json in this directory.
echo  Press Ctrl+C to stop.
echo.
python main.py --web --port 8080
pause
