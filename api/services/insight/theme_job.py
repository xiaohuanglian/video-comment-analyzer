# -*- coding: utf-8 -*-
"""Background open-theme clustering with per-video progress."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .semantic_validator import SemanticReviewDocument, review_open_themes
from .storage import (
    _run_dir,
    _write_json,
    load_config,
    load_results,
    load_semantic_review,
    load_source_records,
    save_semantic_review,
    save_open_theme_artifacts,
    save_themes,
)
from .theme_clustering import BATCH_SIZE, collect_raw_signals, merge_theme_documents, run_theme_clustering
from .theme_schemas import PROMPT_VERSION, ThemesDocument

# Round1 batch timing prior (LLM latency varies; refined after first completed batches).
DEFAULT_SECONDS_PER_BATCH = 8.0
# Round2 merge + semantic review overhead per video.
DEFAULT_SECONDS_PER_VIDEO_OVERHEAD = 45.0
THEME_CHECKPOINT_FILE = "theme_checkpoint.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def theme_job_id(run_id: str) -> str:
    return f"{run_id}::themes"


def load_theme_progress(run_id: str) -> Dict[str, Any]:
    path = _run_dir(run_id) / "theme_progress.json"
    if not path.exists():
        return {"status": "idle", "current": 0, "total": 0}
    try:
        from .storage import _read_json

        data = _read_json(path)
        return data if isinstance(data, dict) else {"status": "idle"}
    except Exception:
        return {"status": "idle", "current": 0, "total": 0}


def save_theme_progress(run_id: str, payload: Dict[str, Any]) -> None:
    payload = {**payload, "updated_at": _utc_now()}
    _write_json(_run_dir(run_id) / "theme_progress.json", payload)


def _load_theme_checkpoint(run_id: str, fingerprint: Dict[str, str]) -> Dict[str, Any]:
    from .storage import _read_json

    path = _run_dir(run_id) / THEME_CHECKPOINT_FILE
    try:
        payload = _read_json(path)
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("fingerprint") != fingerprint:
        return {}
    return payload


def _save_theme_checkpoint(
    run_id: str,
    *,
    fingerprint: Dict[str, str],
    docs: Dict[str, ThemesDocument],
    reviews: Dict[str, SemanticReviewDocument],
    per_source_ids: Dict[str, List[str]],
) -> None:
    _write_json(
        _run_dir(run_id) / THEME_CHECKPOINT_FILE,
        {
            "fingerprint": fingerprint,
            "docs": {key: doc.model_dump(mode="json") for key, doc in docs.items()},
            "reviews": {key: review.model_dump(mode="json") for key, review in reviews.items()},
            "per_source_ids": per_source_ids,
        },
    )


def reconcile_theme_progress(run_id: str) -> Dict[str, Any]:
    """If progress says running but worker is gone, persist interrupted/failed."""
    from .task_runner import is_running as job_is_running
    from .task_runner import reconcile_thread_state

    job_id = theme_job_id(run_id)
    reconcile_thread_state(job_id)
    progress = load_theme_progress(run_id)
    if progress.get("status") == "running" and not job_is_running(job_id):
        message = (
            progress.get("last_error")
            or "开放主题归并已中断（服务重启或进程退出）。请重新点击「生成开放主题」。"
        )
        progress = {
            **progress,
            "status": "failed",
            "phase": "interrupted",
            "eta_seconds": None,
            "message": message,
            "last_error": str(message)[:400],
        }
        save_theme_progress(run_id, progress)
    return progress


def mark_theme_cluster_starting(run_id: str) -> Dict[str, Any]:
    """Clear stale failed/cancelled messages before the worker rewrites progress."""
    previous = load_theme_progress(run_id)
    progress = {
        "status": "running",
        "phase": "starting",
        "current": 0,
        "total": int(previous.get("total") or 0),
        "current_source_label": None,
        "started_at": _utc_now(),
        "eta_seconds": None,
        "progress_pct": 0,
        "batch_current": 0,
        "batch_total": 0,
        "message": "正在启动开放主题归并…",
        "last_error": "",
    }
    save_theme_progress(run_id, progress)
    return progress


def _source_label(source_file: str) -> str:
    return Path(source_file).parent.name or source_file


def _round1_batches(signal_count: int) -> int:
    if signal_count <= 0:
        return 0
    return max(1, (signal_count + BATCH_SIZE - 1) // BATCH_SIZE)


def _plan_signal_batches(
    run_id: str, source_files: List[str]
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Return (signal_count_by_source, round1_batch_count_by_source)."""
    results = load_results(run_id)
    by_source: Dict[str, List[Dict[str, Any]]] = {sf: [] for sf in source_files}
    for row in results:
        sf = str((row.get("source") or {}).get("source_file") or "")
        if sf in by_source:
            by_source[sf].append(row)
    signal_counts: Dict[str, int] = {}
    batch_counts: Dict[str, int] = {}
    for sf in source_files:
        n = len(collect_raw_signals(by_source[sf]))
        signal_counts[sf] = n
        batch_counts[sf] = _round1_batches(n)
    return signal_counts, batch_counts


