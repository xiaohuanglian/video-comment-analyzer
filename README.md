# 视频评论分析

从真实评论中发现需求、痛点与商机的采集工具。提供 Web 界面，支持多平台视频/笔记评论抓取、预览与下载。

## 功能

- **Web 采集界面**：选择平台 → 粘贴链接或扫描博主视频 → 批量采集评论
- **创作者排行**：扫描博主全部视频，按评论数排序，多选后一次采集
- **分视频保存**：每条内容独立子文件夹（`data/comments/{标题}_{ID}/`）
- **数据预览**：Web 内预览 CSV/Excel/JSON，支持下载
- **多平台支持**：B 站、抖音、快手、小红书、微博、贴吧、知乎（CLI 全功能；Web MVP 以 B 站为主）

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip
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

浏览器打开 http://127.0.0.1:8766

### 命令行（可选）

```bash
uv run python main.py --help
```

## 项目结构

```
├── api/                 # FastAPI 后端与 Web 路由
├── web_templates/       # Web 页面模板
├── web_static/          # 前端静态资源
├── media_platform/      # 各平台爬虫实现
├── config/              # 平台与运行配置
├── store/               # 数据存储适配
├── data/                # 采集结果（默认忽略，不提交 Git）
├── browser_data/        # 浏览器登录态（默认忽略）
└── tests/               # 测试
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `VC_CRAWLER_COOKIES` | Cookie 登录时传入的 Cookie 字符串 |
| `CDP_CONNECT_EXISTING` | 设为 `1` 时连接已有 Chrome（默认 Web 模式自动启动浏览器） |
| `PORT` | Web 服务端口，默认 `8766` |

## 测试

```bash
uv run pytest tests/test_product_mvp.py -q
```

## 免责声明

本工具仅供学习与研究使用。请遵守各平台服务条款与 robots 规则，合理控制请求频率，不得用于大规模爬取、商业滥用或任何违法用途。使用者需自行承担合规责任。

## License

MIT — 见 [LICENSE](./LICENSE)
