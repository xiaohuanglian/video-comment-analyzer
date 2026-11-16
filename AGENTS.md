# AGENTS.md

Guidance for AI coding agents working in this repository.

## 项目

面向团队的多平台评论工具（Web UI + CLI）：**采集评论 → 筛选用户 → 起草回复 → 人工审核 → 受控发送**。
本仓库只维护这条链路，以及早播 / YouVibe 的相关产品优化。
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
- **git 双层结构（2026-10-20）**：主仓库（远程为 GitHub）只管代码；`data/` 与 `docs/` 各有独立的**纯本地嵌套 git 仓库**（无 remote，**永不 push**）——内含评论用户数据、运营策略、实验存储，任何情况下不得推到 GitHub。嵌套 `.git` 本身是物理防线：即使误 `git add -f`，也只会生成 gitlink，文件内容进不了主仓库（已验证）。`browser_data/`（登录态）不进任何仓库。
- 浏览器行为可用环境变量覆盖：`CDP_CONNECT_EXISTING`、`DISABLE_CDP_FALLBACK`。
- 在 `data/` 或 `docs/` 内产生重要变更（实验 freeze/bind/diagnose、手册改版、队列批准）后，在对应目录内 commit：`git -C data add -A && git -C data commit -m "…"`（docs 同理）。
- 主要模块：`api/services/insight/`（`evidence_*` 洞察、`outreach*`/`reply_runner`/`reply_sender` 回复、`project_profiles` 档案、`profile_suggestion` AI 生成档案、`insight_narrative` AI 解读）。
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
- 评论区回复流程：算法筛选 → 人工勾选 → AI 生成 → 人工审核 → 受控发送（最小间隔/每日上限/允许时段）。
- **根评论（热评）通道（2026-11-11）**：`api/services/outreach/hot_comment.py` 决定「这个视频值不值得发一条根评论」，与「回复某个具体的人」是**两种动作而非替代**（回复=确定触达 1 人；根评论=零通知、靠赞排序抢公域曝光）。判据按播放档归一（`PLAY_TIERS` 的实测中位数），因为同一个 30 赞在 2 千播放里是热评、在 20 万播放里没人看得见。
  - **阈值不许拍脑袋**：改 `PLAY_TIERS` 前先跑 `uv run python scripts/hot_comment_stats.py`（它会合并 `data/comments` 与 `data/automation/comments` 并按 comment_id 去重——不去重的话同一批评论会被算两遍，中位数直接错）。
  - **采样不足时不要猜**：采到少于 `hot_comment_min_sample`（默认 5）条根评论而平台又报告有评论 → 判 `unknown_coverage` 退回回复通道。实测 0–4 条时六成判断是错的。
  - **窗口看评论区，不看视频发布时间**：`hot_comment_max_silence_hours`（默认 720h）判的是「最后一条评论距今多久」。实测评论到达时间中位 753 小时、视频年龄中位 40 天——沿用回复通道的 `freshness_b_hours`（168h，按发布算）会让配额 5 一条都选不出来（93% 讨论被挡在门外）。
  - **只有 B 站能发根评论**（`reply_sender.supports_root_comment`）：小红书/抖音走浏览器自动化，必须先定位到具体评论才能回复，所以 `_run_sender_tick` 对热评条目直接退回待审并说明原因，不许假装成功。
  - 根评论同样要**人工批准**才发（`pending_review → approved`），同一视频不连发（`_hot_busy_videos`），并且**不走 LLM 精筛**（那套 prompt 判「这个人值不值得回」，根评论没有具体的人）。
