"""Exercise real routing: refreshing UI routes must not swallow API errors."""
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from api.services.workbench_static import install_workbench


@pytest.mark.asyncio
async def test_workbench_routes_and_api_isolation(tmp_path: Path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text('<html lang="zh-CN">工作台</html>')
    (tmp_path / "assets" / "main.js").write_text("console.log('workbench')")
    (tmp_path / "favicon.svg").write_text("<svg />")
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    install_workbench(app, tmp_path)

    @app.get("/late-route")
    def added_later():
        return {"late": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for path in ["/", "/reply-list", "/collect", "/collect/", "/insight", "/automation", "/profiles", "/settings", "/help"]:
            response = await client.get(path)
            assert response.status_code == 200
            assert "工作台" in response.text
            assert response.headers["cache-control"] == "no-cache"
        assert (await client.get("/late-route")).json() == {"late": True}
        assert (await client.get("/api/health")).json() == {"status": "ok"}
        assert (await client.get("/assets/main.js")).status_code == 200
        assert (await client.get("/favicon.svg")).status_code == 200
        for path in ["/api/missing", "/assets/missing.js", "/.env", "/data/model_settings.json", "/missing", "/%2e%2e/.env"]:
            assert (await client.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_missing_build_explains_how_to_start(tmp_path: Path):
    app = FastAPI()
    install_workbench(app, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 503
        assert "run.command" in response.text
        assert "run.bat" in response.text
        assert (await client.get("/api/missing")).status_code == 404
