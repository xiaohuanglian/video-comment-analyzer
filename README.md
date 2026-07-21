# 视频评论分析

从真实评论中发现需求、痛点与商机的采集与分析工具。提供 Web 界面，支持多平台视频/笔记评论抓取，以及 **评论洞察**（默认证据分析）与 **找人聊聊**（调研对象与访谈邀请草稿）。

> 详细实现状态见 [`docs/评论洞察-实现状态.md`](docs/评论洞察-实现状态.md)  
> 正式切换交付见 [`docs/证据分析正式切换交付说明.md`](docs/证据分析正式切换交付说明.md)

## 功能

- **Web 采集界面**：选择平台 → 粘贴链接或扫描博主视频 → 批量采集评论
- **评论洞察（默认 `evidence_items_v1`）**：
  - 选择已采集 CSV → 配置 DeepSeek 等 API → 分析 20/50/100/全部条
  - 微批次证据提取 → 代码校验 → 数据集研究 Agent → `research_report.md`
  - 断点续跑、预算上限、停止/继续、失败重试
  - 证据明细与研究报告；legacy 任务仍可读开放主题仪表盘
  - 潜在用户聚合与评分、半自动私信草稿（E2，**不会自动发送**）
  - 高级设置可手动回退 `legacy_per_record`（调试/兼容）
  - 导出分析 CSV、洞察报告、候选用户与联系记录
- **创作者排行**：扫描博主全部视频，按评论数排序，多选后一次采集
- **分视频保存**：每条内容独立子文件夹（`data/` 下按分类/博主/视频组织）
- **多平台支持**：B 站、抖音、快手、小红书等（日常 MVP 以 B 站验证最多）

## 快速开始

### 环境要求

- Python 3.11+
- **[uv](https://github.com/astral-sh/uv)**（推荐）
- Google Chrome / Chromium（用于登录与采集）

### 安装

```bash
git clone https://github.com/xiaohuanglian/video-comment-analyzer.git
cd video-comment-analyzer
uv sync
uv run playwright install chromium
```

### 启动 Web 界面

```bash
./run_web.sh
```

浏览器打开 http://127.0.0.1:8766 → Tab **「2 评论洞察」**

### 评论洞察使用说明

1. **选择文件**：在左侧树中勾选 `data/**/comments_*.csv`
2. **配置 API**：Base URL（如 `https://api.deepseek.com`）、Model（推荐 `deepseek-v4-flash`）、API Key  
   Key 仅保存在浏览器 sessionStorage，**不会写入磁盘**
3. **分析数量**：20 / 50 / 100 / 全部；默认 100 条适合验收
4. **开始分析**：创建任务并后台运行（**默认证据分析引擎**）；未完成时可「继续分析」
5. **历史任务**：下拉加载已有任务；**选新文件会创建新任务**，不会与历史任务合并；旧任务按原 `config.json` 读取
6. **高级回退**：模型面板「高级设置」可选「旧版逐条分析」，仅作用于该新任务
7. **预算暂停**：达到预算上限后提高上限并点「继续分析」；已完成条目不重复计费
8. **下游步骤**（需手动触发）：「找人聊聊」生成候选用户 → 勾选 →「生成私信」→ 编辑后**手动复制发送**
9. **导出**：分析完成后自动写入 CSV 同目录（`{任务名}_分析结果.csv`、`_洞察报告.md`）；生成调研对象/私信后也会自动保存对应 CSV

分析任务保存在：
- **新任务**：`{CSV 所在目录}/.insight/{任务名}/`
- **旧任务（兼容）**：`data/analysis_runs/{任务名_日期}/`
- **证据产物**：`evidence_cards.jsonl`、`research_analysis.json`、`research_report.md`、`candidates.json`

> 本工具默认仅本机使用（`run_web.sh` 绑定 `127.0.0.1`）。API **无鉴权**；请勿将端口暴露到公网。

### 命令行（可选）

```bash
uv run python main.py --help
```

## 项目结构

```
├── api/                 # FastAPI 后端
├── web_templates/       # Web 页面
├── web_static/          # 前端静态资源
├── media_platform/      # 各平台爬虫
├── data/                # 采集与分析结果（默认忽略）
└── tests/               # 测试
```

## 测试

```bash
uv run pytest tests/test_evidence_*.py tests/test_insight*.py -q
```

## 免责声明

本工具仅供学习与研究使用。请遵守各平台服务条款，合理控制请求频率，**不得用于批量骚扰用户**。工具**不提供医学诊断**；涉及伤病、疼痛等评论需人工审慎解读。使用者需自行承担合规责任。

## License

MIT — 见 [LICENSE](./LICENSE)
