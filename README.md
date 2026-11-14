# 增长工作台

面向不同产品的增长与内容运营工作台。首页先读取已有产品资料，围绕 **诊断与取舍 → 增长计划 → 人工确认执行 → 业务观察 → 复盘与经验回流** 组织工作；评论采集、洞察、回复、选题与创作工具继续可用。

当前增长闭环支持 AI/人工起草计划、人工修订与审批、执行事实登记、自定义业务漏斗和人工确认复盘。执行与指标由人登记；采集、写作、发送和发布工具尚未自动关联到增长尝试，不代表全自动运营已经实现。

> 设计原则：**AI 只负责发现与起草，人负责确认与发送。** 所有 AI 生成环节都必须手动点击开始；回复只发送你审核通过的内容，并受频率与时段约束，可随时停止。

## 功能特性

- **先诊断再准备执行**：有产品描述即可起草诊断，不要求先填完整漏斗。诊断包含备选方向、取舍、假设、下一步、交付物及必要问题；引用原文必须出现在本产品提供的资料中。资料变化后标记旧诊断，AI 分析仍需人工核实。
- **可追溯的方法应用**：提供对 Brian Balfour、Reforge、Sean Ellis / Morgan Brown 公开框架的操作化解释，登记适用条件、所需证据、检查步骤及停止条件；模型需说明本次应用理由与证据引用。这不代表作者背书或增长效果已经验证。
- **产品增长闭环**：在增长工作台直接建立与维护统一产品档案，按需逐项确认当前动作需要的信息；按产品隔离计划、尝试、数据和经验。AI 仅保存待审草稿，真实执行需人工确认登记；历史复盘与可复用资产进入下一轮起草上下文。
- **连接与系统设置**：只读展示当前平台执行节奏和已有拦截记录，维护模型连接、账号恢复与费用；打开页面不自动连接模型、登录、解除冷却或修改策略。已配置与连接成功分开显示。关键词、内容时效及根评论选址在回复页的本平台计划中维护，保存不修改发送频率、配额、允许时段或启用开关。
- **可配置业务漏斗**：自定义阶段、首次价值事件、统计单位、转化率分母、目标及观察门槛。未知与零分开；总量/弱归因数据不计算渠道转化率，重复观察快照不累加。
- **多平台采集**：B 站、抖音、快手、小红书、微博、贴吧、知乎的评论抓取（以 B 站为最完整验证路径）。
- **创作者排行**：扫描博主全部内容，按评论数排序，多选后批量采集。
- **评论洞察**：微批次证据抽取 → 代码校验 → 数据集研究 Agent → 可读报告；支持断点续跑、预算上限、停止/继续、失败重试、大任务二次确认，并可一键生成中文 AI 解读。
- **评论区回复**：算法筛选值得回复的用户 → 人工确认 → AI 按用户意图生成回复 → 人工逐条审核 → 受控发送（最小间隔 / 每日上限 / 允许时段）。
- **内容选题**：把评论里反复出现的需求转成可发布选题，并由 AI 生成多形态草稿。
- **公众号采集**：文章/合集批量下载（md+html+图片+**内嵌视频**，含公众号原生 wxv 视频，自动落盘本地）；素材进资料库供选题与文案引用。
- **工作台对话**：独立 AI 助手页，可查询注入的评论运营状态和讨论思路；该聊天入口尚无执行工具，具体操作使用相应页面。
- **选题双轨与写稿**：评论区内生选题 + 「最强视频」博采众长稿；支持去 AI 味等方法学。
- **可配置项目档案**：不同产品/领域可通过 profile 定制研究目标、假设、**分类维度（意图 / 信号）**与内容人设；也可让 AI 根据真实评论一键生成档案，无需改代码即可适配新业务。
- **数据本地化**：API 无鉴权、默认仅绑定 `127.0.0.1`；结果保存在本地 `data/`，可随时导出 CSV / Markdown。

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip
- Google Chrome / Chromium（用于登录与采集）

### 安装与启动

```bash
git clone https://github.com/xiaohuanglian/video-comment-analyzer.git
cd video-comment-analyzer
uv sync
uv run playwright install chromium
./run_web.sh

# 另开终端启动工作台
cd web_react
npm install
npm run dev
```