- **分类维度（intents / signals / hypotheses）由项目档案驱动**：`project_profiles.intent_label_map` / `signal_label_map` 解析，仪表盘/筛选/CSV/报告/AI 解读均读档案标签。新增行为键还需要在检测层（`evidence_adapter.infer_legacy_signals`）接入，否则不会触发。
- **档案（2026-11-11 合并为多档案）**：`project_profiles` 是唯一存储（`data/project_profiles.json`，`{"version":2,"active_profile_id","profiles":[...]}`），一份档案同时含「账号定位」（niche/monetization/tone_rules/forbidden/reference_styles/goal/evidence）与「分析口径」（domain/target_audience/research_goal/词表/`target_scenarios`）。`api/services/strategy.py` 现在只是它的**兼容门面**（`load/save` 带可选 `profile_id`），不要再往里加字段逻辑。
  - **不同产品的档案不能混用**：`active_profile_id` 是可切换的显式状态，`get_active_profile()` 读它；`resolve_profile(config)` 顺序是 run 的 project_id → active → 内置 default。
  - `ProjectProfile` 是 `extra="allow"`（`save()` **保留未知字段**）：曾经的 bug 是 `save()` 按 8 键白名单写盘，`target_scenarios` 被静默丢弃，前端"已采纳"是假成功。写盘前想过滤字段前先想清楚会不会再犯。
  - 新建档案不自动切换（`POST /api/strategy/profiles`），切换要显式 `PUT /api/strategy/active`。中文产品名直接做 id（`_slug` 保留中文），不要退回 ascii-only——否则所有中文产品名会塌成同一个 id 互相覆盖。
  - 引导式建档 `api/services/onboarding.py`（场景服务在 `outreach/scenario.py`）（3 问 → 档案 → 可选顺手切场景）：建档是主流程，切场景失败只写 `scenario_error` 不回滚。
