# -*- coding: utf-8 -*-
"""Pre-run estimate + large-run confirmation gate for the analyze endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.routers import analysis as analysis_router
from api.services.insight.schemas import FieldMapping, RunConfig, SourceRecord
from api.services.insight.storage import create_run


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def isolated_data(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for mod in (
        "api.services.insight.ingestion",
        "api.services.insight.storage",
        "api.services.insight.run_locations",
    ):
        monkeypatch.setattr(f"{mod}.DATA_DIR", data_dir)
        monkeypatch.setattr(f"{mod}.RUNS_ROOT", data_dir / "runs", raising=False)
    return data_dir


def _make_run(run_id: str, count: int, *, use_mock: bool = False, budget: float = 0.0) -> None:
    records = [
        SourceRecord(
            internal_record_id=f"r{i}",
            source_file="教程类/博主/视频/comments.csv",
            source_row_number=i,
            comment_text=f"这个步骤学了几次还是找不到发力感 {i}",
            user_id=f"u{i}",
            username=f"用户{i}",
        )
        for i in range(count)
    ]
    config = RunConfig(
        run_id=run_id,
        name="guard",
        file_paths=["教程类/博主/视频/comments.csv"],
        field_mapping=FieldMapping(comment_text="comment_text"),
        use_mock=use_mock,
        created_at="2026-01-01T00:00:00Z",
        storage_dir=run_id,
        budget_limit=budget,
    )
    create_run(config, records)


def test_estimate_scales_with_count():
    config = RunConfig(
        run_id="x",
        name="x",
        file_paths=["a.csv"],
        field_mapping=FieldMapping(comment_text="comment_text"),
    )
    small = analysis_router._estimate_batch(config, 10)
    large = analysis_router._estimate_batch(config, 1000)
    assert small["pending"] == 10
    assert large["estimated_cost"] > small["estimated_cost"]
    assert large["estimated_duration_seconds"] > small["estimated_duration_seconds"]


def test_large_run_requires_confirmation(client, isolated_data, monkeypatch):
    monkeypatch.setattr(analysis_router, "LARGE_RUN_CONFIRM_THRESHOLD", 3)
    _make_run("guard_confirm", 5, use_mock=False)

    resp = client.post(
        "/api/analysis/runs/guard_confirm/analyze",
        json={"api_key": "sk-test", "background": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_confirmation"] is True
    assert body["pending"] == 5
    assert body["estimate"]["pending"] == 5


def test_budget_exceeded_is_rejected(client, isolated_data, monkeypatch):
    monkeypatch.setattr(analysis_router, "LARGE_RUN_CONFIRM_THRESHOLD", 10_000)
    _make_run("guard_budget", 50, use_mock=False, budget=0.0000001)

    resp = client.post(
        "/api/analysis/runs/guard_budget/analyze",
        json={"api_key": "sk-test", "background": True},
    )
    assert resp.status_code == 400
    assert "预算" in resp.json()["detail"]


def test_small_run_without_budget_starts(client, isolated_data, monkeypatch):
    monkeypatch.setattr(analysis_router, "LARGE_RUN_CONFIRM_THRESHOLD", 10_000)
    started: dict = {}

    def fake_start(run_id, body, use_mock):
        started["run_id"] = run_id
        return {"run_id": run_id, "background": True, "status": "running"}

    # Stub the background launcher so the test does not spawn a real worker thread.
    monkeypatch.setattr(analysis_router, "_start_analyze_job", fake_start)
    _make_run("guard_ok", 3, use_mock=False)

    resp = client.post(
        "/api/analysis/runs/guard_ok/analyze",
        json={"api_key": "sk-test", "background": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("needs_confirmation") is not True
    assert started.get("run_id") == "guard_ok"
    assert body["estimate"]["pending"] == 3