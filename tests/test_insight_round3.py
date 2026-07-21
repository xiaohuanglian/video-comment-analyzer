# -*- coding: utf-8 -*-
"""Round-3 acceptance tests: merge rules, pagination, score breakdown."""

from __future__ import annotations

from api.services.insight.candidates import build_candidates
from api.services.insight.query_filters import paginate_candidates, paginate_results
from api.services.insight.score_breakdown import explain_candidate_score
from api.services.insight.statistics import compute_candidate_score
from api.services.insight.user_identity import is_mergeable_username, user_key


def test_placeholder_username_not_mergeable():
    assert not is_mergeable_username("用户123")
    assert not is_mergeable_username("")
    assert is_mergeable_username("小明")


def test_different_platform_same_name_not_merged():
    a = user_key({"platform": "bilibili", "username": "同名用户"})
    b = user_key({"platform": "douyin", "username": "同名用户"})
    assert a != b


def test_same_user_id_same_platform_merges():
    source = {"platform": "bilibili", "user_id": "u1", "username": "用户123"}
    assert user_key(source) == "id:bilibili:u1"


def test_build_candidates_respects_user_key(tmp_path, monkeypatch):
    from api.services.insight.analyzer import run_analysis_batch
    from api.services.insight.ingestion import ingest_files
    from api.services.insight.schemas import FieldMapping, RunConfig
    from api.services.insight.storage import create_run, load_results

    sample = """comment_id,content,user_id,nickname
1,看不懂镜像,u1,用户1
2,还是镜像问题,u1,用户1
3,谢谢教练,u2,用户2
"""
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "博主" / "视频" / "comments.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(sample, encoding="utf-8")
    rel = "健身类/博主/视频/comments.csv"
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    run_id = "merge_test"
    create_run(
        RunConfig(
            run_id=run_id,
            name="merge",
            file_paths=[rel],
            field_mapping=FieldMapping(comment_text="content"),
            use_mock=True,
            created_at="2026-07-19T00:00:00Z",
        ),
        ingest_files([rel]),
    )
    run_analysis_batch(run_id, use_mock=True)
    doc = build_candidates(load_results(run_id))
    u1 = [c for c in doc.candidates if c.record_ids and len(c.record_ids) >= 2]
    assert u1
    assert len(u1[0].record_ids) == 2


def test_results_pagination_and_filter():
    rows = [
        {
            "record_id": "1",
            "source": {"comment_text": "镜像问题", "username": "a"},
            "analysis": {"primary_intent": "question", "signals": [], "new_signals": []},
        },
        {
            "record_id": "2",
            "source": {"comment_text": "谢谢教练", "username": "b"},
            "analysis": {"primary_intent": "gratitude_recognition", "signals": ["gratitude"], "new_signals": []},
        },
    ]
    page1 = paginate_results(rows, page=1, page_size=1)
    assert page1["total"] == 2
    assert len(page1["items"]) == 1
    filtered = paginate_results(rows, page=1, page_size=10, keyword="镜像")
    assert filtered["total"] == 1


def test_candidates_pagination():
    from api.services.insight.candidate_schemas import CandidateRecord

    items = [
        CandidateRecord(user_key="a", priority="high", candidate_score=8),
        CandidateRecord(user_key="b", priority="low", candidate_score=2),
    ]
    page = paginate_candidates(items, page=1, page_size=1, priority="high")
    assert page["total"] == 1
    assert page["items"][0]["user_key"] == "a"


def test_score_breakdown_lists_components():
    analysis = {
        "actual_training_evidence": "continued",
        "specific_problems": ["腿后侧酸"],
        "single_video_relation": "realtime_observation_needed",
        "help_seeking": True,
        "product_fit": "high",
    }
    items = explain_candidate_score(analysis)
    assert items
    assert compute_candidate_score(analysis) == sum(item["points"] for item in items)
