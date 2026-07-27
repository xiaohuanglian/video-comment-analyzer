# -*- coding: utf-8 -*-
"""Incremental / per-video processing plan tests."""

from __future__ import annotations

from api.services.insight.analyzer import _plan_processing_chunks
from api.services.insight.schemas import SourceRecord


def _rec(rid: str, source_file: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file=source_file,
        source_row_number=1,
        comment_text=f"comment {rid}",
    )


def test_multi_video_splits_by_source_file():
    paths = ["a/v1/comments.csv", "a/v2/comments.csv", "b/v3/comments.csv", "b/v4/comments.csv"]
    pending = [
        _rec("1", paths[0]),
        _rec("2", paths[0]),
        _rec("3", paths[1]),
        _rec("4", paths[2]),
        _rec("5", paths[3]),
    ]
    chunks = _plan_processing_chunks(pending, paths, analysis_limit=0)
    assert len(chunks) == 4
    assert [len(chunk) for _, chunk in chunks] == [2, 1, 1, 1]
    assert [source for source, _ in chunks] == paths


def test_multi_video_large_source_splits_into_incremental_chunks():
    paths = ["a/small/comments.csv", "a/large/comments.csv"]
    pending = [_rec(str(i), paths[0]) for i in range(50)]
    pending += [_rec(f"L{i}", paths[1]) for i in range(250)]
    chunks = _plan_processing_chunks(pending, paths, analysis_limit=0)
    assert len(chunks) == 4  # 50 + 100 + 100 + 50
    assert [source for source, _ in chunks] == [paths[0], paths[1], paths[1], paths[1]]
    assert [len(chunk) for _, chunk in chunks] == [50, 100, 100, 50]


def test_reconcile_stale_progress_resets_zombie_running():
    from api.services.insight.analyzer import reconcile_stale_progress
    from api.services.insight.schemas import RunProgress

    progress = RunProgress(
        status="cancelling",
        total_records=100,
        completed=0,
        cancel_requested=True,
        extracting_count=12,
        current_source_label="demo",
    )
    fixed = reconcile_stale_progress(progress, worker_alive=False)
    assert fixed.status == "cancelled"
    assert fixed.cancel_requested is False
    assert fixed.extracting_count == 0
    assert fixed.current_source_label is None
