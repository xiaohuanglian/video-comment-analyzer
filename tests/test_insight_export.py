# -*- coding: utf-8 -*-
"""Export endpoint tests."""

from __future__ import annotations

from api.services.insight.export import auto_export_artifacts, build_report_markdown, build_results_csv
from api.services.insight.ingestion import ingest_files
from api.services.insight.run_locations import run_exists_in_csv_dir
from api.services.insight.run_naming import build_run_id
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import create_run
from api.services.insight.analyzer import run_analysis_batch


def _patch_data_dir(monkeypatch, data_dir):
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)


SAMPLE_CSV = """comment_id,content,user_id,nickname
1,这个动作练完膝盖疼,uid1,用户A
2,感谢博主讲解很清晰,uid2,用户B
"""


def _setup_run(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "健身类" / "博主" / "视频" / "comments.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    _patch_data_dir(monkeypatch, data_dir)

    rel = "健身类/博主/视频/comments.csv"
    records = ingest_files([rel])
    run_id = build_run_id("导出测试", exists=lambda c: run_exists_in_csv_dir([rel], c))
    create_run(
        RunConfig(
            run_id=run_id,
            name="导出测试",
            file_paths=[rel],
            field_mapping=FieldMapping(comment_text="content"),
            use_mock=True,
        ),
        records,
    )
    run_analysis_batch(run_id, use_mock=True)
    return run_id, data_dir


def test_export_results_csv(tmp_path, monkeypatch):
    run_id, _data_dir = _setup_run(tmp_path, monkeypatch)
    content = build_results_csv(run_id)
    text = content.decode("utf-8-sig")
    assert "评论" in text
    assert "用户A" in text or "膝盖疼" in text


def test_export_report_markdown(tmp_path, monkeypatch):
    run_id, _data_dir = _setup_run(tmp_path, monkeypatch)
    report = build_report_markdown(run_id)
    assert "评论洞察报告" in report
    assert "导出测试" in report


def test_auto_export_writes_beside_source_csv(tmp_path, monkeypatch):
    run_id, data_dir = _setup_run(tmp_path, monkeypatch)
    paths = auto_export_artifacts(run_id)
    assert paths["results_csv"].endswith("导出测试_分析结果.csv")
    assert paths["report_md"].endswith("导出测试_洞察报告.md")
    csv_file = data_dir / "健身类" / "博主" / "视频" / "导出测试_分析结果.csv"
    report_file = data_dir / "健身类" / "博主" / "视频" / "导出测试_洞察报告.md"
    assert csv_file.exists()
    assert report_file.exists()
