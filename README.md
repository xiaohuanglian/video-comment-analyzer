# 评论工作台

面向团队的多平台评论工具：**采集评论 → 筛选用户 → 起草回复 → 人工审核 → 受控发送**。

## 功能

- **采集评论**：B 站、小红书、抖音等平台；支持链接、关键词、创作者内容扫描，以及本地数据预览/导出。YouTube 支持本地频道清单采集与任务进度。
- **分析与筛选用户**：评论证据分析、需求/意图分类、候选用户筛选、真实语料验证搜索场景、按产品隔离任务。
- **起草回复**：按产品事实和原评论起草，提供推荐与帮助两种模式、质检理由、图片附件；无法支撑的推荐弃写。
- **人工审核与发送**：逐条编辑、批准/拒绝后受控发送；保留每日上限、间隔、允许时段、去重、风控冷却和人工停采。
- **产品档案与设置**：建档、明确切换产品、回复口吻与禁区；独立模型设置、账号异常与费用统计。

## 安装与启动

需要 Python 3.11+、uv、Node.js（建议 22+）及 Chrome/Chromium。

```bash
git clone https://github.com/xiaohuanglian/video-comment-analyzer.git
cd video-comment-analyzer
uv sync
uv run playwright install chromium
./run_web.sh

# 另开终端
cd web_react
npm ci
npm run dev
```

打开 [评论工作台](http://localhost:5173)。API 默认在 `127.0.0.1:8766`，前端代理 `/api`。

1. 在「产品与筛选档案」填写产品事实、目标人群、研究目标及回复口吻；已有产品需明确切换。采集关键词默认为空，在本平台的筛选计划中明确保存，或从当前产品档案带入后确认。
2. 在「连接与设置」配置模型根地址、模型名和 API Key，主动测试连接。
3. 在「采集评论」小批量采集；在「评论洞察与用户筛选」查看需求证据。
4. 在「起草、审核与发送」选择产品/平台、筛选候选、起草、逐条审核，然后受控发送。

B 站使用已登录 Cookie；小红书和抖音的回复使用本机浏览器登录态。根评论发送只支持 B 站。登录、采集和发送是否可用以实际平台检查为准；平台异常时保留冷却，不自动重试解除。

## 配置与数据边界

- 模型配置位于本地 `data/model_settings.json`（权限 0600），API 只返回脱敏 Key。也支持 `.env` 的 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`，环境变量优先。
- Base URL 填根地址，端点由统一解析器拼接，避免重复 `/v1`。
- 数据保存在本地 `data/`；`data/` 与 `docs/` 是独立本地仓库，无 remote、永不 push。`.env`、`browser_data/`、冷却记录均为本地状态，不随代码分发。
- API 无鉴权、仅供本机使用。不要把服务端口开放到公网。
- `/api/data/*` 使用目录白名单；凭据、回复队列与内部状态不可下载。
- AI 只发现与起草，人确认与发送。采集冷却、搜索配额、夜间静默及人工停采仍有效。

## 开发

```bash
uv run pytest tests -q
uv run ruff check api tools scripts tests
cd web_react
npx tsc -b --noEmit
npx oxlint
npx vitest run
npm run test:node
npm run build
```

前端保持 Vitest 3。修改被 import 的后端模块后重启 Web 服务。

结构：`api/routers` 提供采集/分析/档案/回复/设置接口；`api/services/insight` 保留用户需求证据；`api/services/outreach` 负责筛选、起草与受控发送；`media_platform` 与 `tools` 提供采集及平台保护。

## 许可证

MIT。本项目派生自 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)（MIT），保留其原始版权声明，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
