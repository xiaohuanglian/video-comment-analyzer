# -*- coding: utf-8 -*-
"""Checkpoint 1 tests for insight module."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app

from api.services.insight.analyzer import build_summary, run_analysis_batch
from api.services.insight.field_mapping import detect_field_mapping
from api.services.insight.ingestion import ingest_files
from api.services.insight.schemas import CommentAnalysisResult, FieldMapping, PrimaryIntent, RunConfig
from api.services.insight.storage import completed_record_ids, create_run, load_results
from api.services.insight.validation import validate_analysis


SAMPLE_CSV = """comment_id,video_id,content,user_id,nickname,like_count
1,100,这个动作一周练几次？,u1,测试用户,0
2,100,已打卡。,u2,打卡人,1
3,100,谢谢教练，跟着练了一周腰舒服多了，但我做臀桥时大腿后侧酸，这正常吗？,u3,训练者,3
"""


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def sample_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "健身类" / "测试博主" / "视频_BV1test" / "comments_2026-07-19.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")
    return "健身类/测试博主/视频_BV1test/comments_2026-07-19.csv"


def test_detect_comment_column():
    mapping = detect_field_mapping(["comment_id", "content", "nickname"], "健身类/x.csv")
    assert mapping.comment_text == "content"


def test_ingest_preserves_raw_fields(sample_csv):
    records = ingest_files([sample_csv])
    assert len(records) == 3
    assert records[0].raw_data["comment_id"] == "1"
    assert records[0].creator_type == "普通健身类"


def test_mock_analysis_and_resume(sample_csv):
    records = ingest_files([sample_csv])
    run_id = "test_run_1"
    config = RunConfig(
        run_id=run_id,
        name="test",
        file_paths=[sample_csv],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-07-19T00:00:00Z",
    )
    create_run(config, records)
    first = run_analysis_batch(run_id, limit=2, use_mock=True)
    assert first["processed"] == 2
    done_after_first = completed_record_ids(run_id)
    assert len(done_after_first) == 2

    second = run_analysis_batch(run_id, limit=10, use_mock=True)
    assert second["processed"] == 1
    assert len(completed_record_ids(run_id)) == 3


def test_primary_intent_percentages_sum_to_100(sample_csv):
    records = ingest_files([sample_csv])
    run_id = "test_run_summary"
    config = RunConfig(
        run_id=run_id,
        name="test",
        file_paths=[sample_csv],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-07-19T00:00:00Z",
    )
    create_run(config, records)
    run_analysis_batch(run_id, limit=10, use_mock=True)
    summary = build_summary(run_id)
    total_pct = sum(summary["primary_intent_percentages"].values())
    assert abs(total_pct - 100.0) < 0.01


def test_evidence_quote_invalid_is_dropped_not_failing(sample_csv):
    """Token-saving: bad evidence is sanitized away instead of failing the whole paid call."""
    records = ingest_files([sample_csv])
    analysis = CommentAnalysisResult(
        record_id=records[0].internal_record_id,
        primary_intent=PrimaryIntent.QUESTION,
        evidence_quotes=["不存在的句子"],
        confidence=0.8,
    )
    validate_analysis(records[0], analysis)
    assert analysis.evidence_quotes == []


def test_api_list_sources(client, sample_csv, monkeypatch):
    data_root = Path(sample_csv).parents[3]
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_root)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_root)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_root / "analysis_runs")
    flat = client.get("/api/analysis/sources?grouped=false")
    assert flat.status_code == 200
    assert len(flat.json()["files"]) >= 1
    grouped = client.get("/api/analysis/sources?grouped=true")
    assert grouped.status_code == 200
    body = grouped.json()
    assert body["total_files"] >= 1
    assert len(body["groups"]) >= 1


MULTILINE_CSV = '''comment_id,video_id,content,user_id,nickname,avatar,like_count,sub_comment_count,create_time,parent_comment_id,sign
134,123,"第一行
第二行带换行",u1,用户A,https://i0.hdslb.com/bfs/face/196bc8e1e61cd65905cf8b9ffad2a7c58fd94048.jpg,0,0,1710000000,0,""
135,123,普通评论,u2,用户B,https://i0.hdslb.com/bfs/face/abc.jpg,3,1,1710000001,0,""
'''


def test_ingest_multiline_csv_with_avatar_url(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "运康类" / "运动康复陈老师" / "下雨天脚前方甩泥_BV1test" / "comments_2026-07-19.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(MULTILINE_CSV, encoding="utf-8")
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    rel = "运康类/运动康复陈老师/下雨天脚前方甩泥_BV1test/comments_2026-07-19.csv"
    records = ingest_files([rel])
    assert len(records) == 2
    assert "换行" in records[0].comment_text
    assert records[0].like_count == 0
    assert records[1].like_count == 3


def test_safe_int_rejects_url():
    from api.services.insight.utils import safe_int

    assert safe_int("https://i0.hdslb.com/bfs/face/x.jpg") == 0
    assert safe_int("12") == 12
