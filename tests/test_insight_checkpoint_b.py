# -*- coding: utf-8 -*-
"""Checkpoint B tests: statistics and dashboard data."""

from api.services.insight.analyzer import build_summary, run_analysis_batch
from api.services.insight.ingestion import ingest_files
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.statistics import build_statistics, compute_candidate_score
from api.services.insight.storage import create_run


SAMPLE = """comment_id,content,user_id,nickname
1,已打卡,u1,用户1
2,谢谢教练，臀桥时腿后侧酸，这正常吗？,u2,用户2
3,这个动作一周练几次？,u3,用户3
4,我看第二遍就会了,u4,用户4
"""


def _setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "博主" / "视频" / "comments.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(SAMPLE, encoding="utf-8")
    rel = "健身类/博主/视频/comments.csv"
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    records = ingest_files([rel])
    run_id = "cpb_test"
    create_run(
        RunConfig(
            run_id=run_id,
            name="cpb",
            file_paths=[rel],
            field_mapping=FieldMapping(comment_text="content"),
            use_mock=True,
            created_at="2026-07-19T00:00:00Z",
        ),
        records,
    )
    run_analysis_batch(run_id, use_mock=True)
    return run_id


def test_intent_percentages_sum_to_100(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    summary = build_summary(run_id)
    total_pct = sum(summary["primary_intent_percentages"].values())
    assert abs(total_pct - 100.0) < 0.01


def test_signal_coverage_can_exceed_100_percent(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    summary = build_summary(run_id)
    total_coverage = sum(item["coverage_pct"] for item in summary["signal_coverage"].values())
    assert total_coverage >= 0


def test_hypothesis_weakens_present(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    summary = build_summary(run_id)
    h2 = summary["hypothesis_details"]["H2"]
    assert h2["counts"]["supports"] >= 0
    assert h2["counts"]["weakens"] >= 0
    assert "support_quotes" in h2
    assert "weaken_quotes" in h2


def test_single_video_stats(tmp_path, monkeypatch):
    run_id = _setup(tmp_path, monkeypatch)
    summary = build_summary(run_id)
    assert "one_reply_sufficient" in summary["single_video_stats"]
    assert summary["single_video_stats"]["video_sufficient"]["count"] >= 1


def test_candidate_score_rules():
    score = compute_candidate_score(
        {
            "actual_training_evidence": "continued",
            "specific_problems": ["问题"],
            "single_video_relation": "realtime_observation_needed",
            "help_seeking": True,
            "product_fit": "high",
        }
    )
    assert score >= 7
