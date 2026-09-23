# AGENTS.md

Guidance for AI coding agents working in this repository.

## 项目

多平台评论采集与分析工作台（Web UI + CLI）：**评论采集 → 评论洞察 → 评论区回复 → 内容选题**。
核心边界：**AI 只发现与起草，人负责确认与发送**。

## 常用命令

```bash
uv sync
uv run pytest tests -q          # 期望全绿
./run_web.sh                    # http://127.0.0.1:8766
```

## 约定

- 改完代码先跑 `uv run pytest tests -q`，通过后再提交；本地改 → 测试 → push。
- 改动被 import 的模块（如 `media_platform/**/login.py`、`api/**`）后，**必须重启 Web 服务**才生效。
- `data/`、`docs/`、`browser_data/` 均为本地运行产物/内部文档，已被 `.gitignore` 忽略，不要提交。
- 浏览器行为可用环境变量覆盖：`CDP_CONNECT_EXISTING`、`DISABLE_CDP_FALLBACK`。
- 主要模块：`api/services/insight/`（`evidence_*` 洞察、`outreach*`/`reply_runner`/`reply_sender` 回复、`content_plan` 选题、`project_profiles` 档案）。
- 评论区回复流程：算法筛选 → 人工勾选 → AI 生成 → 人工审核 → 受控发送（最小间隔/每日上限/允许时段）。

## 跨会话续接

如需在本地保存跨会话交接记录，请写在本地的 `docs/` 目录（不纳入版本库），新会话开始时先读该文件。