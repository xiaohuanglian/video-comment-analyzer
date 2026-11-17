#!/bin/bash
# Finder double-click entry point; preserve errors on screen.
cd "$(dirname "$0")"
./run_web.sh
result=$?
if [ "$result" -ne 0 ]; then
  echo ""
  read -r -p "启动未完成。请保留上方错误并联系维护者。按回车关闭…"
fi
exit "$result"
