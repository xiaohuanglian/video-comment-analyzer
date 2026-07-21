# -*- coding: utf-8 -*-
"""Analysis batch limit tests (phase 1 quality acceptance)."""

from __future__ import annotations

from api.services.insight.analyzer import run_analysis_batch
from api.services.insight.ingestion import ingest_files
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import completed_record_ids, create_run, load_config, load_progress


def _make_rows(n: int) -> str:
    lines = ["comment_id,content,user_id,nickname"]
    for i in range(n):
        lines.append(f"{i},评论内容{i}，长度测试文本,u{i},用户{i}")
    return "\n".join(lines)


def _setup_run(tmp_path, monkeypatch, *, total: int = 120, analysis_limit: int = 100):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "博主" / "视频" / "comments.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(_make_rows(total), encoding="utf-8")
    rel = "健身类/博主/视频/comments.csv"
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")

    records = ingest_files([rel])
    run_id = "limit_test"
    create_run(
        RunConfig(
            run_id=run_id,
            name="limit",
            file_paths=[rel],
            field_mapping=FieldMapping(comment_text="content"),
            analysis_limit=analysis_limit,
            use_mock=True,
            created_at="2026-07-19T00:00:00Z",
        ),
        records,
    )
    return run_id


def test_analysis_limit_processes_at_most_n(tmp_path, monkeypatch):
    run_id = _setup_run(tmp_path, monkeypatch, total=120, analysis_limit=100)
    result = run_analysis_batch(run_id, use_mock=True)
    assert result["processed"] == 100
    assert result["completed"] == 100
    assert load_progress(run_id).total_records == 120


def test_continue_analysis_does_not_repeat(tmp_path, monkeypatch):
    run_id = _setup_run(tmp_path, monkeypatch, total=120, analysis_limit=100)
    run_analysis_batch(run_id, use_mock=True)
    first_done = completed_record_ids(run_id)
    assert len(first_done) == 100

    second = run_analysis_batch(run_id, use_mock=True)
    assert second["processed"] == 20
    assert second["completed"] == 120
    second_done = completed_record_ids(run_id)
    assert len(second_done) == 120
    assert first_done.issubset(second_done)


def test_analysis_limit_zero_processes_all(tmp_path, monkeypatch):
    run_id = _setup_run(tmp_path, monkeypatch, total=30, analysis_limit=0)
    result = run_analysis_batch(run_id, use_mock=True)
    assert result["completed"] == 30


def test_analysis_limit_saved_in_config(tmp_path, monkeypatch):
    run_id = _setup_run(tmp_path, monkeypatch, analysis_limit=50)
    config = load_config(run_id)
    assert config.analysis_limit == 50


def test_high_priority_candidate_comment_count(tmp_path, monkeypatch):
    from api.services.insight.statistics import build_statistics
    from api.services.insight.storage import load_results

    run_id = _setup_run(tmp_path, monkeypatch, total=4, analysis_limit=0)
    run_analysis_batch(run_id, use_mock=True)
    summary = build_statistics(load_results(run_id), total_records=4)
    assert "high_priority_candidate_comment_count" in summary
    assert summary["high_priority_candidate_comment_count"] >= 0