def _avg_or_default(samples: List[float], default: float) -> float:
    if not samples:
        return default
    return sum(samples) / len(samples)


def _eta_seconds(
    *,
    remaining_batches: float,
    remaining_videos: int,
    batch_samples: List[float],
    video_overhead_samples: List[float],
) -> Optional[int]:
    remaining_batches = max(0.0, float(remaining_batches))
    remaining_videos = max(0, int(remaining_videos))
    if remaining_batches <= 0 and remaining_videos <= 0:
        return 0
    batch_avg = _avg_or_default(batch_samples, DEFAULT_SECONDS_PER_BATCH)
    overhead_avg = _avg_or_default(video_overhead_samples, DEFAULT_SECONDS_PER_VIDEO_OVERHEAD)
    total = batch_avg * remaining_batches + overhead_avg * remaining_videos
    return max(1, int(round(total)))


def _progress_pct(
    *,
    source_files: List[str],
    completed_sources: int,
    batch_counts: Dict[str, int],
    current_batch_index: int,
    current_batch_total: int,
) -> float:
    total_batches = sum(batch_counts.values()) or len(source_files)
    done = sum(batch_counts[sf] for sf in source_files[:completed_sources])
    if current_batch_total > 0:
        done += min(current_batch_index, current_batch_total)
    elif completed_sources < len(source_files):
        # Review / round2 phase for current video: count its batches as done.
        current_sf = source_files[completed_sources]
        done += batch_counts.get(current_sf, 0)
    return min(99.0, max(0.0, 100.0 * done / max(1, total_batches)))


