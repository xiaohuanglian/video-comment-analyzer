# -*- coding: utf-8 -*-
"""Growth API smoke tests (TestClient, real HTTP round-trip, mock agent)."""

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.services.growth import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GROWTH_ROOT", tmp_path / "growth")
    return TestClient(app)


def test_products_seed_and_crud(client):
    r = client.get("/api/growth/products")
    assert r.status_code == 200
    assert {p["product_id"] for p in r.json()["products"]} >= {"youvibe", "trainmind"}
    r = client.post("/api/growth/products/seed")
    assert r.status_code == 200


def test_asset_and_signal_flow(client):
    client.post("/api/growth/products/seed")
    r = client.post("/api/growth/products/youvibe/assets", json={
        "asset_id": "a1", "product_id": "youvibe", "title": "AI 动画教程素材",
        "topics": ["AI 动画"], "license_status": "owned",
    })
    assert r.status_code == 200
    r = client.post("/api/growth/products/youvibe/signals", json=[{
        "signal_id": "s1", "product_id": "youvibe", "source_type": "external_comment",
        "need_or_problem": "AI 动画怎么做的",
    }])
    assert r.json()["imported"] == 1
    # 跨产品一致性校验
    bad = client.post("/api/growth/products/youvibe/signals", json=[{
        "signal_id": "s2", "product_id": "trainmind", "source_type": "product_feedback",
    }])
    assert bad.status_code == 400


def test_export_import_and_isolation(client):
    client.post("/api/growth/products/seed")
    bundle = client.get("/api/growth/products/youvibe/export").json()
    assert bundle["product"]["product_id"] == "youvibe"
    assert "signals" in bundle and "assets" in bundle


def test_agent_run_mock_via_api(client):
    client.post("/api/growth/products/seed")
    r = client.post("/api/growth/agent/run", json={
        "product_id": "youvibe",
        "goal": "分析现有数据，找出下周最值得测试的内容方向",
        "use_mock": True,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["final_answer"].startswith("【MOCK")
    assert body["iterations"] >= 3
    # 会话与审计可追溯
    sessions = client.get("/api/growth/agent/sessions", params={"product_id": "youvibe"}).json()["sessions"]
    assert any(s["session_id"] == body["session_id"] for s in sessions)
    audit = client.get("/api/growth/products/youvibe/audit").json()["audit"]
    assert any(a["action"] == "agent_session_end" for a in audit)
