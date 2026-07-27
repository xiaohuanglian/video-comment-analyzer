# -*- coding: utf-8 -*-
"""Per-video open theme clustering tests."""

from __future__ import annotations

from api.services.insight.ingestion import ingest_files
from api.services.insight.run_partitions import partition_run_storage
from api.services.insight.schemas import FieldMapping, RunConfig
from api.services.insight.storage import (
    append_result,
    create_run,
    load_semantic_review,
    load_source_records,
    save_semantic_review,
    save_themes,
)
from api.services.insight.theme_clustering import merge_theme_documents, run_theme_clustering
from api.services.insight.theme_schemas import ThemesDocument
from api.services.insight.schemas import CommentAnalysisResult


def _patch_data_dir(monkeypatch, data_dir):
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.paths.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.run_partitions._data_dir", lambda: data_dir)
    monkeypatch.setattr("api.services.insight.run_locations._data_dir", lambda: data_dir)
    monkeypatch.setattr("api.services.insight.storage.RUNS_ROOT", data_dir / "analysis_runs")


def _append_signal(run_id: str, record, text: str) -> None:
    analysis = CommentAnalysisResult(
        record_id=record.internal_record_id,
        primary_intent="difficulty_help_request",
        new_signals=[
            {
                "type": "new_problem",
                "text": text,
                "evidence_quote": record.comment_text[:40],
            }
        ],
    )
    append_result(run_id, record, analysis)


def test_multi_video_theme_clustering_is_independent(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    first = data_dir / "运康类" / "A" / "视频A" / "comments.csv"
    second = data_dir / "运康类" / "B" / "视频B" / "comments.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        "comment_id,content,user_id,nickname\n"
        "1,这个动作练完膝盖特别疼,u1,甲\n"
        "2,膝盖疼痛不敢再练了,u2,乙\n",
        encoding="utf-8",
    )
    second.write_text(
        "comment_id,content,user_id,nickname\n"
        "3,下雨天走路脚前方甩泥,u3,丙\n"
        "4,甩泥是不是步态问题,u4,丁\n",
        encoding="utf-8",
    )
    _patch_data_dir(monkeypatch, data_dir)
    paths = [
        "运康类/A/视频A/comments.csv",
        "运康类/B/视频B/comments.csv",
    ]
    records = ingest_files(paths)
    run_id = "主题分视频"
    create_run(
        RunConfig(
            run_id=run_id,
            name=run_id,
            file_paths=paths,
            field_mapping=FieldMapping(comment_text="content"),
            use_mock=True,
            storage_dir=f".insight_runs/{run_id}",
        ),
        records,
    )
    stored = load_source_records(run_id)
    by_file = {}
    for record in stored:
        by_file.setdefault(record.source_file, []).append(record)
    _append_signal(run_id, by_file[paths[0]][0], "膝盖疼痛")
    _append_signal(run_id, by_file[paths[0]][1], "膝盖不敢练")
    _append_signal(run_id, by_file[paths[1]][0], "脚前方甩泥")
    _append_signal(run_id, by_file[paths[1]][1], "步态甩泥")

    doc_a = run_theme_clustering(run_id, use_mock=True, persist=False, source_files={paths[0]})
    doc_b = run_theme_clustering(run_id, use_mock=True, persist=False, source_files={paths[1]})
    ids_a = {theme.theme_id for theme in doc_a.themes}
    ids_b = {theme.theme_id for theme in doc_b.themes}
    assert ids_a
    assert ids_b
    assert ids_a.isdisjoint(ids_b)

    merged = merge_theme_documents([doc_a, doc_b], model_name="mock")
    save_themes(run_id, merged)
    semantic = load_semantic_review(run_id)
    semantic["open_themes"] = {
        "reviews": [
            {"claim_id": f"open_theme:{theme.theme_id}", "verdict": "supported"}
            for theme in merged.themes
        ]
    }
    semantic["per_source_open_theme_ids"] = {
        paths[0]: sorted(ids_a),
        paths[1]: sorted(ids_b),
    }
    save_semantic_review(run_id, semantic)
    partition_run_storage(run_id)

    part_a = data_dir / "运康类" / "A" / "视频A" / ".insight" / run_id / "themes.json"
    part_b = data_dir / "运康类" / "B" / "视频B" / ".insight" / run_id / "themes.json"
    assert part_a.exists() and part_b.exists()
    themes_a = ThemesDocument.model_validate_json(part_a.read_text(encoding="utf-8"))
    themes_b = ThemesDocument.model_validate_json(part_b.read_text(encoding="utf-8"))
    assert {t.theme_id for t in themes_a.themes} == ids_a
    assert {t.theme_id for t in themes_b.themes} == ids_b
    assert not ({t.theme_id for t in themes_a.themes} & {t.theme_id for t in themes_b.themes})
