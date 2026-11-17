"""Serve the built workbench on the API port, including refreshed SPA routes."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

WORKBENCH_PATHS = {"", "collect", "reply-list", "insight", "automation", "profiles", "settings", "help"}


def install_workbench(app: FastAPI, dist: Path) -> None:
    """Register last, so API endpoints always take precedence.

    Only known UI routes receive index.html. Missing API/static paths must keep
    their 404 instead of returning HTML disguised as a successful API response.
    """
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="workbench-assets")

    async def workbench():
        index = dist / "index.html"
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<title>工作台尚未准备好</title><body style="font-family:sans-serif;'
            'max-width:640px;margin:80px auto;padding:24px;line-height:1.8">'
            '<h1>工作台界面尚未准备好</h1>'
            '<p>请关闭此启动窗口，再双击项目中的 run.command（Mac）或 run.bat（Windows）。'
            '首次启动会准备界面，请等待启动成功提示。</p>'
            '<p>维护者也可在 web_react 目录执行 npm ci 和 npm run build，之后重启服务。</p>'
            '</body></html>',
            status_code=503,
        )
    # Explicit paths leave future API/plugin/test routes reachable even when they
    # are registered after the workbench. A catch-all would shadow those routes.
    for route in sorted(WORKBENCH_PATHS):
        app.add_api_route(f"/{route}", workbench, methods=["GET"], include_in_schema=False)
        if route:
            app.add_api_route(f"/{route}/", workbench, methods=["GET"], include_in_schema=False)
    for name in ("favicon.svg", "icons.svg"):
        asset = dist / name
        if asset.is_file():
            app.add_api_route(
                f"/{name}", _public_asset(asset), methods=["GET"], include_in_schema=False,
            )


def _public_asset(path: Path):
    async def serve():
        return FileResponse(path)
    return serve
