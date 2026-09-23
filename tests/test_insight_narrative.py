# -*- coding: utf-8 -*-
"""Plain-language insight readout (template fallback, no API call)."""

from __future__ import annotations

from api.services.insight.analyzer import run_analysis_batch
from api.services.insight.ingestion import ingest_files
from api.services.insight.insight_narrative import build_insight_narrative
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run

SAMPLE_CSV = """comment_id,video_id,content,user_id,nickname,like_count
1,100,请问这个提示词怎么写才稳定？,u1,用户A,0
2,100,照着教程做还是报错，卡住了,u2,用户B,0
3,100,收藏了准备周末试试,u3,用户C,1
4,100,按你的方法跑通了，效果不错,u4,用户D,2
5,100,一直没搞明白怎么接入自己的工作流,u5,用户E,0
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
    csv_path = data_dir / "AI类" / "博主" / "视频" / "comments_x.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    return "AI类/博主/视频/comments_x.csv"


def test_build_narrative_template_without_key(tmp_path, monkeypatch):
    rel = _isolate(tmp_path, monkeypatch)
    records = ingest_files([rel])
    run_id = "narrative_run"
    config = RunConfig(
        run_id=run_id,
        name="解读测试",
        file_paths=[rel],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=True,
        created_at="2026-01-01T00:00:00Z",
        analysis_limit=0,
        storage_dir=run_id,
    )
    create_run(config, records)
    run_analysis_batch(run_id, limit=0, use_mock=True)

    result = build_insight_narrative(run_id, use_mock=True)
    assert result["model_name"] == "template"
    text = result["text"]
    assert "共分析了" in text
    assert "信息信号覆盖率" not in text  # avoid jargon
    assert "单向视频关系" not in text