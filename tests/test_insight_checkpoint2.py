# -*- coding: utf-8 -*-
"""Checkpoint 2 tests: Instructor LLM path, budget, API key hygiene."""

from __future__ import annotations

import json

import pytest

from api.services.insight.analyzer import run_analysis_batch
from api.services.insight.ingestion import ingest_files
from api.services.insight.llm_analyzer import estimate_cost
from api.services.insight.schemas import (
    FieldMapping,
    RunConfig,
)
from api.services.insight.storage import create_run, load_config, load_progress


SAMPLE_CSV = """comment_id,video_id,content,user_id,nickname,like_count
1,100,这个动作一周练几次？,u1,测试用户,0
2,100,已打卡。,u2,打卡人,1
3,100,谢谢教练，跟着练了一周腰舒服多了，但我做臀桥时大腿后侧酸，这正常吗？,u3,训练者,3
4,100,看不懂镜像，左右腿分不清,u4,新手,0
5,100,膝盖旧伤还能练吗,u5,康复者,2
"""


@pytest.fixture()
def sample_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "测试博主" / "视频_BV1test" / "comments_2026-07-19.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    return "健身类/测试博主/视频_BV1test/comments_2026-07-19.csv"


def _make_run(sample_csv: str, *, budget_limit: float = 0.0, use_mock: bool = False) -> str:
    records = ingest_files([sample_csv])
    run_id = "cp2_test_run"
    config = RunConfig(
        run_id=run_id,
        name="cp2",
        file_paths=[sample_csv],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=use_mock,
        input_price=0.001,
        output_price=0.002,
        budget_limit=budget_limit,
        created_at="2026-07-19T00:00:00Z",
    )
    create_run(config, records)
    return run_id


def test_estimate_cost_math():
    cost = estimate_cost(2000, 1000, input_price=0.001, output_price=0.002)
    assert cost == pytest.approx(0.004, rel=1e-6)


def test_estimate_cost_with_cache_hits():
    cost = estimate_cost(
        3000,
        500,
        input_price=0.001,
        output_price=0.002,
        prompt_cache_hit_tokens=2500,
        input_price_cache_hit=0.00002,
    )
    assert cost < estimate_cost(3000, 500, input_price=0.001, output_price=0.002)


def test_config_json_never_contains_api_key(sample_csv, tmp_path):
    run_id = _make_run(sample_csv)
    from api.services.insight.storage import _run_dir

    config_path = _run_dir(run_id) / "config.json"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert "api_key" not in raw


def test_real_mode_requires_api_key(sample_csv):
    run_id = _make_run(sample_csv)
    with pytest.raises(ValueError, match="API Key"):
        run_analysis_batch(run_id, limit=1, use_mock=False, api_key="")


def test_api_estimate_endpoint(client):
    response = client.post(
        "/api/analysis/estimate",
        json={"sample_size": 100, "model": {"base_url": "https://api.deepseek.com", "budget_limit": 1}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sample_size"] == 100
    assert body["estimated_cost"] > 0
    assert body["provider_label"] == "DeepSeek V4-Flash"


def test_api_estimate_accepts_large_sample_size(client):
    response = client.post(
        "/api/analysis/estimate",
        json={"sample_size": 150818, "model": {"base_url": "https://api.deepseek.com"}},
    )
    assert response.status_code == 200
    assert response.json()["sample_size"] == 150818


def test_api_verify_model_rejects_invalid_key(client):
    response = client.post(
        "/api/analysis/verify-model",
        json={
            "api_key": "sk-invalid-test-key",
            "model": {"base_url": "https://api.deepseek.com", "model_name": "deepseek-chat"},
        },
    )
    assert response.status_code in (401, 400)


def test_build_run_id_uses_task_name_without_date():
    from api.services.insight.run_naming import build_run_id

    run_id = build_run_id("戴夫健身评论")
    assert run_id == "戴夫健身评论"


def test_api_cancel_run(client, sample_csv, monkeypatch):
    from api.services.insight.ingestion import ingest_files
    from api.services.insight.schemas import FieldMapping, RunConfig
    from api.services.insight.storage import create_run, load_progress

    records = ingest_files([sample_csv])
    run_id = "cancel_test_run"
    config = RunConfig(
        run_id=run_id,
        name="cancel",
        file_paths=[sample_csv],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-07-19T00:00:00Z",
    )
    create_run(config, records)
    progress = load_progress(run_id)
    progress.status = "running"
    from api.services.insight.storage import save_progress

    save_progress(run_id, progress)
    response = client.post(f"/api/analysis/runs/{run_id}/cancel")
    assert response.status_code == 200
    progress = load_progress(run_id)
    assert progress.status == "cancelled"


def test_pricing_auto_detect():
    from api.services.insight.pricing import normalize_model_settings

    data = normalize_model_settings(base_url="https://api.deepseek.com", model_name="deepseek-chat")
    assert data["provider_label"] == "DeepSeek V4-Flash"
    assert "deepseek-v4-flash" in data["model_display"]
    assert data["input_price"] > 0


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from api.main import app

    return TestClient(app)