def _execute_hybrid_theme_cluster(
    run_id: str,
    *,
    config,
    records,
    api_key: str,
    use_mock: bool,
) -> Dict[str, Any]:
    """Hybrid pipeline adapter that preserves the legacy ThemesDocument contract."""
    from .theme_pipeline import run_hybrid_theme_pipeline

    pipeline_dir = _run_dir(run_id) / "theme_pipeline"
    source_total = len({record.source_file for record in records if record.source_file})
    save_theme_progress(
        run_id,
        {
            "status": "running",
            "phase": "embedding",
            "progress_scope": "stages",
            "source_total": source_total,
            "source_completed": 0,
            "current": 0,
            "total": 7,
            "progress_pct": 10,
            "message": "正在准备信号并生成本地语义向量…",
            "last_error": "",
        },
    )
    doc = run_hybrid_theme_pipeline(
        run_id, config=config, pipeline_dir=pipeline_dir, use_mock=use_mock
    )
    save_theme_progress(
        run_id,
        {
            "status": "running",
            "phase": "quality_validation",
            "progress_scope": "stages",
            "source_total": source_total,
            "source_completed": source_total,
            "current": 6,
            "total": 7,
            "progress_pct": 90,
            "message": "正在校验主题结构与证据链…",
            "last_error": "",
        },
    )
    # Hybrid labels are deterministic fallbacks until short LLM labeling is
    # enabled; structural review still keeps the downstream semantic contract.
    reviewed_doc, review = review_open_themes(
        doc, records, config=config, api_key=api_key, use_mock=use_mock
    )
    per_source_ids = reviewed_doc.cluster_metadata.get("per_source_theme_ids") or {}
    semantic_payload = load_semantic_review(run_id)
    semantic_payload["open_themes"] = review.model_dump(mode="json")
    semantic_payload["per_source_open_theme_ids"] = per_source_ids
    semantic_payload["per_source_open_themes"] = {
        source_file: review.model_dump(mode="json") for source_file in per_source_ids
    }
    save_open_theme_artifacts(run_id, reviewed_doc, semantic_payload)
    try:
        from .analyzer import build_summary
        from .export import auto_export_artifacts

        build_summary(run_id)
        auto_export_artifacts(run_id)
    except Exception:
        pass
    save_theme_progress(
        run_id,
        {
            "status": "completed_with_warnings" if reviewed_doc.warnings else "completed",
            "phase": "done",
            "progress_scope": "stages",
            "source_total": source_total,
            "source_completed": source_total,
            "current": 7,
            "total": 7,
            "progress_pct": 100,
            "eta_seconds": 0,
            "message": f"完成：共 {len(reviewed_doc.themes)} 个开放主题",
            "last_error": "",
            "theme_count": len(reviewed_doc.themes),
            "per_source_theme_counts": {
                key: len(value) for key, value in per_source_ids.items()
            },
            "warnings": reviewed_doc.warnings,
        },
    )
    return {**reviewed_doc.model_dump(mode="json"), "status": "completed"}


