#!/bin/bash
# 启动 Web 界面，同时防止系统空闲休眠（允许屏幕熄灭）。
# caffeinate -i : 阻止「系统空闲睡眠」，但不阻止显示器熄灭 —— 正好是「熄屏但任务继续跑」。
# 注意：合上笔记本盖子仍会睡眠（除非外接显示器+电源+键鼠的蛤壳模式）。
cd "$(dirname "$0")"
exec caffeinate -i ./run_web.sh