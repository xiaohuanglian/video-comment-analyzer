@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
uv run uvicorn api.main:app --host 127.0.0.1 --port 8766
pause
