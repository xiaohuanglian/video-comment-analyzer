"""
视频评论分析 Web API Server
Start command: uvicorn api.main:app --port 8766 --reload
Or: python -m api.main
Or: ./run_web.sh
"""
import asyncio
import contextlib
import logging
import os
import subprocess
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .routers import (
    analysis_artifacts_router,
    analysis_router,
    automation_router,
    bilibili_router,
    chat_router,
    comments_router,
    costs_router,
    crawler_router,
    creator_router,
    data_router,
    growth_router,
    hot_radar_router,
    publish_router,
    strategy_router,
    studio_router,
    topics_router,
    websocket_router,
    wechat_router,
    writer_router,
    youtube_router,
    youvibe_router,
)
from .services.browser_check import probe_browser_launch
from .services.platform_capabilities import PLATFORM_CAPABILITIES

APP_DIR = Path(__file__).parent.parent


def _apply_web_defaults() -> None:
    """Web UI defaults: auto-launch browser; CLI users can opt into existing Chrome via env."""
    import config

    config.WEB_UI_MODE = True
    config.ENABLE_CDP_MODE = True
    config.DISABLE_CDP_FALLBACK = True

    connect_existing = os.environ.get("CDP_CONNECT_EXISTING", "").strip().lower()
    if connect_existing in {"1", "true", "yes", "on"}:
        config.CDP_CONNECT_EXISTING = True
    elif connect_existing in {"0", "false", "no", "off"}:
        config.CDP_CONNECT_EXISTING = False
    else:
        config.CDP_CONNECT_EXISTING = False


_apply_web_defaults()

# Ensure stdout/stderr accept Chinese logs in the uvicorn worker (avoids ascii encode crashes).
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
os.environ.setdefault("PYTHONUTF8", "1")

logger = logging.getLogger("api")


def _configure_logging() -> None:
    """统一日志：原先 api/ 里散落 13 个 print，uvicorn 只转发自己那部分。

    只在该 logger 尚无 handler 时配置，避免 uvicorn --reload 重复叠加。
    """
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    """应用生命周期：启动后台任务、退出时优雅停止。

    2026-11-11：`@app.on_event("startup")` 已被 FastAPI 标记废弃，而且
    从没有对应的 shutdown 钩子——`automation_loop` / `sender_loop` 起的
    task 永远不结束，进程退出时被硬杀。这里迁到 lifespan 并补上关闭路径。
    """
    _configure_logging()

    from api.services.outreach.reply_automation import (
        PLATFORMS,
        get_store,
        reconcile_stuck_sending,
        start_background_tasks,
        stop_background_tasks,
    )

    # 启动自愈：把上次进程中断时卡在 sending 的条目退回待发
    for platform in PLATFORMS:
        try:
            recovered = reconcile_stuck_sending(get_store(platform))
            if recovered:
                logger.warning("[startup] %s 通道有 %s 条回复卡在 sending，已退回待发", platform, recovered)
        except Exception:  # noqa: BLE001 - 自愈失败不该拦住启动
            logger.exception("[startup] %s 通道 reconcile 失败", platform)

    start_background_tasks()
    try:
        yield
    finally:
        await stop_background_tasks()
        logger.info("[shutdown] 后台任务已停止")


_configure_logging()

app = FastAPI(
    title="视频评论分析 WebUI API",
    description="视频评论采集与预览 Web API",
    version="1.0.0",
    lifespan=lifespan,
)

# 统一失败信封：HTTPException / 校验错误 / 未捕获异常都归一成
# {"ok": false, "error": {code, message, hint, retry_after_seconds}}
from .services.error_handlers import install_error_handlers  # noqa: E402

install_error_handlers(app)

# CORS configuration - allow frontend dev server access
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8766",
        "http://localhost:8766",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(crawler_router, prefix="/api")
