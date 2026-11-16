# -*- coding: utf-8 -*-
"""评论洞察 UI 的后端契约。

背景（2026-11-11）：`/api/analysis/*` 有 47 条路由、约 16k 行、完整测试，
但 React 面板**从未接入**——旧前端 `web_static/insight.js` 在移除旧面板时
被删掉，UI 没跟着重建。README 却仍在教用户在「评论洞察」面板操作。

这组测试锁住 InsightPage 依赖的那几个端点的形状，防止前后端再次漂移；
并用 mock 模式真正跑通「建任务 → 分析 → 出报告」，证明这条链路是活的。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """把洞察数据目录指到临时目录，避免碰真实 data/。"""
    from api.services.insight import paths, run_locations, storage

    runs_root = tmp_path / "insight"
    runs_root.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(paths, "RUNS_ROOT", runs_root, raising=False)
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path, raising=False)
    monkeypatch.setattr(storage, "RUNS_ROOT", runs_root, raising=False)
    monkeypatch.setattr(run_locations, "DATA_DIR", tmp_path, raising=False)
    return TestClient(app)


def test_sources_endpoint_shape(client):
    """InsightPage 读的是 `groups`，不是 `categories`（这里曾经写错过）。"""
    body = client.get("/api/analysis/sources").json()
    assert "groups" in body
    assert "categories" not in body
    assert isinstance(body["groups"], list)


def test_profiles_endpoint_exposes_builtin(client):
    profiles = client.get("/api/analysis/profiles").json()["profiles"]
    assert profiles, "至少应有内置档案"
    ids = {p["profile_id"] for p in profiles}
    assert "default" in ids
    # 档案决定分类维度，这两个字段必须在
    assert all("intents" in p and "signals" in p for p in profiles)


def test_pricing_endpoint_shape(client):
    body = client.get("/api/analysis/pricing").json()
    for key in ("model_name", "base_url", "input_price", "output_price", "currency"):
        assert key in body, f"pricing 缺字段 {key}"


def test_runs_endpoint_shape(client):
    body = client.get("/api/analysis/runs").json()
    assert "runs" in body
    assert isinstance(body["runs"], list)


def test_mock_run_end_to_end(client, tmp_path):
    """建任务 → 分析 → 报告，全程不碰真实模型。"""

    # 准备一份最小可分析的评论文件
    csv_path = tmp_path / "comments_test.csv"
    rows = ["comment_id,content,platform,video_id,video_title"]
    rows += [
        f"c{i},我想知道这个具体怎么做 {i} 步,bilibili,BV1,示例视频" for i in range(1, 13)
    ]
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    created = client.post(
        "/api/analysis/runs",
        json={
            "name": "契约测试任务",
            "file_paths": [str(csv_path)],
            "analysis_limit": 12,
            "use_mock": True,
            "profile_id": "default",
        },
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    assert run_id

    # 分析（mock 模式不需要 api_key）
    analyzed = client.post(
        f"/api/analysis/runs/{run_id}/analyze",
        json={"use_mock": True, "background": False},
    )
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert body.get("completed", 0) >= 1, f"mock 分析没有产出：{body}"

    # 报告端点：即使还没有主题归并，也必须返回结构化结果而不是 500
    report = client.get(f"/api/analysis/runs/{run_id}/research-report")
    assert report.status_code == 200, report.text
    payload = report.json()
    assert payload["run_id"] == run_id
    assert "markdown" in payload
    assert "has_report" in payload

    # 运行详情（页面用来展示进度）
    detail = client.get(f"/api/analysis/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json().get("run_id", run_id) == run_id


def test_analyze_requires_key_without_mock(client, tmp_path):
    """红线：真实分析必须显式给 key，不能悄悄用空 key 去调模型。"""
    csv_path = tmp_path / "c.csv"
    csv_path.write_text(
        "comment_id,content\nc1,测试\nc2,测试2\n", encoding="utf-8"
    )
    created = client.post(
        "/api/analysis/runs",
        json={"name": "t", "file_paths": [str(csv_path)], "use_mock": True},
    )
    run_id = created.json()["run_id"]
    response = client.post(
        f"/api/analysis/runs/{run_id}/analyze",
        json={"use_mock": False, "background": False},
    )
    assert response.status_code == 400
    assert "API Key" in response.json()["error"]["message"] or "API Key" in response.text


def test_analyze_uses_server_side_model_config(monkeypatch, tmp_path):
    """设置页配好的网关要能被「开始分析」直接用上（2026-11-13 修）。

    前端从不收集 api_key（也不该收集），而路由原先只认 body.api_key——用户在
    设置页填好 base_url/模型/Key，点「开始分析」仍然 400「需要填写 API Key」，
    页面看着整个坏掉。现在路由走 require_llm_api_key()：入参 → 环境变量 →
    设置页保存的配置。这里只验证「服务端有配置时不再拦」，不真的调模型。
    """
    from api.services import llm_config, model_settings

    monkeypatch.setattr(model_settings, "SETTINGS_PATH", tmp_path / "model_settings.json")
    model_settings.save_model_settings("https://gw.example.com", "m-1", "sk-stored")
    assert llm_config.require_llm_api_key("") == "sk-stored"
    # 请求里显式给的 key 仍然优先
    assert llm_config.require_llm_api_key("sk-body") == "sk-body"


def test_frontend_wires_insight_page():
    """UI 侧的最小断言：路由、导航、API 客户端都要接上。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "web_react" / "src"
    app_tsx = (root / "App.tsx").read_text(encoding="utf-8")
    layout = (root / "components" / "Layout.tsx").read_text(encoding="utf-8")
    api_ts = (root / "lib" / "api.ts").read_text(encoding="utf-8")

    assert "InsightPage" in app_tsx and 'path="insight"' in app_tsx
    assert "/insight" in layout and "评论洞察" in layout
    assert "insightSources" in api_ts and "insightAnalyze" in api_ts

    page = (root / "pages" / "InsightPage.tsx").read_text(encoding="utf-8")
    # 必须显式点击才开始，不能自动触发分析
    assert "开始分析" in page and "insightAnalyze" in page
