# -*- coding: utf-8 -*-
"""Theme cluster background progress tests."""

from __future__ import annotations

from api.services.insight.ingestion import ingest_files
from api.services.insight.schemas import CommentAnalysisResult, FieldMapping, RunConfig
from api.services.insight.storage import (
    append_result,
    create_run,
    load_source_records,
    load_themes,
)
from api.services.insight.theme_job import execute_theme_cluster, load_theme_progress


def _patch_data_dir(monkeypatch, data_dir):
    monkeypatch.setattr("api.services.insight.storage.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.ingestion.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.paths.DATA_DIR", data_dir)
    monkeypatch.setattr("api.services.insight.run_locations._data_dir", lambda: data_dir)
    monkeypatch.setattr("api.services.insight.run_partitions._data_dir", lambda: data_dir)
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


def test_execute_theme_cluster_writes_progress_and_completes(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    first = data_dir / "运康类" / "A" / "视频A" / "comments.csv"
    second = data_dir / "运康类" / "B" / "视频B" / "comments.csv"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        "comment_id,content,user_id,nickname\n1,膝盖特别疼,u1,甲\n2,不敢再练,u2,乙\n",
        encoding="utf-8",
    )
    second.write_text(
        "comment_id,content,user_id,nickname\n3,脚前方甩泥,u3,丙\n4,步态问题,u4,丁\n",
        encoding="utf-8",
    )
    _patch_data_dir(monkeypatch, data_dir)
    paths = ["运康类/A/视频A/comments.csv", "运康类/B/视频B/comments.csv"]
    records = ingest_files(paths)
    run_id = "主题进度"
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

    result = execute_theme_cluster(run_id, use_mock=True)
    assert result["status"] == "completed"
    assert result["themes"]
    progress = load_theme_progress(run_id)
    assert progress["status"] == "completed"
    assert progress["current"] == 2
    assert progress["total"] == 2
    assert progress["eta_seconds"] == 0
    assert progress.get("progress_pct") == 100
    assert load_themes(run_id).themes


def test_mark_theme_cluster_starting_clears_stale_failure(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "运康类" / "A" / "视频A" / "comments.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(
        "comment_id,content,user_id,nickname\n1,膝盖特别疼,u1,甲\n",
        encoding="utf-8",
    )
    _patch_data_dir(monkeypatch, data_dir)
    paths = ["运康类/A/视频A/comments.csv"]
    records = ingest_files(paths)
    run_id = "主题清错"
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
    from api.services.insight.theme_job import mark_theme_cluster_starting, save_theme_progress

    save_theme_progress(
        run_id,
        {
            "status": "failed",
            "phase": "failed",
            "current": 1,
            "total": 6,
            "message": "归并失败：旧错误不应残留",
            "last_error": "归并失败：旧错误不应残留",
        },
    )
    progress = mark_theme_cluster_starting(run_id)
    assert progress["status"] == "running"
    assert progress["phase"] == "starting"
    assert progress["last_error"] == ""
    assert "失败" not in progress["message"]
    assert load_theme_progress(run_id)["status"] == "running"


def test_reconcile_theme_progress_marks_dead_worker(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    csv_path = data_dir / "运康类" / "A" / "视频A" / "comments.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text(
        "comment_id,content,user_id,nickname\n1,膝盖特别疼,u1,甲\n",
        encoding="utf-8",
    )
    _patch_data_dir(monkeypatch, data_dir)
    paths = ["运康类/A/视频A/comments.csv"]
    records = ingest_files(paths)
    run_id = "主题僵尸"
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
    from api.services.insight.theme_job import reconcile_theme_progress, save_theme_progress

    save_theme_progress(
        run_id,
        {
            "status": "running",
            "phase": "clustering",
            "current": 1,
            "total": 1,
            "eta_seconds": 450,
            "message": "正在归并第 1/1 个视频",
            "last_error": "",
        },
    )
    progress = reconcile_theme_progress(run_id)
    assert progress["status"] == "failed"
    assert progress["phase"] == "interrupted"
    assert load_theme_progress(run_id)["status"] == "failed"


def test_eta_scales_with_remaining_batches():
    from api.services.insight.theme_job import _eta_seconds

    short = _eta_seconds(
        remaining_batches=10,
        remaining_videos=1,
        batch_samples=[5.0, 5.0],
        video_overhead_samples=[40.0],
    )
    long = _eta_seconds(
        remaining_batches=130,
        remaining_videos=6,
        batch_samples=[5.0, 5.0],
        video_overhead_samples=[40.0],
    )
    assert short is not None and long is not None
    assert long > short
    # 130*5 + 6*40 = 890s — not the old flat 75*5=375 style underestimate
    assert long >= 800
