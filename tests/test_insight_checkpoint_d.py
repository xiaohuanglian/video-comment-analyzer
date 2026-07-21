# -*- coding: utf-8 -*-
"""Checkpoint D tests: candidate list and outreach drafts."""

from __future__ import annotations

from api.services.insight.analyzer import run_analysis_batch
from api.services.insight.candidates import build_candidates, build_contact_reason
from api.services.insight.export import build_candidates_csv, build_outreach_csv
from api.services.insight.ingestion import ingest_files
from api.services.insight.outreach import generate_outreach_drafts
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run, load_candidates, load_outreach, save_candidates, save_outreach
from api.services.insight.statistics import compute_candidate_score


SAMPLE = """comment_id,content,user_id,nickname
1,看不懂镜像，左右腿分不清,u1,用户1
2,视频镜像把我搞晕了，不知道跟同侧还是反侧,u2,用户2
3,谢谢教练,u3,用户3
4,膝盖旧伤还能练吗,u4,用户4
5,谢谢教练，练完大腿酸是正常的吗？,u5,用户5
"""


def _setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "博主" / "视频_BV1test" / "comments_2026-07-19.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(SAMPLE, encoding="utf-8")
    rel = "健身类/博主/视频_BV1test/comments_2026-07-19.csv"
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    records = ingest_files([rel])
    run_id = "cpd_test"
    config = RunConfig(
        run_id=run_id,
        name="cpd",
        file_paths=[rel],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-07-19T00:00:00Z",
    )
    create_run(config, records)
    run_analysis_batch(run_id, use_mock=True)
    return run_id, config


def test_build_candidates_merges_by_user(tmp_path, monkeypatch):
    run_id, _config = _setup(tmp_path, monkeypatch)
    from api.services.insight.storage import load_results

    doc = build_candidates(load_results(run_id))
    assert doc.total_candidates == 5
    assert all(candidate.user_key for candidate in doc.candidates)
    assert doc.candidates[0].candidate_score >= doc.candidates[-1].candidate_score


def test_build_candidates_persists_json(tmp_path, monkeypatch):
    run_id, _config = _setup(tmp_path, monkeypatch)
    from api.services.insight.storage import load_results

    doc = build_candidates(load_results(run_id))
    save_candidates(run_id, doc)
    saved = load_candidates(run_id)
    assert saved.total_candidates == doc.total_candidates
    assert saved.candidates[0].username


def test_mock_outreach_generation(tmp_path, monkeypatch):
    run_id, config = _setup(tmp_path, monkeypatch)
    from api.services.insight.storage import load_results

    candidates_doc = build_candidates(load_results(run_id))
    keys = [c.user_key for c in candidates_doc.candidates[:2]]
    outreach = generate_outreach_drafts(
        candidates_doc.candidates,
        config,
        user_keys=keys,
        use_mock=True,
    )
    assert len(outreach.entries) == 2
    assert outreach.entries[0].edited_content
    assert outreach.entries[0].model_name == "mock"
    save_outreach(run_id, outreach)
    saved = load_outreach(run_id)
    assert len(saved.entries) == 2


def test_candidates_and_outreach_csv_export(tmp_path, monkeypatch):
    run_id, config = _setup(tmp_path, monkeypatch)
    from api.services.insight.storage import load_results

    candidates_doc = build_candidates(load_results(run_id))
    save_candidates(run_id, candidates_doc)
    outreach = generate_outreach_drafts(
        candidates_doc.candidates,
        config,
        user_keys=[candidates_doc.candidates[0].user_key],
        use_mock=True,
    )
    save_outreach(run_id, outreach)

    candidates_csv = build_candidates_csv(run_id).decode("utf-8-sig")
    outreach_csv = build_outreach_csv(run_id).decode("utf-8-sig")
    assert "user_key" in candidates_csv
    assert "联系理由" in candidates_csv
    assert "生成草稿" in outreach_csv


def test_contact_reason_non_empty_for_high_score():
    analysis = {
        "actual_training_evidence": "continued",
        "help_seeking": True,
        "specific_problems": ["训练时出现局部发力或体感异常"],
        "single_video_relation": "realtime_observation_needed",
        "product_fit": "high",
    }
    score = compute_candidate_score(analysis)
    reason = build_contact_reason(analysis, score)
    assert score >= 7
    assert reason
