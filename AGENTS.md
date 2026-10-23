# AGENTS.md

Guidance for AI coding agents working in this repository.

## 项目

多平台评论采集与分析工作台（Web UI + CLI）：**评论采集 → 评论洞察 → 评论区回复 → 内容选题**。
核心边界：**AI 只发现与起草，人负责确认与发送**。

## 常用命令

```bash
uv sync
uv run pytest tests -q          # 期望全绿
./run_web.sh                    # 后端 API http://127.0.0.1:8766（启动时自动加载 .env）
cd web_react && npm run dev     # 工作台面板 http://localhost:5173（/api 代理到 8766）
```

- 本地网关/密钥等配置在 `.env`（git 忽略，模板见 `.env.example`）；LLM 网关需 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`。
- 公众号视频下载用无头 Chrome（`channel="chrome"`）捕获签名直链；不需要登录态。

## 约定

- 改完代码先跑 `uv run pytest tests -q`，通过后再提交；本地改 → 测试 → push。
- 改动被 import 的模块（如 `media_platform/**/login.py`、`api/**`）后，**必须重启 Web 服务**才生效。
- **git 双层结构（2026-10-20）**：主仓库（远程为 **public GitHub**）只管代码；`data/` 与 `docs/` 各有独立的**纯本地嵌套 git 仓库**（无 remote，**永不 push**）——内含评论用户数据、运营策略、实验存储，任何情况下不得推到 GitHub。嵌套 `.git` 本身是物理防线：即使误 `git add -f`，也只会生成 gitlink，文件内容进不了主仓库（已验证）。`browser_data/`（登录态）不进任何仓库。
- 浏览器行为可用环境变量覆盖：`CDP_CONNECT_EXISTING`、`DISABLE_CDP_FALLBACK`。
- 在 `data/` 或 `docs/` 内产生重要变更（实验 freeze/bind/diagnose、手册改版、队列批准）后，在对应目录内 commit：`git -C data add -A && git -C data commit -m "…"`（docs 同理）。
- 主要模块：`api/services/insight/`（`evidence_*` 洞察、`outreach*`/`reply_runner`/`reply_sender` 回复、`content_plan` 选题、`project_profiles` 档案、`profile_suggestion` AI 生成档案、`insight_narrative` AI 解读）。
- 评论区回复流程：算法筛选 → 人工勾选 → AI 生成 → 人工审核 → 受控发送（最小间隔/每日上限/允许时段）。
- **分类维度（intents / signals / hypotheses）由项目档案驱动**：`project_profiles.intent_label_map` / `signal_label_map` 解析，仪表盘/筛选/CSV/报告/AI 解读均读档案标签。新增行为键还需要在检测层（`evidence_adapter.infer_legacy_signals`）接入，否则不会触发。
- 采集节奏与登录：`tools/crawl_pacing.py`（`CrawlPacer`，抖动 + 批量暂停 + 限流退避，B 站/小红书/抖音已接入）、`tools/login_helper.py`（打开登录页 → 轮询 Cookie → 超时抛错，不再 `sys.exit()`）。

## 跨会话续接

如需在本地保存跨会话交接记录，请写在本地的 `docs/` 目录（docs/ 有独立本地 git 保护，可追溯），新会话开始时先读该文件。