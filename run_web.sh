#!/bin/bash
# Single-port workbench launcher; keeps existing processes untouched.
set -e
cd "$(dirname "$0")"
source "$HOME/.local/bin/env" 2>/dev/null || true
if ! command -v uv >/dev/null 2>&1; then
  echo "尚未安装启动工具 uv。请按 README 的首次安装说明完成安装后重试。"
  exit 1
fi
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
exec uv run python scripts/start_workbench.py
