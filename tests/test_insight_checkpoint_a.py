# -*- coding: utf-8 -*-
"""Checkpoint A tests: trial sampling and reporting."""

from api.services.insight.ingestion import ingest_files
from api.services.insight.sampling import DEFAULT_SAMPLE_SEED, stratified_sample
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run, save_trial_sample
from api.services.insight.trial_report import build_trial_report


SAMPLE_CSV = """comment_id,content,user_id,nickname
{i},{content},u{i},用户{i}
"""


def _make_records(tmp_path, monkeypatch, count=120):
    data_dir = tmp_path / "data"
    rows = []
    for i in range(count):
        if i % 3 == 0:
            content = "已打卡"
        elif i % 3 == 1:
            content = "谢谢教练，" + ("详细说明" * 20) + "这正常吗？"
        else:
            content = f"问题{i}：这个动作怎么做？"
        rows.append(f"{i},{content},u{i},用户{i}")
    csv_path = data_dir / "健身类" / "博主A" / "视频1" / "comments_2026-07-19.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("comment_id,content,user_id,nickname\n" + "\n".join(rows), encoding="utf-8")
    rel = "健身类/博主A/视频1/comments_2026-07-19.csv"
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    return rel


def test_stratified_sample_reproducible(tmp_path, monkeypatch):
    rel = _make_records(tmp_path, monkeypatch, count=80)
    records = ingest_files([rel])
    first = stratified_sample(records, 50, seed=DEFAULT_SAMPLE_SEED)
    second = stratified_sample(records, 50, seed=DEFAULT_SAMPLE_SEED)
    assert first == second
    assert len(first) == 50
    assert first != [records[i].internal_record_id for i in range(50)]


def test_trial_report_extrapolation(tmp_path, monkeypatch):
    rel = _make_records(tmp_path, monkeypatch, count=20)
    records = ingest_files([rel])
    run_id = "trial_report_run"
    config = RunConfig(
        run_id=run_id,
        name="trial",
        file_paths=[rel],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-07-19T00:00:00Z",
    )
    create_run(config, records)
    sample_ids = stratified_sample(records, 5, seed=42)
    save_trial_sample(run_id, {"sample_size": 5, "seed": 42, "record_ids": sample_ids})

    from api.services.insight.analyzer import run_analysis_batch

    run_analysis_batch(run_id, record_ids=set(sample_ids), use_mock=True)
    report = build_trial_report(run_id)
    assert report["sample_analyzed"] == 5
    assert report["estimated_full_cost"] >= report["actual_cost"]
    assert report["estimated_total_with_margin"] >= report["estimated_full_cost"]
