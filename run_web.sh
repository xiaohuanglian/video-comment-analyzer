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

# 加载本地 .env(存在则导出;内含网关地址/密钥等,已被 git 忽略)
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

echo "启动视频评论分析 Web 界面: http://127.0.0.1:${PORT}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
exec uv run python -m uvicorn api.main:app --host 127.0.0.1 --port "$PORT" --workers 1
