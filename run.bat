@echo off
chcp 65001 >nul
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo 尚未安装 uv。请先按 README 的首次安装说明操作。
  pause
  exit /b 1
)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
uv run python scripts/start_workbench.py
if errorlevel 1 pause
