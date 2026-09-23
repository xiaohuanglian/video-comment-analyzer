# -*- coding: utf-8 -*-
"""Content plan: deterministic topics + drafted content from a mock run."""

from __future__ import annotations

from pathlib import Path

from api.services.insight.analyzer import run_analysis_batch
from api.services.insight.content_plan import (
    _keywords_from,
    _parse_drafts,
    build_content_plan,
    content_plan_markdown,
)
from api.services.insight.ingestion import ingest_files
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run

SAMPLE_CSV = """comment_id,video_id,content,user_id,nickname,like_count
1,100,这个动作一周练几次？,u1,用户A,0
2,100,深蹲膝盖到底怎么摆，求教练指点,u2,用户B,0
3,100,臀桥大腿后侧酸正常吗？,u3,用户C,1
4,100,跟着练了一周腰舒服多了,u4,用户D,2
5,100,收藏了但一直没开始练,u5,用户E,0
"""


def _isolate(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for mod in (
        "api.services.insight.ingestion",
        "api.services.insight.storage",
        "api.services.insight.run_locations",
        "api.services.insight.paths",
    ):
        monkeypatch.setattr(f"{mod}.DATA_DIR", data_dir, raising=False)
        monkeypatch.setattr(f"{mod}.RUNS_ROOT", data_dir / "analysis_runs", raising=False)
    csv_path = data_dir / "健身类" / "博主" / "视频" / "comments_x.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    return "健身类/博主/视频/comments_x.csv"


def test_build_content_plan_from_mock_run(tmp_path, monkeypatch):
    rel = _isolate(tmp_path, monkeypatch)
    records = ingest_files([rel])
    run_id = "content_run"
    config = RunConfig(
        run_id=run_id,
        name="内容测试",
        file_paths=[rel],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-01-01T00:00:00Z",
        analysis_limit=0,
        storage_dir=run_id,
    )
    create_run(config, records)
    run_analysis_batch(run_id, limit=0, use_mock=True)

    doc = build_content_plan(run_id, use_mock=True, max_topics=10, draft_topics=3)
    assert doc.profile_id == "kineo"
    assert doc.topics, "应当至少产出一个内容选题"
    first = doc.topics[0]
    assert first.rank == 1
    assert first.demand_comments >= 1
    assert first.generated is True
    assert first.draft
    assert first.target_platforms

    markdown = content_plan_markdown(doc)
    assert "内容选题与生成" in markdown
    assert "需人工审核" in markdown


def test_keywords_and_draft_parsing():
    keywords = _keywords_from("深蹲膝盖怎么摆")
    assert keywords  # non-empty
    assert "膝盖" in keywords
    parsed = _parse_drafts('{"topics": [{"topic_id": "T1", "title": "x"}]}')
    assert parsed and parsed[0]["topic_id"] == "T1"
    assert _parse_drafts("not json at all") == []