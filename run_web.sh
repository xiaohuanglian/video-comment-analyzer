#!/bin/bash
cd "$(dirname "$0")"
source "$HOME/.local/bin/env" 2>/dev/null || true
PORT="${PORT:-8766}"

if lsof -ti :"$PORT" >/dev/null 2>&1; then
  echo "端口 ${PORT} 已被占用，正在停止旧进程..."
  kill $(lsof -ti :"$PORT") 2>/dev/null || true
  sleep 1
  if lsof -ti :"$PORT" >/dev/null 2>&1; then
    kill -9 $(lsof -ti :"$PORT") 2>/dev/null || true
    sleep 1
  fi
fi

echo "启动视频评论分析 Web 界面: http://127.0.0.1:${PORT}"
exec uv run uvicorn api.main:app --host 127.0.0.1 --port "$PORT" --workers 1