def execute_theme_cluster(
    run_id: str,
    *,
    api_key: str = "",
    use_mock: bool = False,
    cancel_event=None,
) -> Dict[str, Any]:
    """Cluster open themes per video and persist progress for UI polling."""
    # Wipe stale failure text before the potentially slow signal scan.
    mark_theme_cluster_starting(run_id)
    config = load_config(run_id)
    records = load_source_records(run_id)
    if config.themes_engine == "hybrid_cluster_v1":
        return _execute_hybrid_theme_cluster(
            run_id,
            config=config,
            records=records,
            api_key=api_key,
            use_mock=use_mock,
        )
    source_files = sorted({record.source_file for record in records if record.source_file})
    if not source_files:
        raise ValueError("任务中没有可归并的来源文件")

    signal_counts, batch_counts = _plan_signal_batches(run_id, source_files)
    total_signals = sum(signal_counts.values())
    total_batches = sum(batch_counts.values())
    fingerprint = {
        "model_name": config.model_name,
        "prompt_version": PROMPT_VERSION,
        "source_files": "|".join(source_files),
        "signal_total": str(total_signals),
    }
    checkpoint = _load_theme_checkpoint(run_id, fingerprint)
    docs_by_source: Dict[str, ThemesDocument] = {}
    reviews_by_source: Dict[str, SemanticReviewDocument] = {}
    for source_file, payload in (checkpoint.get("docs") or {}).items():
        try:
            docs_by_source[source_file] = ThemesDocument.model_validate(payload)
        except (TypeError, ValueError):
            continue
    for source_file, payload in (checkpoint.get("reviews") or {}).items():
        try:
            reviews_by_source[source_file] = SemanticReviewDocument.model_validate(payload)
        except (TypeError, ValueError):
            continue
    per_source_ids: Dict[str, List[str]] = {
        str(key): list(value or [])
        for key, value in (checkpoint.get("per_source_ids") or {}).items()
        if key in docs_by_source and key in reviews_by_source
    }
    started_at = _utc_now()
    total = len(source_files)
    batch_samples: List[float] = []
    video_overhead_samples: List[float] = []

    save_theme_progress(
        run_id,
        {
            "status": "running",
            "phase": "starting",
            "current": 0,
            "total": total,
            "current_source_label": None,
            "started_at": started_at,
            "eta_seconds": _eta_seconds(
                remaining_batches=total_batches,
                remaining_videos=total,
                batch_samples=batch_samples,
                video_overhead_samples=video_overhead_samples,
            ),
            "progress_pct": 0,
            "signal_total": total_signals,
            "batch_total_plan": total_batches,
            "message": (
                f"准备归并 {total} 个视频的开放主题"
                f"（约 {total_signals} 条去重信号 / {total_batches} 个模型批次）…"
            ),
            "last_error": "",
        },
    )

    scoped_docs = [docs_by_source[sf] for sf in source_files if sf in docs_by_source and sf in reviews_by_source]
    open_reviews_by_source: Dict[str, Any] = dict(reviews_by_source)

    try:
        for index, source_file in enumerate(source_files, start=1):
            if source_file in docs_by_source and source_file in reviews_by_source:
                continue
            if cancel_event is not None and cancel_event.is_set():
                save_theme_progress(
                    run_id,
                    {
                        "status": "cancelled",
                        "phase": "cancelled",
                        "current": index - 1,
                        "total": total,
                        "current_source_label": _source_label(source_file),
                        "started_at": started_at,
                        "eta_seconds": None,
                        "progress_pct": _progress_pct(
                            source_files=source_files,
                            completed_sources=index - 1,
                            batch_counts=batch_counts,
                            current_batch_index=0,
                            current_batch_total=0,
                        ),
                        "message": "用户已停止开放主题归并",
                        "last_error": "用户已停止开放主题归并",
                    },
                )
                return {"status": "cancelled", "run_id": run_id}

            label = _source_label(source_file)
            video_signals = signal_counts.get(source_file, 0)
            video_batches = batch_counts.get(source_file, 0)
            remaining_batches_after = sum(
                batch_counts[sf] for sf in source_files[index:]
            )
            remaining_videos_including = total - index + 1
            last_batch_started_at: Optional[datetime] = None
            last_reported_batch = 0

            def _write_running(
                *,
                phase: str,
                message: str,
                batch_index: int = 0,
                batch_total: int = 0,
                remaining_batches: float,
                remaining_videos: int,
            ) -> None:
                save_theme_progress(
                    run_id,
                    {
                        "status": "running",
                        "phase": phase,
                        "current": index,
                        "total": total,
                        "current_source_label": label,
                        "started_at": started_at,
                        "batch_current": batch_index,
                        "batch_total": batch_total,
                        "signal_count": video_signals,
                        "signal_total": total_signals,
                        "eta_seconds": _eta_seconds(
                            remaining_batches=remaining_batches,
                            remaining_videos=remaining_videos,
                            batch_samples=batch_samples,
                            video_overhead_samples=video_overhead_samples,
                        ),
                        "progress_pct": round(
                            _progress_pct(
                                source_files=source_files,
                                completed_sources=index - 1,
                                batch_counts=batch_counts,
                                current_batch_index=batch_index if phase == "clustering" else video_batches,
                                current_batch_total=batch_total if phase == "clustering" else video_batches,
                            ),
                            1,
                        ),
                        "message": message,
                        "last_error": "",
                    },
                )

            _write_running(
                phase="clustering",
                message=(
                    f"正在归并第 {index}/{total} 个视频"
                    + (f"（0/{video_batches} 批，{video_signals} 条信号）" if video_batches else "")
                    + f"：{label}"
                ),
                batch_index=0,
                batch_total=video_batches,
                remaining_batches=video_batches + remaining_batches_after,
                remaining_videos=remaining_videos_including,
            )

            def on_cluster_progress(info: Dict[str, Any]) -> None:
                nonlocal last_batch_started_at, last_reported_batch
                phase = str(info.get("phase") or "clustering")
                if phase == "round2":
                    _write_running(
                        phase="round2",
                        message=f"正在合并第 {index}/{total} 个视频主题：{label}",
                        batch_index=video_batches,
                        batch_total=video_batches,
                        remaining_batches=remaining_batches_after,
                        remaining_videos=remaining_videos_including,
                    )
                    return

                batch_index = int(info.get("batch_index") or 0)
                batch_total = int(info.get("batch_total") or video_batches)
                last_reported_batch = max(last_reported_batch, batch_index)
                if info.get("batch_started"):
                    last_batch_started_at = datetime.now(timezone.utc)
                    remaining = max(0, batch_total - batch_index + 1) + remaining_batches_after
                    _write_running(
                        phase="clustering",
                        message=(
                            f"正在归并第 {index}/{total} 个视频"
                            f"（批次 {batch_index}/{batch_total}）：{label}"
                        ),
                        batch_index=max(0, last_reported_batch - 1),
                        batch_total=batch_total,
                        remaining_batches=remaining,
                        remaining_videos=remaining_videos_including,
                    )
                    return
                if info.get("batch_completed") and last_batch_started_at is not None:
                    elapsed = (
                        datetime.now(timezone.utc) - last_batch_started_at
                    ).total_seconds()
                    if elapsed > 0.2:
                        batch_samples.append(elapsed)
                    last_batch_started_at = None
                remaining = max(0, batch_total - batch_index) + remaining_batches_after
                _write_running(
                    phase="clustering",
                    message=(
                        f"正在归并第 {index}/{total} 个视频"
                        f"（批次 {batch_index}/{batch_total}）：{label}"
                    ),
                    batch_index=last_reported_batch,
                    batch_total=batch_total,
                    remaining_batches=remaining,
                    remaining_videos=remaining_videos_including,
                )

            step_started = datetime.now(timezone.utc)
            scoped_doc = run_theme_clustering(
                run_id,
                api_key=api_key,
                use_mock=use_mock,
                persist=False,
                source_files={source_file},
                on_progress=None if use_mock else on_cluster_progress,
                cancel_event=cancel_event,
            )
            scoped_records = [
                record for record in records if record.source_file == source_file
            ]
            _write_running(
                phase="review",
                message=f"正在审查第 {index}/{total} 个视频主题：{label}",
                batch_index=video_batches,
                batch_total=video_batches,
                remaining_batches=remaining_batches_after,
                remaining_videos=remaining_videos_including,
            )
            scoped_doc, scoped_review = review_open_themes(
                scoped_doc,
                scoped_records,
                config=config,
                api_key=api_key,
                use_mock=use_mock,
            )
            scoped_review.source_file = source_file
            scoped_docs.append(scoped_doc)
            docs_by_source[source_file] = scoped_doc
            open_reviews_by_source[source_file] = scoped_review
            per_source_ids[source_file] = [theme.theme_id for theme in scoped_doc.themes]
            _save_theme_checkpoint(
                run_id,
                fingerprint=fingerprint,
                docs=docs_by_source,
                reviews=open_reviews_by_source,
                per_source_ids=per_source_ids,
            )
            video_elapsed = max(
                1.0, (datetime.now(timezone.utc) - step_started).total_seconds()
            )
            # Approximate non-batch overhead for this video (review + round2).
            batch_time = _avg_or_default(batch_samples, DEFAULT_SECONDS_PER_BATCH) * video_batches
            overhead = max(5.0, video_elapsed - batch_time) if video_batches else video_elapsed
            video_overhead_samples.append(overhead)

        open_reviews = [open_reviews_by_source[source_file] for source_file in source_files]
        doc = merge_theme_documents(
            scoped_docs,
            model_name=config.model_name,
            currency=config.currency,
        )
        open_review = SemanticReviewDocument(
            passed=all(item.passed for item in open_reviews),
            claims=[claim for item in open_reviews for claim in item.claims],
            reviews=[review for item in open_reviews for review in item.reviews],
            removed_claim_ids=[
                claim_id for item in open_reviews for claim_id in item.removed_claim_ids
            ],
            downgraded_claim_ids=[
                claim_id for item in open_reviews for claim_id in item.downgraded_claim_ids
            ],
            prompt_tokens=sum(item.prompt_tokens for item in open_reviews),
            completion_tokens=sum(item.completion_tokens for item in open_reviews),
            prompt_cache_hit_tokens=sum(
                item.prompt_cache_hit_tokens for item in open_reviews
            ),
            cost=sum(item.cost for item in open_reviews),
            error="; ".join(item.error for item in open_reviews if item.error)[:300],
        )
        semantic_payload = load_semantic_review(run_id)
        semantic_payload["open_themes"] = open_review.model_dump(mode="json")
        semantic_payload["per_source_open_theme_ids"] = per_source_ids
        semantic_payload["per_source_open_themes"] = {
            source_file: open_reviews_by_source[source_file].model_dump(mode="json")
            for source_file in source_files
        }
        save_open_theme_artifacts(run_id, doc, semantic_payload)
        try:
            from .analyzer import build_summary

            build_summary(run_id)
        except Exception:
            pass
        result = {
            **doc.model_dump(),
            "status": "completed",
            "semantic_removed_count": len(open_review.removed_claim_ids),
            "research_semantic_removed_count": len(
                ((semantic_payload.get("global") or {}).get("removed_claim_ids") or [])
            ),
            "per_source_theme_counts": {
                source_file: len(theme_ids)
                for source_file, theme_ids in per_source_ids.items()
            },
        }
        save_theme_progress(
            run_id,
            {
                "status": "completed",
                "phase": "done",
                "current": total,
                "total": total,
                "current_source_label": None,
                "started_at": started_at,
                "eta_seconds": 0,
                "progress_pct": 100,
                "message": f"完成：共 {len(doc.themes)} 个开放主题",
                "last_error": "",
                "theme_count": len(doc.themes),
                "per_source_theme_counts": result["per_source_theme_counts"],
                "cost": doc.cost,
                "currency": doc.currency,
            },
        )
        # Markdown is a final artifact. Publish it only after the persisted
        # progress state is terminal, so the UI never shows 6/7 while all
        # reports already contain a supposedly final clustering result.
        try:
            from .export import auto_export_artifacts

            auto_export_artifacts(run_id)
        except Exception:
            pass
        return result
    except InterruptedError:
        last_progress = load_theme_progress(run_id)
        save_theme_progress(
            run_id,
            {
                **last_progress,
                "status": "cancelled",
                "phase": "cancelled",
                "eta_seconds": None,
                "message": "用户已停止开放主题归并",
                "last_error": "用户已停止开放主题归并",
            },
        )
        return {"status": "cancelled", "run_id": run_id}
    except Exception as exc:
        # Keep the last live, batch-level position instead of regressing to the
        # number of fully completed videos.  A failure may happen partway through
        # a later video's Round1 batches, where that distinction is material.
        last_progress = load_theme_progress(run_id)
        save_theme_progress(
            run_id,
            {
                "status": "failed",
                "phase": "failed",
                "current": int(last_progress.get("current") or len(scoped_docs)),
                "total": total,
                "current_source_label": last_progress.get("current_source_label"),
                "started_at": started_at,
                "eta_seconds": None,
                "progress_pct": last_progress.get("progress_pct"),
                "batch_current": last_progress.get("batch_current"),
                "batch_total": last_progress.get("batch_total"),
                "signal_count": last_progress.get("signal_count"),
                "signal_total": total_signals,
                "message": f"归并失败：{exc}",
                "last_error": str(exc)[:400],
            },
        )
        raise
