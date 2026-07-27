# -*- coding: utf-8 -*-
"""Export endpoint tests."""

from __future__ import annotations

from api.services.insight.export import auto_export_artifacts, build_report_markdown, build_results_csv
from api.services.insight.ingestion import ingest_files
from api.services.insight.run_locations import run_exists_in_csv_dir
from api.services.insight.run_naming import build_run_id
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import (
    create_run,
    load_semantic_review,
    load_source_records,
    save_semantic_review,
    save_themes,
)
from api.services.insight.theme_schemas import ThemeRecord, ThemesDocument
from api.services.insight.analyzer import build_summary, run_analysis_batch


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


def _save_reviewed_themes(run_id: str, doc: ThemesDocument) -> None:
    save_themes(run_id, doc)
    semantic = load_semantic_review(run_id)
    semantic["open_themes"] = {
        "reviews": [
            {
                "claim_id": f"open_theme:{theme.theme_id}",
                "verdict": "supported",
            }
            for theme in doc.themes
        ]
    }
    source_files = {record.source_file for record in load_source_records(run_id)}
    semantic["per_source_open_theme_ids"] = {
        source_file: [theme.theme_id for theme in doc.themes]
        for source_file in source_files
    }
    save_semantic_review(run_id, semantic)


def test_export_results_csv(tmp_path, monkeypatch):
    run_id, _data_dir = _setup_run(tmp_path, monkeypatch)
    content = build_results_csv(run_id)
    text = content.decode("utf-8-sig")
    assert "评论" in text
    assert "用户A" in text or "膝盖疼" in text


def test_export_report_markdown(tmp_path, monkeypatch):
    run_id, _data_dir = _setup_run(tmp_path, monkeypatch)
    report = build_report_markdown(run_id)
    assert "评论洞察决策报告" in report
    assert "导出测试" in report
    assert "## 任务概况" not in report
    assert "Prompt Tokens" not in report
    assert "Completion Tokens" not in report


def test_auto_export_writes_beside_source_csv(tmp_path, monkeypatch):
    run_id, data_dir = _setup_run(tmp_path, monkeypatch)
    paths = auto_export_artifacts(run_id)
    assert paths["results_csv"].endswith("视频_评论分析_分析结果.csv")
    assert "report_md" not in paths
    csv_file = data_dir / "健身类" / "博主" / "视频" / "视频_评论分析_分析结果.csv"
    report_file = data_dir / "健身类" / "博主" / "视频" / "视频_评论分析_洞察报告.md"
    assert csv_file.exists()
    assert not report_file.exists()
    _save_reviewed_themes(
        run_id, ThemesDocument(created_at="2026-07-22T00:00:00Z")
    )
    auto_export_artifacts(run_id)
    assert report_file.exists()
    report = report_file.read_text(encoding="utf-8")
    assert "评论洞察决策报告" in report
    assert "主要沟通目的" in report
    assert "单向视频关系" in report
    assert "访谈与实验" not in report
    assert "访谈结果按首页" not in report
    assert "## 当前优先行动" in report


def test_open_themes_refresh_exported_research_report(tmp_path, monkeypatch):
    run_id, data_dir = _setup_run(tmp_path, monkeypatch)
    record_ids = [record.internal_record_id for record in load_source_records(run_id)]
    _save_reviewed_themes(
        run_id,
        ThemesDocument(
            created_at="2026-07-22T00:00:00Z",
            raw_signal_count=2,
            themes=[
                ThemeRecord(
                    theme_id="OT1",
                    theme_name="动作疼痛反馈",
                    theme_type="problem",
                    definition="用户练习后反馈膝盖疼痛",
                    implication="先验证动作安全提示",
                    record_ids=record_ids,
                    representative_quotes=["这个动作练完膝盖疼"],
                )
            ],
        ),
    )

    assembled = build_report_markdown(run_id)
    assert "## 开放主题（归并结果）" in assembled
    assert "动作疼痛反馈" in assembled
    assert assembled.count("## 开放主题（归并结果）") == 1
    assert "开放主题覆盖率" in assembled or "主要主题覆盖率" in assembled

    auto_export_artifacts(run_id)
    report_file = data_dir / "健身类" / "博主" / "视频" / "视频_评论分析_洞察报告.md"
    exported = report_file.read_text(encoding="utf-8")
    assert "动作疼痛反馈" in exported
    assert "主要沟通目的" in exported


def test_multi_video_exports_are_scoped_per_source(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    first = data_dir / "健身类" / "博主" / "视频A" / "comments.csv"
    second = data_dir / "健身类" / "博主" / "视频B" / "comments.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        "comment_id,content,user_id,nickname\n1,动作A练完疼,u1,甲\n",
        encoding="utf-8",
    )
    second.write_text(
        "comment_id,content,user_id,nickname\n2,动作B练完舒服,u2,乙\n",
        encoding="utf-8",
    )
    _patch_data_dir(monkeypatch, data_dir)
    paths = ["健身类/博主/视频A/comments.csv", "健身类/博主/视频B/comments.csv"]
    records = ingest_files(paths)
    run_id = "多视频导出"
    create_run(
        RunConfig(
            run_id=run_id,
            name=run_id,
            file_paths=paths,
            field_mapping=FieldMapping(comment_text="content"),
            use_mock=True,
            analysis_limit=0,
        ),
        records,
    )
    run_analysis_batch(run_id, use_mock=True)
    build_summary(run_id)
    _save_reviewed_themes(
        run_id, ThemesDocument(created_at="2026-07-22T00:00:00Z")
    )
    auto_export_artifacts(run_id)

    report_a = (first.parent / "视频A_评论分析_洞察报告.md").read_text(encoding="utf-8")
    report_b = (second.parent / "视频B_评论分析_洞察报告.md").read_text(encoding="utf-8")
    assert report_a != report_b
    assert "多视频导出 · 视频A" in report_a
    assert "多视频导出 · 视频B" in report_b
    assert "| 评论总数 | 1 |" in report_a
    assert "| 评论总数 | 1 |" in report_b

    csv_a = (first.parent / "视频A_评论分析_分析结果.csv").read_text(encoding="utf-8-sig")
    csv_b = (second.parent / "视频B_评论分析_分析结果.csv").read_text(encoding="utf-8-sig")
    assert "动作A练完疼" in csv_a and "动作B练完舒服" not in csv_a
    assert "动作B练完舒服" in csv_b and "动作A练完疼" not in csv_b

    alias_b = second.parent / ".insight" / run_id
    assert alias_b.is_dir() and not alias_b.is_symlink()
    spine_results = (alias_b / "results.jsonl").read_text(encoding="utf-8")
    assert "动作B练完舒服" in spine_results
    assert "动作A练完疼" not in spine_results

    alias_a = first.parent / ".insight" / run_id
    assert alias_a.is_dir() and not alias_a.is_symlink()
    chris_results = (alias_a / "results.jsonl").read_text(encoding="utf-8")
    assert "动作A练完疼" in chris_results
    assert "动作B练完舒服" not in chris_results

    canonical = data_dir / ".insight_runs" / run_id
    assert canonical.is_dir()