app.include_router(data_router, prefix="/api")
app.include_router(websocket_router, prefix="/api")
app.include_router(bilibili_router, prefix="/api")
app.include_router(creator_router, prefix="/api")
app.include_router(analysis_router, prefix="/api")
app.include_router(analysis_artifacts_router, prefix="/api/analysis")
app.include_router(growth_router, prefix="/api")
app.include_router(automation_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(topics_router, prefix="/api")
app.include_router(writer_router, prefix="/api")
app.include_router(youvibe_router, prefix="/api")
app.include_router(comments_router, prefix="/api")
app.include_router(strategy_router, prefix="/api")
app.include_router(wechat_router, prefix="/api")
app.include_router(costs_router, prefix="/api")
app.include_router(hot_radar_router, prefix="/api")
app.include_router(publish_router, prefix="/api")
app.include_router(studio_router, prefix="/api")
app.include_router(youtube_router, prefix="/api")


@app.get("/")
async def root():
    """8766 只提供 API;工作台面板在 web_react(默认 http://localhost:5173,/api 自动代理)。"""
    return {
        "message": "视频评论分析 API",
        "workbench": "http://localhost:5173 (cd web_react && npm run dev)",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Avoid noisy 404s from browsers requesting a favicon."""
    return Response(status_code=204)


@app.get("/api/env/check")
async def check_environment():
    """Check runtime dependencies and browser launch capability."""
    import config

    checks: dict = {"uv": False, "browser": {"ok": False}}
    try:
        if sys.platform == "win32":
            loop = asyncio.get_running_loop()
            process = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["uv", "run", "main.py", "--help"],
                    capture_output=True,
                    timeout=30.0,
                    cwd=str(APP_DIR),
                ),
            )
            stdout, stderr = process.stdout, process.stderr
        else:
            process = await asyncio.create_subprocess_exec(
                "uv", "run", "main.py", "--help",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(APP_DIR),
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")
            return {
                "success": False,
                "message": "Python 环境检查失败",
                "error": error_msg[:500],
                "checks": checks,
            }
        checks["uv"] = True
    except asyncio.TimeoutError:
        return {
            "success": False,
            "message": "环境检查超时",
            "error": "命令执行超过 30 秒",
            "checks": checks,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "message": "未找到 uv 命令",
            "error": "请确保 uv 已安装并配置在系统 PATH 中",
            "checks": checks,
        }
    except Exception as e:
        return {
            "success": False,
            "message": "环境检查出错",
            "error": f"{type(e).__name__}: {str(e) or 'Unknown'}",
            "checks": checks,
        }

    browser = probe_browser_launch()
    checks["browser"] = browser
    ready = checks["uv"] and browser.get("ok")
    return {
        "success": ready,
        "message": "环境就绪，首次采集会自动打开 B 站登录页" if ready else "依赖已安装，但未检测到浏览器",
        "browser": browser.get("browser", ""),
        "error": "" if ready else browser.get("error", "浏览器检查失败"),
        "checks": checks,
        "web_mode": {
            "cdp_connect_existing": getattr(config, "CDP_CONNECT_EXISTING", False),
            "disable_cdp_fallback": getattr(config, "DISABLE_CDP_FALLBACK", False),
        },
    }


@app.get("/api/config/platforms")
async def get_platforms():
    """Get list of supported platforms"""
    return {
        "platforms": [
            {"value": value, **capabilities}
            for value, capabilities in PLATFORM_CAPABILITIES.items()
        ]
    }


@app.get("/api/config/defaults")
async def get_config_defaults():
    """Default paths and project info for Web UI"""
    try:
        import config
        save_path = config.SAVE_DATA_PATH or "./data/comments"
    except Exception:
        save_path = "./data/comments"
    return {
        "save_data_path": save_path,
        "project_root": str(APP_DIR.resolve()),
    }


@app.get("/api/config/options")
async def get_config_options():
    """Get all configuration options"""
    return {
        "login_types": [
            {"value": "qrcode", "label": "扫码登录"},
            {"value": "cookie", "label": "Cookie 登录"},
        ],
        "crawler_types": [
            {"value": "search", "label": "搜索模式"},
            {"value": "detail", "label": "详情模式"},
            {"value": "creator", "label": "创作者模式"},
        ],
        "save_options": [
            {"value": "jsonl", "label": "JSONL 文件"},
            {"value": "json", "label": "JSON 文件"},
            {"value": "csv", "label": "CSV 文件"},
            {"value": "excel", "label": "Excel 文件"},
            {"value": "sqlite", "label": "SQLite 数据库"},
            {"value": "db", "label": "MySQL 数据库"},
            {"value": "mongodb", "label": "MongoDB 数据库"},
        ],
    }


if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8766"))
    uvicorn.run(app, host=host, port=port)
