#!/bin/bash
cd "$(dirname "$0")"
source "$HOME/.local/bin/env" 2>/dev/null || true
PORT="${PORT:-8766}"
echo "开发模式启动视频评论分析: http://127.0.0.1:${PORT}"
exec uv run uvicorn api.main:app --host 127.0.0.1 --port "$PORT" --reload
