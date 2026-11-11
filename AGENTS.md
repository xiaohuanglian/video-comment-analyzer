# AGENTS.md

Guidance for AI coding agents working in this repository.

## 项目

多平台评论采集与分析工作台（Web UI + CLI）：**评论采集 → 评论洞察 → 评论区回复 → 内容选题**。
核心边界：**AI 只发现与起草，人负责确认与发送**。

## 常用命令

```bash
uv sync
uv run pytest tests -q          # 期望全绿
uv run ruff check api tools scripts   # 期望 All checks passed
./run_web.sh                    # 后端 API http://127.0.0.1:8766（启动时自动加载 .env）
cd web_react && npm run dev     # 工作台面板 http://localhost:5173（/api 代理到 8766）
cd web_react && npx tsc -b --noEmit && npx oxlint && npx vitest run
```

- CI 在 `.github/workflows/ci.yml`（push/PR 自动跑 ruff + pytest + 前端三件套 + 构建）。
- 前端测试用 vitest 3。**不要降到 vitest 2**——在本机 Node v26 上它的 worker 会在
  启动阶段挂住（连空测试都跑不起来）。`npm run test:node` 是不依赖 worker 的兜底脚本。

- 本地网关/密钥等配置在 `.env`（git 忽略，模板见 `.env.example`）；LLM 网关需 `LLM_BASE_URL/LLM_API_KEY/LLM_MODEL`。


## 约定

- 改完代码先跑 `uv run pytest tests -q`，通过后再提交；本地改 → 测试 → push。
- 改动被 import 的模块（如 `media_platform/**/login.py`、`api/**`）后，**必须重启 Web 服务**才生效。
- **git 双层结构（2026-10-20）**：主仓库（远程为 **public GitHub**）只管代码；`data/` 与 `docs/` 各有独立的**纯本地嵌套 git 仓库**（无 remote，**永不 push**）——内含评论用户数据、运营策略、实验存储，任何情况下不得推到 GitHub。嵌套 `.git` 本身是物理防线：即使误 `git add -f`，也只会生成 gitlink，文件内容进不了主仓库（已验证）。`browser_data/`（登录态）不进任何仓库。
- 浏览器行为可用环境变量覆盖：`CDP_CONNECT_EXISTING`、`DISABLE_CDP_FALLBACK`。
- 在 `data/` 或 `docs/` 内产生重要变更（实验 freeze/bind/diagnose、手册改版、队列批准）后，在对应目录内 commit：`git -C data add -A && git -C data commit -m "…"`（docs 同理）。
- 主要模块：`api/services/insight/`（`evidence_*` 洞察、`outreach*`/`reply_runner`/`reply_sender` 回复、`content_plan` 选题、`project_profiles` 档案、`profile_suggestion` AI 生成档案、`insight_narrative` AI 解读）。
- **基础设施模块（改它们前先读注释，都是踩过坑的）**：
  - `api/services/json_store.py`：JSON 持久化的唯一底座。锁 + 原子写 + 损坏留档。
    **别再手写 `read_text/json.loads/write_text` 三件套**；损坏时不返回 `[]`
    （那会导致下次保存抹掉历史），抛 `JsonStoreCorruption`。
  - `api/services/llm_config.py`：模型配置唯一解析入口。base URL 一律存**根地址**
    （不带 `/v1`），端点由 `chat_completions_url()` 拼，保证只有一个 `/v1`。
  - `api/services/llm_json.py`：模型 JSON 输出的唯一解析器。别再用 `re.search(r"\{.*\}")`
    ——贪婪正则遇到「示例 JSON + 真正 JSON」会拼出非法字符串。
  - `api/services/error_handlers.py`：统一错误信封
    `{ok:false, error:{code,message,hint,retry_after_seconds}}`，并保留 `detail` 兼容老前端。
  - `api/services/outreach/browser_reply_base.py`：浏览器受控回复的公共连接/登录态逻辑；
    新接平台只写业务差异，别复制 `_connect_browser`。
- **`/api/data/*` 是白名单**：只开放 `comments/wechat/youtube_comments/xhs_browse/analysis/bench`。
  新增可下载目录要显式加进 `data.py:ALLOWED_DIRS`；`data/model_settings.json`、
  `automation/*.json` 等凭据/状态文件永不可通过该接口读取（有测试锁着）。
- **选题 `origin` 是硬约束**：`store.make_topic()` 缺 `origin` 直接报错；
  确实无语料物证时传 `extra={"origin_missing_reason": "..."}`。
- 评论区回复流程：算法筛选 → 人工勾选 → AI 生成 → 人工审核 → 受控发送（最小间隔/每日上限/允许时段）。
- **分类维度（intents / signals / hypotheses）由项目档案驱动**：`project_profiles.intent_label_map` / `signal_label_map` 解析，仪表盘/筛选/CSV/报告/AI 解读均读档案标签。新增行为键还需要在检测层（`evidence_adapter.infer_legacy_signals`）接入，否则不会触发。
- **选题三源（2026-11 落地）**：评论驱动 `api/services/topics/demand.py`（代码筛需求评论 → LLM 只做分组起名 → 用户数/视频数/评论数/点赞数全部由代码回算，模型引用假 comment_id 的分组直接作废；网关挂了自动降级规则聚类）；事件驱动 `topics/event.py`（素材→事实/立场/角度，`validate_grounding` 硬校验"证据片段必须在原文、数字必须在原文"，不过就报错）；洗稿驱动 `topics/rewrite.py`（先出差异化方案让人拍板，再成稿；支持 YouTube/B站/通用文章，小红书抖音明确回"不支持"）。三源共用 `topics/store.py` 的选题库与状态机（planned→drafting→drafted→published/dropped），成稿经 `api/routers/writer.py:save_draft_record` 回写状态。接口：`/api/topics/demand`、`/from-demand`、`/from-event`、`/rewrite/plan`、`/rewrite/draft`、`PATCH /api/topics/{id}`、`/api/topics/stats`。
- 采集节奏与登录：`tools/crawl_pacing.py`（`CrawlPacer`，抖动 + 批量暂停 + 限流退避，B 站/小红书/抖音已接入）、`tools/login_helper.py`（打开登录页 → 轮询 Cookie → 超时抛错，不再 `sys.exit()`）。
- 采集失败与冷却（crawl guard，同一文件 `tools/crawl_pacing.py`）：失败统一成 `code / message / hint / retry_after_seconds`，九种错误码（`RATE_LIMITED`、`NEED_LOGIN`、`PLATFORM_BLOCKED`、`UPSTREAM_BROKEN`、`TIMEOUT`、`NOT_FOUND`、`BAD_INPUT`、`BUSY`、`NEED_SETUP`）由 `classify_failure()` 映射。限流/风控/登录失效会把**整个平台**标记为冷却，状态写在 `cache/crawl_guard/cooldowns.json`（已 gitignore），所以下一次采集（新进程也算）会在启动前被 `ensure_platform_available()` 拦下并说明还要等多久（CLI 退出码 3，接口 409）。抓取中途只做软等待（`CrawlPacer.before_request()`，最多 `CRAWL_GUARD_WAIT_GRACE_SEC`），不打断已拿到的进度；跑通了会自动清掉该平台冷却。每个 client 的 `request()` 还套了平台并发槽位（默认同平台 2 条、全局 4 条，超时返回 `BUSY`），新平台照抄这三处，别各写一份。

## 跨会话续接

如需在本地保存跨会话交接记录，请写在本地的 `docs/` 目录（docs/ 有独立本地 git 保护，可追溯），新会话开始时先读该文件。