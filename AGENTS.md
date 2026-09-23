# AGENTS.md — 视频评论分析（AI 教学与分享方向）

> 新会话/新协作者请先读 [`docs/项目归档与交接.md`](docs/项目归档与交接.md)，再按本文件执行。

## 项目一句话

以 **AI 教学与知识分享** 为主推方向的评论采集与分析应用（Web UI + CLI）。核心边界：**AI 只发现与起草，人负责确认与发送**。

## 快速上手

```bash
cd ~/video-comment-analyzer
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
uv sync
uv run pytest tests -q          # 期望全绿（当前 293 passed）
./run_web.sh                    # http://127.0.0.1:8766
```

## 约定 / 注意

- 改完代码先跑 `uv run pytest tests -q`，绿了再 commit；本地改 → 测试 → push 到 GitHub（不要反过来）。
- 改动 `media_platform/**/login.py` 等被 import 的模块后，**必须重启 Web 服务**才会生效（Python 不会热更新已加载模块）。
- `data/` 是运行产物目录，已被忽略，可安全删除重建。
- 主推功能：`api/services/insight/` 下 `evidence_*`（评论洞察）、`outreach*.py` + `reply_runner.py` + `reply_sender.py`（评论区回复）、`content_plan.py`（内容选题）、`project_profiles.py`（场景档案，默认 `default` 为 AI 教学方向）。
- 评论区回复流程：算法筛选 → 人工勾选 → AI 生成 → 人工逐条审核 → 受控发送（最小间隔/每日上限/允许时段）。
- 上下文快满时优先 `/compact`；需要全新会话时，本文件 + 交接文档即为记忆载体。