- 采集节奏与登录：`tools/crawl_pacing.py`（`CrawlPacer`，抖动 + 批量暂停 + 限流退避，B 站/小红书/抖音已接入）、`tools/login_helper.py`（打开登录页 → 轮询 Cookie → 超时抛错，不再 `sys.exit()`）。
- 采集失败与冷却（crawl guard，同一文件 `tools/crawl_pacing.py`）：失败统一成 `code / message / hint / retry_after_seconds`，九种错误码（`RATE_LIMITED`、`NEED_LOGIN`、`PLATFORM_BLOCKED`、`UPSTREAM_BROKEN`、`TIMEOUT`、`NOT_FOUND`、`BAD_INPUT`、`BUSY`、`NEED_SETUP`）由 `classify_failure()` 映射。限流/风控/登录失效会把**整个平台**标记为冷却，状态写在 `cache/crawl_guard/cooldowns.json`（已 gitignore），所以下一次采集（新进程也算）会在启动前被 `ensure_platform_available()` 拦下并说明还要等多久（CLI 退出码 3，接口 409）。抓取中途只做软等待（`CrawlPacer.before_request()`，最多 `CRAWL_GUARD_WAIT_GRACE_SEC`），不打断已拿到的进度；跑通了会自动清掉该平台冷却。每个 client 的 `request()` 还套了平台并发槽位（默认同平台 2 条、全局 4 条，超时返回 `BUSY`），新平台照抄这三处，别各写一份。
  - **平台级节奏**（2026-11-12 事故后加）：`compute_crawl_interval(platform)` 会读 `<平台>_CRAWL_SLEEP_SEC` / `_JITTER_SEC`（`_PLATFORM_PACING`）。小红书 20s+12s、抖音 12s+8s、B 站 4s+2s，通用值 3s 只用在没登记的平台上。**新写平台相关等待必须调它，别直接 `asyncio.sleep(config.CRAWLER_MAX_SLEEP_SEC)`** —— 那正是 12 个关键词 40 秒打完、账号进异常的成因（`media_platform/xhs/core.py` 里这类等待已收进 `_pace_sleep()`）。
  - **平台级冷却时长**（`_PLATFORM_COOLDOWN_OVERRIDES`）：B 站封 IP，风控冷却 30 分钟；小红书/抖音封账号，`PLATFORM_BLOCKED` 走 `XHS_BLOCKED_COOLDOWN_SEC=12h` / `DY_BLOCKED_COOLDOWN_SEC=6h`。账号不可替换的平台不要把冷却调短。
  - **验证码必须抛专用异常**：`media_platform/xhs/exception.py:CaptchaError`（继承 `DataFetchError`），并排除在 `@retry` 之外。裸 `Exception` 会被重试 3 次，等于对已被标记的账号补刀 —— 2026-11-11 的 461 事故就是这么恶化的。抛之前要先 `self._pacer.on_failure(exc)` 落冷却，然后调用方 `except CaptchaError` **立即停批**（`scripts/xhs_keyword_notes.py` 会写 `aborted` + `skipped_keywords`）。
  - **账号级限制也走同一个出口**：`PlatformAccessError`（继承 `DataFetchError`）覆盖三种情况——HTTP 401/403/429、业务码 `300011`（账号安全限制，**不是** IP 问题的 `300012`）。它同样排除在 `@retry` 外。注意 `classify_failure()` 里有 `_BLOCKING_EXC_NAMES` 按**类名**优先判 `PLATFORM_BLOCKED`：这类异常的文案常带「限制」「频繁」，走正则会被误判成 `RATE_LIMITED`（15 分钟），把账号级的 12 小时冷却降级。
  - **冷却不能被"跑完了"清掉**（2026-11-12 复核出的真洞）：爬虫把拦截异常 `break` 吞掉后正常返回，`main.py` 会当成跑通并 `clear_platform_cooldown`，刚落的 12 小时冷却当场消失。现在 `main.py` 用 `clear_stale_cooldown(platform, started_at)`：只有冷却的写入时间**早于本次启动**（= 上次遗留）才清。新写爬虫时**不要把平台拦截异常吞成正常返回**——要么 `raise`，要么走同样的判定。
  - **人工停采用 `set_manual_cooldown()`，不要直接改 `cooldowns.json`**：人工条目带 `manual: true`，`clear_stale_cooldown()` 会跳过它——人能判断账号好了没有，采集器不能。用 `clear_platform_cooldown()` 显式解除。（2026-11-12 踩到：手工挂的 72 小时冷却被一次成功的采集当成"上次遗留"清掉了，人工挂牌形同虚设。）
  - **搜索有配额**（`tools/xhs_safety.py`）：单批最多 `XHS_MAX_KEYWORDS_PER_BATCH=4` 个词、每天最多 `XHS_SEARCH_DAILY_LIMIT=6` 次，**在发第一个请求之前**就拒绝（`ensure_batch_allowed`），记账在请求前（被拦也算用掉次数）。词表比单批长时用 `plan_keywords()` 按日期轮转取一批，别固定取前 N 个（后排的词会永远轮不到）。预算落盘在 `cache/crawl_guard/xhs_search_budget.json`，测试里必须 `reset_search_budget` 隔离。爬虫入口（`XiaoHongShuCrawler.search()`）与独立脚本两条路径都接了这道检查——Web 面板「立即采集」走的是前者。
  - **指纹必须从浏览器读**（实现已提升到 `tools/browser_fingerprint.py`，`media_platform/xhs/fingerprint.py` 只剩兼容 re-export）：`user-agent` / `sec-ch-ua` / `sec-ch-ua-platform` / `sec-ch-ua-mobile` 一律取 `read_browser_fingerprint(page)` 的结果，**不要再写死常量**。2026-11-11 事故里同一个会话同时声称 Chrome 126 / 137 / 136，且 UA 说 Mac 而 `sec-ch-ua-platform` 说 Windows——这比"间隔短"更容易被规则直接命中。拿不到就留空（缺头好过错头），`fingerprint_mismatches()` 用来抓回归。浏览器 UA 传 `None` 让它自报，别注入。
  - **search 接口单列一档节奏**：`compute_crawl_interval(platform, kind)` 支持 `kind="search"`（`_PACING_KINDS`，小红书 45s+45s）。搜索是主动在平台库里捞东西，比 detail/feed 敏感得多：同一账号 detail 模式零风控、search 模式 40 秒就被拦。走 search 的路径都要传 `kind="search"`。
  - **夜间静默**（`tools/xhs_safety.py`）：`XHS_QUIET_HOURS_START=1` / `XHS_QUIET_HOURS_END=6`（支持跨零点；两者相等=关闭）。三个入口都显式调 `ensure_not_quiet_hours()`：`main.py`（Web/CLI 采集）、`XiaoHongShuCrawler.search()`、`scripts/xhs_keyword_notes.py`。抛 `QuietHoursActive(SearchBudgetExceeded)`，退出码 3。**没有塞进 `ensure_batch_allowed`**——额度测试要与运行时刻解耦，别为了少写一行把两者绑死。发送侧不用它（已有 09:00–22:00 窗口）。
  - **账号级异常不许被宽容分支吞掉**：`CaptchaError` / `PlatformAccessError` / `IPBlockError` 合称 `BLOCKING_EXCEPTIONS`（`media_platform/xhs/exception.py`）。写 `except DataFetchError`（或更宽的 `except Exception`）时，前面必须有一条 `except BLOCKING_EXCEPTIONS: raise`，否则就是「记一条 error，然后继续把剩下的全打完」——2026-11-11 那次事故的行为。已修：`get_note_detail_async_task`（detail 模式）、`get_comments_all_sub_comments` 的内层分页与外层 per-comment 循环。
  - **抖音（2026-11-12 补课）**：这条线以前是"架子齐全、没有一处生效"——`client.request()` 撞拦截只抛一个裸 `Exception`、**从不写平台冷却**，上层 `except DataFetchError: break` 一吞，`main.py` 反而当成跑通并 `clear_stale_cooldown` 把冷却清掉。
    - 现在 `request()` 的结构是固定的：**判读响应 → 命中就 `self._pacer.on_failure(exc)` 落盘 → 再 `raise`**。判读集中在 `DouYinClient._classify_response()`：401/403 → `PlatformAccessError`（签名失效 "Signature Not Found" 也走这里）、429 → `RateLimitError`、空 body / `"blocked"` → `DouYinAccountBlockedError`、HTML 挑战页含 captcha/secsdk → `CaptchaError`、5xx **不落冷却**（服务端抖动不是账号问题）。**不要去 JSON body 里搜"验证码"这类词**——评论正文本身就会带这些词，会把正常数据判成风控。
    - 类型分两层：`BLOCKING_EXCEPTIONS`（→ 6 小时账号冷却，`DouYinAccountBlockedError` 必须留在 `_BLOCKING_EXC_NAMES` 里，否则文案里的"限制/频繁"会把它降级成 15 分钟）与 `ABORT_EXCEPTIONS = BLOCKING_EXCEPTIONS + (RateLimitError,)`（→ 停批但不长冷却）。翻页/子评论/详情循环里用后者，写在 `except Exception` 之前。
    - **节奏**：`media_platform/douyin/core.py` 的 `_pace_sleep(reason, kind=...)` 是唯一等待入口。detail 走 `DY_CRAWL_SLEEP_SEC=12`+8s 抖动，search 走 `DY_SEARCH_SLEEP_SEC=45`+45s（`_PACING_KINDS` 里登记 `("dy","search")`）。改造前 search 用的是通用 `CRAWLER_MAX_SLEEP_SEC=3`，比 detail 还快 4 倍。
    - **指纹 / webid / msToken**：`browser_version` `engine_version` `os_version` `screen_*` `cpu_core_num` `device_memory` 全部来自 `read_browser_fingerprint` / `read_device_profile`（原来硬写 Chrome 125 / 2560×1440 / 8 核，而 cookie 里的 `stream_recommend_feed_params` 按真实设备写死）。webid 整个会话只认一个（浏览器 `localStorage.user_unique_id` → `byted_acrawler` → 兜底生成并记住），**不许每个请求 `get_web_id()`**。`msToken` 拿不到就整条参数不发，不许发字面量 `msToken=None`。
    - **TLS 指纹**（`tools/httpx_util.py`）：业务接口走 `make_impersonated_client()`（curl_cffi `impersonate="chrome"`，`default_headers=False`），媒体/二维码/短链/代理探活继续走 `make_async_client()`（httpx，20 个调用点）。实测同一个抖音地址 httpx 302 / curl_cffi 200，UA 与 header 完全一致——差别只在 JA3/HTTP2 握手。curl_cffi 不可用时自动退回 httpx 并告警，**不崩**。
    - **搜索配额与夜间静默**（`tools/crawl_safety.py`，平台化版；`tools/xhs_safety.py` 是兼容门面）：抖音 `DY_SEARCH_DAILY_LIMIT=4` / `DY_MAX_KEYWORDS_PER_BATCH=3` / `DY_QUIET_HOURS_START=1` `_END=6`，预算文件 `cache/crawl_guard/dy_search_budget.json`（与小红书分开记账）。`main.py` 的夜间静默已从 `if platform == "xhs"` 改成对所有平台生效。
    - **登录滑块要收敛**（`media_platform/douyin/login.py`）：`DY_SLIDER_MAX_ATTEMPTS=3` / `DY_SLIDER_MAX_REFRESH=1`，**刷新验证码计入尝试次数**，过不去抛 `CaptchaError`（→ 落冷却 → 停），不再 20 次无限刷。`check_login_state` 的 `@retry` 从 600 次/秒收到 150 次/2 秒。
    - **超时也分两级**：业务接口用 `DY_REQUEST_TIMEOUT_SEC=20`（原先硬编码 60，一个挂住的请求要占着浏览器一分钟），媒体下载另有 `MEDIA_MIN_TIMEOUT_SEC=60` 下限（50MB 视频在慢网络上 20s 下不来）。改 `get_aweme_media` 时别把它改回 `self.timeout`。
    - **没有"连续 N 次空响应才判风控"这种门槛**（`DY_BLOCKED_CONSECUTIVE_LIMIT` 写完删掉了）：`_classify_response` 只判空 body / 挑战页 / 业务码报错，正常的空评论页走的是另一条分支，本来就不会误伤；剩下那种单次空 body 要么签名失效要么已被标记，**多打一次是拿账号换确认**。
    - 回归测试在 `tests/test_douyin_crawl_guard.py`（拦截分类/落冷却/跨进程可见/指纹参数/webid 稳定/msToken/search 档/配额/夜间静默接线/滑块收敛/TLS 适配层/超时分级）。
  - **采集档与发送档分离**（`tools/browser_profile.py`）：浏览器档案目录**只有一个来源** `resolve_user_data_dir()`，调试口只有一个来源 `crawl_debug_port()`——平台 core 里不许再自己 `os.path.join("browser_data", config.USER_DATA_DIR % ...)`（测试 `tests/test_browser_profile.py::TestNoHardcodedProfileDirs` 锁着）。默认共用主档；设 `CRAWL_PROFILE_SUFFIX=_collect` + `CRAWL_DEBUG_PORT=9223` 后，采集子进程（`crawler_manager`、`reply_automation._collect_env`）用自己的档案与端口，**且不再向发送侧借 Cookie**（`_xhs_crawl_cookie` 那条链就是「读侧拖垮写侧」的根因）。代价：采集档要单独登录一次。同一账号开两个档案反而像两台设备，所以默认关闭。

## 跨会话续接

如需在本地保存跨会话交接记录，请写在本地的 `docs/` 目录（docs/ 有独立本地 git 保护，可追溯），新会话开始时先读该文件。
## 相关配置入口

模型设置为 `api/services/model_settings.py`，只读系统状态为 `api/services/system_status.py`，接口 `/api/settings/*`。产品场景为 `/api/strategy/scenario/*`。真实 data/docs/.env/browser_data 永远只在本地，仓库中只保留代码。删除功能时同时清理页面、路由、服务、CLI 和客户端类型。