浏览器打开 [工作台](http://localhost:5173)。后端 API 在 `http://127.0.0.1:8766`，前端自动代理 `/api`。

> 本工具默认仅本机使用（`run_web.sh` 绑定 `127.0.0.1`）。API **无鉴权**，请勿将端口暴露到公网。

### 安全边界

- `/api/data/*` 只开放**采集结果目录**（comments / wechat / youtube_comments /
  xhs_browse / analysis / bench），且只认数据文件扩展名。登录 Cookie、
  API Key、队列与中间态（`model_settings.json`、`automation/*.json`、
  `topics/`、`growth/` 等）不可通过该接口列出或下载。
- 模型配置写入 `data/model_settings.json`（0600），接口只返回脱敏值。
- 回复发送默认受控：最小间隔、每日上限、允许时段、已回复用户冷却；
  任何发送都必须先经人工批准。

## 使用流程

增长工作台：直接选择或新建产品 → 读取已有资料并准备增长诊断 → 核实方向与本次必要信息 → 起草与审核可执行计划 → 人工执行后登记事实 → 按同一批用户与观察周期记录数据 → 确认下一轮继续/调整/停止 → 经验回流。诊断和计划起草使用设置中的模型网关；连接失败或输出校验失败不会保存伪造产物，计划仍可人工填写。

原有评论与内容工具：

1. **采集**：选择平台 → 粘贴链接或扫描博主内容 → 批量采集评论（每条内容保存到独立子文件夹）。
2. **评论洞察**：勾选已采集的评论文件 → 选项目档案与分析数量（100 / 1K / 10K / 全部）→ 点「开始分析」→ 看报告。支持断点续跑、停止与失败重试。
3. **评论区回复**：筛选 → 勾选确认 → AI 生成回复内容 → 逐条审核 → 受控发送。
4. **内容选题**：基于评论需求生成选题与多形态草稿 → 人工审核后再发布。

### 模型 API 配置

在「设置 → 模型网关」填写 Base URL、Model、API Key，保存一次后**全部功能共用**
（对话 / 选题 / 写稿 / 质检 / 洞察 / 回复起草）。

- Base URL 填**根地址**，不用带 `/v1`（带也会被自动去掉，端点只会拼出一个 `/v1`）。
- 默认 Base URL：`https://api.deepseek.com`；默认 Model：`deepseek-v4-flash`。
- 配置保存在服务端本地 `data/model_settings.json`（权限 0600，已被 git 忽略）；
  接口只返回脱敏形式（`sk-****尾4位`），明文不会出现在响应或日志里。
- 未配置 Key 时，可用「演示模式（use_mock）」走通全流程（结果仅用于演示）。

> 也支持环境变量 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`，优先级高于设置页
> （显式请求入参 > 环境变量 > 设置页保存值）。

### 项目档案与多产品切换

一份档案 = 一个产品/账号。不同产品的定位、受众、口吻、禁区**不能混用**，
所以「当前档案」是一个可切换的状态，不是全局默认值。

- **首次使用**：设置页只问 3 个问题（做什么 / 面向谁 / 想搞清楚什么），
  答完即可开始用，并可顺手跑一次切场景。口吻、禁区、参考风格等后续再补。
- **多产品**：设置页「产品档案」可新建 / 切换 / 删除。新建**不会**自动切换——
  避免做着 A 产品，AI 却按 B 产品的口径给你筛评论。
- 存储：`data/project_profiles.json`（`active_profile_id` + `profiles` 列表；
  旧的 `data/strategy/youvibe_account.json` 首次启动自动迁移为其中一个档案，旧文件保留）。
- 接口：`GET/PUT /api/strategy`、`GET/POST /api/strategy/profiles`、
  `PUT /api/strategy/active`、`DELETE /api/strategy/profiles/{id}`、
  `GET /api/strategy/onboarding/questions`、`POST /api/strategy/onboarding`。
- 洞察侧仍可按任务指定档案（`GET /api/analysis/profiles`），
  顺序是「任务指定 → 当前档案 → 内置占位」。

档案除了账号定位（`niche / target_audience / monetization / tone_rules /
forbidden / reference_styles / goal`）与 `target_scenarios`（切场景采纳结果），
还可以定义分类维度：

- `intents`：评论的主要沟通目的分类（如提问 / 反馈 / 不满）。
- `signals`：值得关注的用户表达信号。
- `realtime_tokens` / `personalized_tokens` / `positive_result_tokens`：「一次回复能否解决」的判定词表（实时观察 / 需结合个人情况 / 正向结果）。

仪表盘、筛选、CSV 与报告都会按当前档案显示这些维度。修改 label 或增删维度即可贴合自己的业务，**无需改代码**；也可以点「AI 根据评论生成档案」，让模型基于当前任务的真实评论直接产出建议档案。

> 说明：档案决定分类的**定义与展示**；信号的**检测**目前仍由通用规则引擎完成。重命名 / 裁剪 / 调整展示均可生效，但全新且引擎无法识别的行为信号需要后续接入模型打标。

### 采集节奏与账号安全

采集默认启用「安全模式」：页间隔带随机抖动、每若干页额外暂停、并发数为 1（模仿真人节奏，降低风控概率）。登录环节会打开真实登录页并等待扫码，失败时给出明确提示而不是静默退出。

> 频率越高、单账号请求越多，越容易被平台限流或验证。大批量采集建议放慢节奏、分批进行，或使用小号 / 代理池。

### B 站自动回复（可选）

评论区回复的自动发送目前仅支持 B 站，需在服务端配置登录 Cookie：

```bash
export VCA_OUTREACH_COOKIE="SESSDATA=...; bili_jct=...; ..."
```

其他平台暂不支持自动发送，会保留为手动复制。

## 项目结构

```
├── api/
│   ├── routers/            # HTTP 路由（analysis_artifacts 是从 analysis 拆出的导出/成稿）
│   └── services/
│       ├── insight/        # 评论洞察（证据抽取 → 校验 → 研究 Agent → 报告）
│       ├── outreach/       # 评论区回复（筛选/起草/硬校验/受控发送）
│       ├── topics/         # 内容选题三源（评论/洗稿/事件）
│       ├── growth/         # 增长引擎（独立子系统，CLI + API）
│       ├── llm.py          # 统一 LLM 出口
│       ├── llm_config.py   # 模型配置解析（单一真相源，避免双 /v1）
│       ├── llm_json.py     # 模型 JSON 输出解析（单一实现）
│       ├── json_store.py   # JSON 持久化底座（锁 + 原子写 + 损坏留档）
│       └── error_handlers.py # 统一错误信封
├── web_react/              # React 工作台（Vite+React+Tailwind+Radix，npm run dev @5173）
├── media_platform/         # 各平台爬虫
├── tools/                  # 浏览器、采集节奏、可达性分析等工具
├── scripts/                # 一次性/运维脚本（数据迁移、清理）
├── data/                   # 采集与分析结果（gitignore；独立本地仓库，永不 push）
└── tests/                  # 测试
```

## 开发

```bash
# 后端
uv run pytest tests -q          # 期望全绿
uv run ruff check api tools scripts

# 命令行入口
uv run python main.py --help

# 工作台面板（React，另开终端）
cd web_react && npm install && npm run dev   # http://localhost:5173，/api 自动代理到 8766
cd web_react && npx tsc -b --noEmit && npx oxlint && npx vitest run
```

CI（`.github/workflows/ci.yml`）在每次 push/PR 时跑：`ruff` + `pytest` +
`tsc` + `oxlint` + `vitest` + 构建。

> 前端测试用 vitest 3（vitest 2 在 Node v26 上 worker 会挂住，别降级）。
> `npm run test:node` 是不依赖 worker 的兜底校验，CI 里两个都跑。

LLM 网关等本地配置放在 `.env`（参考 `.env.example`，已被 git 忽略；`run_web.sh` 启动时自动加载）。

公众号视频下载依赖本机 Chrome（Playwright `channel="chrome"`）：公众号原生视频的签名直链需无头浏览器点播捕获，无需登录。

调整浏览器行为（可选，环境变量）：

- `CDP_CONNECT_EXISTING=1`：连接你已手动开启远程调试（端口 9222）的 Chrome，而不是新开一个。
- `DISABLE_CDP_FALLBACK=1`：CDP 启动失败时不回退到 Playwright 持久化上下文。

## 免责声明

本工具仅供学习与研究使用。请遵守各平台服务条款，合理控制请求频率，**不得用于批量骚扰用户**。使用自动回复时请自行确认频率与时段合规，并由使用者承担合规责任。

## License

MIT — 见 [LICENSE](./LICENSE)
