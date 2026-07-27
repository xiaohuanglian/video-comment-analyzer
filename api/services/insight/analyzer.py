# -*- coding: utf-8 -*-
"""Orchestrate mock/real analysis batches with resume support."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .evidence_adapter import outreach_analysis_from_card, derive_new_signals_from_card
from .evidence_schemas import ANALYSIS_VERSION_EVIDENCE, ResearchAnalysis
from .evidence_extractor import BatchExtractStats, run_evidence_extraction
from .evidence_writer import EvidenceWriterQueue
from .llm_analyzer import estimate_cost
from .pricing import resolve_pricing
from .run_locations import run_dir_for_id
from .sampling import DEFAULT_SAMPLE_SEED, stratified_sample
from .schemas import CommentAnalysisResult, RunProgress, TrainingEvidence, TrainingImpact, ProductFit, PrimaryIntent, SourceRecord
from .storage import (
    append_result,
    completed_evidence_record_ids,
    completed_record_ids,
    ensure_run_config,
    load_config,
    load_progress,
    load_source_records,
    prune_stale_failures,
    remove_evidence_for_records,
    remove_results_for_records,
    save_config,
    save_progress,
    save_research_report,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_eta(progress: RunProgress) -> None:
    if progress.completed <= 0 or not progress.started_at:
        progress.eta_seconds = None
        return
    try:
        started = datetime.fromisoformat(progress.started_at)
        elapsed = max(0.1, (datetime.now(timezone.utc) - started).total_seconds())
    except ValueError:
        progress.eta_seconds = None
        return
    remaining = max(0, progress.total_records - progress.completed)
    rate = progress.completed / elapsed
    progress.eta_seconds = int(remaining / rate) if rate > 0 else None


def _persist_progress(run_id: str, progress: RunProgress) -> None:
    progress.updated_at = _utc_now()
    _update_eta(progress)
    progress.skipped = max(0, progress.total_records - progress.completed - progress.failed)
    save_progress(run_id, progress)


def _card_to_comment_analysis(card) -> CommentAnalysisResult:
    projected = outreach_analysis_from_card(card)
    new_signals = derive_new_signals_from_card(card)
    return CommentAnalysisResult.model_validate(
        {
            "record_id": projected.get("record_id") or card.record_id,
            "primary_intent": projected.get("primary_intent") or PrimaryIntent.OTHER_VALID,
            "signals": projected.get("signals") or [],
            "specific_problems": projected.get("specific_problems") or [],
            "actual_training_evidence": projected.get("actual_training_evidence") or TrainingEvidence.NONE,
            "help_seeking": bool(projected.get("help_seeking")),
            "behavior_costs": projected.get("behavior_costs") or [],
            "training_impact": projected.get("training_impact") or TrainingImpact.NONE,
            "single_video_relation": projected.get("single_video_relation") or "unclear",
            "product_fit": projected.get("product_fit") or ProductFit.UNCLEAR,
            "product_fit_reason": projected.get("product_fit_reason") or "",
            "evidence_quotes": projected.get("evidence_quotes") or [],
            "explicit_user_context": projected.get("explicit_user_context") or [],
            "confidence": projected.get("confidence") or 0.7,
            "hypothesis_relations": [],
            "new_signals": new_signals,
        }
    )


INCREMENTAL_CHUNK_SIZE = 100
PROGRESS_FLUSH_EVERY = 20


def _source_label(source_file: str) -> str:
    return Path(source_file).parent.name or source_file


def _plan_processing_chunks(
    pending: List[SourceRecord],
    file_paths: List[str],
    *,
    analysis_limit: int,
) -> List[Tuple[str, List[SourceRecord]]]:
    """Split work by video; large single videos are further split for live progress."""
    if not pending:
        return []
    paths_order = list(dict.fromkeys(file_paths))
    by_file: Dict[str, List[SourceRecord]] = defaultdict(list)
    for record in pending:
        by_file[record.source_file].append(record)

    chunks: List[Tuple[str, List[SourceRecord]]] = []
    multi_video = len(paths_order) > 1

    def append_chunks(source_file: str, records: List[SourceRecord]) -> None:
        if not records:
            return
        max_chunk = INCREMENTAL_CHUNK_SIZE
        if (not multi_video) and analysis_limit > 0:
            chunks.append((source_file, records))
            return
        if len(records) <= max_chunk:
            chunks.append((source_file, records))
            return
        for index in range(0, len(records), max_chunk):
            chunks.append((source_file, records[index : index + max_chunk]))

    for source_file in paths_order:
        append_chunks(source_file, by_file.pop(source_file, []))
    for source_file, records in by_file.items():
        append_chunks(source_file, records)
    return chunks


def _merge_extract_stats(target: BatchExtractStats, source: BatchExtractStats) -> None:
    target.processed += source.processed
    target.failed += source.failed
    target.cache_hits += source.cache_hits
    target.format_failures += source.format_failures
    target.retries += source.retries
    target.splits += source.splits
    target.prompt_tokens += source.prompt_tokens
    target.completion_tokens += source.completion_tokens
    target.cache_hit_tokens += source.cache_hit_tokens
    target.requests_count += source.requests_count
    target.batch_latencies.extend(source.batch_latencies)
    target.failed_ids.extend(source.failed_ids)
    target.failed_errors.update(source.failed_errors)
    target.extract_elapsed_seconds += source.extract_elapsed_seconds
    if source.performance:
        target.performance = source.performance


def _apply_progress_costs(progress: RunProgress, config, stats: BatchExtractStats) -> None:
    progress.prompt_tokens += stats.prompt_tokens
    progress.completion_tokens += stats.completion_tokens
    progress.prompt_cache_hit_tokens += stats.cache_hit_tokens
    pricing = resolve_pricing(config.base_url, config.model_name)
    progress.estimated_cost = estimate_cost(
        progress.prompt_tokens,
        progress.completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
        prompt_cache_hit_tokens=progress.prompt_cache_hit_tokens,
        input_price_cache_hit=float(pricing["input_price_cache_hit"]),
    )
    progress.actual_cost = progress.estimated_cost


def reconcile_stale_progress(progress: RunProgress, *, worker_alive: bool) -> RunProgress:
    """If UI says running but the worker is gone, allow the user to continue."""
    if worker_alive:
        return progress
    if progress.status not in {"running", "cancelling"}:
        return progress
    was_cancelling = progress.status == "cancelling" or progress.cancel_requested
    progress.cancel_requested = False
    progress.extracting_count = 0
    progress.current_source_label = None
    if was_cancelling:
        progress.status = "cancelled"
        if not progress.last_error:
            progress.last_error = "用户已停止分析"
    else:
        progress.status = "paused" if progress.completed > 0 else "ready"
        if not progress.last_error:
            progress.last_error = "上次分析意外中断，可点击继续分析"
    return progress


def _write_extraction_cards(
    run_id: str,
    pending_chunk: List[SourceRecord],
    result,
    progress: RunProgress,
    *,
    cancel_event: Optional[threading.Event] = None,
) -> int:
    writer = EvidenceWriterQueue(run_id)
    writer.start()
    processed = 0
    record_by_id = {record.internal_record_id: record for record in pending_chunk}
    try:
        for card in result.cards:
            if cancel_event is not None and cancel_event.is_set():
                progress.cancel_requested = True
                progress.status = "cancelled"
                progress.last_error = "用户已停止分析"
                break
            source = record_by_id.get(card.record_id)
            if source is None:
                continue
            writer.put(source, card, from_cache=bool(card.reused_from_record_id))
            analysis = _card_to_comment_analysis(card)
            append_result(run_id, source, analysis)
            processed += 1
            rid = card.record_id
            if rid in progress.failed_record_ids:
                progress.failed_record_ids.remove(rid)
            progress.failed_errors.pop(rid, None)
            if processed % PROGRESS_FLUSH_EVERY == 0:
                progress.completed = len(completed_record_ids(run_id))
                progress.failed = len(progress.failed_record_ids)
                _persist_progress(run_id, progress)
    finally:
        writer.close()
    return processed


def run_evidence_analysis_batch(
    run_id: str,
    *,
    limit: Optional[int] = None,
    record_ids: Optional[Set[str]] = None,
    retry_failed_only: bool = False,
    use_mock: Optional[bool] = None,
    api_key: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    force_reanalyze: bool = False,
) -> Dict[str, object]:
    """Evidence_items_v1 path: concurrent extract → JSONL + projected results.jsonl."""
    config = ensure_run_config(load_config(run_id))
    save_config(run_id, config)
    progress = load_progress(run_id)
    records = load_source_records(run_id)
    mock_mode = config.use_mock if use_mock is None else use_mock

    if force_reanalyze and record_ids:
        targets = set(record_ids)
        remove_results_for_records(run_id, targets)
        remove_evidence_for_records(run_id, targets)

    result_done = completed_record_ids(run_id)
    evidence_done = completed_evidence_record_ids(run_id)
    # Results are authoritative for success. Evidence-only orphans stay pending
    # so "继续分析" can backfill results (cache may avoid a full re-bill).
    done = result_done
    prune_stale_failures(progress, result_done)
    progress.completed = len(result_done)
    progress.failed = len(progress.failed_record_ids)
    pending = [record for record in records if record.internal_record_id not in done]
    if retry_failed_only:
        failed_set = set(progress.failed_record_ids)
        pending = [record for record in pending if record.internal_record_id in failed_set]
    elif record_ids is not None:
        allowed = set(record_ids)
        pending = [record for record in pending if record.internal_record_id in allowed]
    else:
        batch_limit = limit if limit is not None else config.analysis_limit
        if batch_limit and batch_limit > 0 and pending:
            batch_size = min(batch_limit, len(pending))
            if batch_size < len(pending):
                sampled_ids = set(stratified_sample(pending, batch_size, seed=DEFAULT_SAMPLE_SEED))
                pending = [record for record in pending if record.internal_record_id in sampled_ids]

    if not mock_mode and not (api_key or "").strip():
        raise ValueError("真实 API 分析需要填写 API Key（仅用于本次请求，不会写入磁盘）")

    if cancel_event is not None and cancel_event.is_set():
        progress.status = "cancelled"
        progress.last_error = "用户已停止分析"
        _persist_progress(run_id, progress)
        return {"run_id": run_id, "processed": 0, "failed": 0, "status": "cancelled", "cancelled": True}

    progress.status = "running"
    progress.cancel_requested = False
    progress.last_error = ""
    if not progress.started_at:
        progress.started_at = _utc_now()
    _persist_progress(run_id, progress)

    if not pending:
        prune_stale_failures(progress, result_done)
        progress.completed = len(result_done)
        progress.failed = len(progress.failed_record_ids)
        orphan_evidence = len(evidence_done - result_done)
        if progress.completed >= progress.total_records and progress.failed == 0:
            progress.status = "completed"
            progress.last_error = ""
            try:
                research_perf = _maybe_finish_evidence_research(
                    run_id, config, api_key or "", mock_mode
                )
                progress.prompt_tokens += int(research_perf.get("prompt_tokens") or 0)
                progress.completion_tokens += int(research_perf.get("completion_tokens") or 0)
                progress.prompt_cache_hit_tokens += int(
                    research_perf.get("prompt_cache_hit_tokens") or 0
                )
                pricing = resolve_pricing(config.base_url, config.model_name)
                progress.estimated_cost = estimate_cost(
                    progress.prompt_tokens,
                    progress.completion_tokens,
                    input_price=config.input_price,
                    output_price=config.output_price,
                    prompt_cache_hit_tokens=progress.prompt_cache_hit_tokens,
                    input_price_cache_hit=float(pricing["input_price_cache_hit"]),
                )
                progress.actual_cost = progress.estimated_cost
            except Exception as exc:  # noqa: BLE001
                progress.last_error = f"研究阶段失败: {exc}"[:300]
        elif progress.completed >= progress.total_records and progress.failed > 0:
            progress.status = "paused"
            progress.last_error = f"仍有 {progress.failed} 条失败，可点击「重试失败项」"
        else:
            progress.status = "paused"
            if orphan_evidence:
                progress.last_error = (
                    f"有 {orphan_evidence} 条证据未落盘为结果，请继续分析补齐"
                )
        _persist_progress(run_id, progress)
        return {
            "run_id": run_id,
            "processed": 0,
            "failed": 0,
            "completed": progress.completed,
            "total_records": progress.total_records,
            "status": progress.status,
            "last_error": progress.last_error,
            "analysis_version": ANALYSIS_VERSION_EVIDENCE,
        }

    work_chunks = _plan_processing_chunks(
        pending,
        config.file_paths,
        analysis_limit=int(config.analysis_limit or 0),
    )
    progress.current_chunk_total = len(work_chunks)
    combined_stats = BatchExtractStats()
    processed = 0
    failed = 0

    for chunk_index, (source_file, chunk) in enumerate(work_chunks, start=1):
        if cancel_event is not None and cancel_event.is_set():
            progress.cancel_requested = True
            progress.status = "cancelled"
            progress.last_error = "用户已停止分析"
            break

        progress.current_source_label = _source_label(source_file)
        progress.current_chunk_index = chunk_index
        progress.current_chunk_total = len(work_chunks)
        progress.extracting_count = 0
        _persist_progress(run_id, progress)

        def _cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        def _wave_heartbeat(chunk_stats: BatchExtractStats) -> None:
            progress.extracting_count = chunk_stats.processed
            _persist_progress(run_id, progress)

        result = run_evidence_extraction(
            chunk,
            use_mock=mock_mode,
            config=config,
            api_key=api_key or "",
            batch_size=int(getattr(config, "batch_size", 20) or 20),
            concurrency=int(getattr(config, "concurrency", 8) or 8),
            cancel_check=_cancelled,
            on_wave_complete=_wave_heartbeat,
        )
        progress.extracting_count = 0
        if _cancelled():
            progress.cancel_requested = True
            progress.status = "cancelled"
            progress.last_error = "用户已停止分析"

        _merge_extract_stats(combined_stats, result.stats)
        chunk_processed = _write_extraction_cards(
            run_id,
            chunk,
            result,
            progress,
            cancel_event=cancel_event,
        )
        processed += chunk_processed

        for rid, err in (result.stats.failed_errors or {}).items():
            failed += 1
            if rid not in progress.failed_record_ids:
                progress.failed_record_ids.append(rid)
            progress.failed_errors[rid] = err

        _apply_progress_costs(progress, config, result.stats)
        progress.completed = len(completed_record_ids(run_id))
        progress.failed = len(progress.failed_record_ids)
        _persist_progress(run_id, progress)

        next_source = work_chunks[chunk_index][0] if chunk_index < len(work_chunks) else None
        if next_source != source_file:
            try:
                from .run_partitions import partition_run_storage

                partition_run_storage(run_id)
            except Exception:
                pass

        if progress.status == "cancelled":
            break

    result_stats = combined_stats
    pricing = resolve_pricing(config.base_url, config.model_name)

    if progress.status != "cancelled":
        result_done_ids = completed_record_ids(run_id)
        prune_stale_failures(progress, result_done_ids)
        progress.completed = len(result_done_ids)
        progress.failed = len(progress.failed_record_ids)
        if progress.completed >= progress.total_records and progress.failed == 0:
            progress.status = "completed"
            progress.last_error = ""
            # Optional dataset research when fully done
            try:
                research_perf = _maybe_finish_evidence_research(
                    run_id, config, api_key or "", mock_mode
                )
                progress.prompt_tokens += int(research_perf.get("prompt_tokens") or 0)
                progress.completion_tokens += int(research_perf.get("completion_tokens") or 0)
                progress.prompt_cache_hit_tokens += int(
                    research_perf.get("prompt_cache_hit_tokens") or 0
                )
                progress.estimated_cost = estimate_cost(
                    progress.prompt_tokens,
                    progress.completion_tokens,
                    input_price=config.input_price,
                    output_price=config.output_price,
                    prompt_cache_hit_tokens=progress.prompt_cache_hit_tokens,
                    input_price_cache_hit=float(pricing["input_price_cache_hit"]),
                )
                progress.actual_cost = progress.estimated_cost
            except Exception as exc:  # noqa: BLE001
                progress.last_error = f"研究阶段失败: {exc}"[:300]
        elif progress.completed >= progress.total_records and progress.failed > 0:
            progress.status = "paused"
            progress.last_error = f"仍有 {progress.failed} 条失败，可点击「重试失败项」"
        elif processed > 0:
            progress.status = "paused"
        elif failed > 0:
            progress.status = "failed"

    progress.current_source_label = None
    progress.current_chunk_index = 0
    progress.current_chunk_total = 0
    progress.extracting_count = 0
    _persist_progress(run_id, progress)
    perf = dict(result_stats.performance or {})
    try:
        path = run_dir_for_id(run_id) / "extract_performance.json"
        path.write_text(json.dumps(perf, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    return {
        "run_id": run_id,
        "processed": processed,
        "failed": failed,
        "completed": progress.completed,
        "total_records": progress.total_records,
        "status": progress.status,
        "prompt_tokens": progress.prompt_tokens,
        "completion_tokens": progress.completion_tokens,
        "estimated_cost": progress.estimated_cost,
        "currency": config.currency,
        "budget_limit": config.budget_limit,
        "cancelled": progress.status == "cancelled",
        "use_mock": mock_mode,
        "last_error": progress.last_error,
        "analysis_version": ANALYSIS_VERSION_EVIDENCE,
        "extract_performance": perf,
    }


def _maybe_finish_evidence_research(
    run_id: str, config, api_key: str, use_mock: bool
) -> Dict[str, object]:
    from .readable_report import build_readable_report
    from .research_agent import run_research_analysis
    from .semantic_validator import build_manual_audit_samples, run_semantic_review
    from .storage import (
        load_evidence_cards,
        load_source_records,
        save_research_analysis,
        save_semantic_review,
    )

    records = load_source_records(run_id)
    card_rows = load_evidence_cards(run_id)
    if not card_rows:
        return {
            "research_elapsed_seconds": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0,
        }
    started = time.perf_counter()
    research, usage = run_research_analysis(
        records, card_rows, use_mock=use_mock, config=config, api_key=api_key
    )
    research_elapsed = time.perf_counter() - started
    research, semantic_review = run_semantic_review(
        research,
        records,
        card_rows,
        use_mock=use_mock,
        config=config,
        api_key=api_key,
    )
    save_research_analysis(run_id, research.model_dump())
    semantic_payload = {
        "global": semantic_review.model_dump(mode="json"),
        "per_source": {},
        "per_source_research": {},
        "manual_audit_samples": build_manual_audit_samples(records, card_rows),
    }

    source_files = sorted({record.source_file for record in records if record.source_file})
    if len(source_files) == 1:
        source_file = source_files[0]
        semantic_payload["per_source"][source_file] = semantic_review.model_dump(mode="json")
        semantic_payload["per_source_research"][source_file] = research.model_dump()
    elif source_files:
        from .export import _scoped_research_payload

        for source_file in source_files:
            scoped_payload, scoped_records, scoped_cards = _scoped_research_payload(
                run_id, {source_file}
            )
            scoped_research, scoped_review = run_semantic_review(
                ResearchAnalysis.model_validate(scoped_payload),
                scoped_records,
                scoped_cards,
                use_mock=use_mock,
                config=config,
                api_key=api_key,
                source_file=source_file,
            )
            semantic_payload["per_source"][source_file] = scoped_review.model_dump(mode="json")
            semantic_payload["per_source_research"][source_file] = scoped_research.model_dump()
            semantic_review.prompt_tokens += scoped_review.prompt_tokens
            semantic_review.completion_tokens += scoped_review.completion_tokens
            semantic_review.prompt_cache_hit_tokens += scoped_review.prompt_cache_hit_tokens
            semantic_review.cost += scoped_review.cost
    save_semantic_review(run_id, semantic_payload)
    md = build_readable_report(
        research=research.model_dump(),
        records=records,
        card_rows=card_rows,
        run_id=run_id,
        performance={"research_elapsed_seconds": round(research_elapsed, 3)},
    )
    save_research_report(run_id, md)
    performance = {
        "research_elapsed_seconds": round(research_elapsed, 3),
        "prompt_tokens": usage.prompt_tokens + semantic_review.prompt_tokens,
        "completion_tokens": usage.completion_tokens + semantic_review.completion_tokens,
        "prompt_cache_hit_tokens": (
            usage.prompt_cache_hit_tokens + semantic_review.prompt_cache_hit_tokens
        ),
        "semantic_review_cost": round(semantic_review.cost, 6),
        "semantic_removed": len(semantic_review.removed_claim_ids),
        "semantic_downgraded": len(semantic_review.downgraded_claim_ids),
    }
    try:
        (run_dir_for_id(run_id) / "research_performance.json").write_text(
            json.dumps(performance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    return performance

def run_analysis_batch(
    run_id: str,
    *,
    limit: Optional[int] = None,
    record_ids: Optional[Set[str]] = None,
    retry_failed_only: bool = False,
    use_mock: Optional[bool] = None,
    api_key: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
    force_reanalyze: bool = False,
) -> Dict[str, object]:
    return run_evidence_analysis_batch(
        run_id,
        limit=limit,
        record_ids=record_ids,
        retry_failed_only=retry_failed_only,
        use_mock=use_mock,
        api_key=api_key,
        cancel_event=cancel_event,
        force_reanalyze=force_reanalyze,
    )


def build_summary(run_id: str) -> Dict[str, object]:
    from .export import auto_export_artifacts
    from .evidence_adapter import derive_new_signals_from_card, merge_projected_analysis, outreach_analysis_from_card
    from .statistics import apply_candidates_to_summary, build_statistics
    from .storage import load_candidates, load_evidence_cards, load_progress, load_results, save_progress, save_summary

    results = load_results(run_id)
    cards_by_id = {
        str(row.get("record_id") or ""): row
        for row in load_evidence_cards(run_id)
        if row.get("record_id")
    }
    refreshed: List[Dict[str, object]] = []
    for row in results:
        rid = str(row.get("record_id") or "")
        card_row = cards_by_id.get(rid)
        if not card_row:
            refreshed.append(row)
            continue
        card = card_row.get("card") or {}
        projected = outreach_analysis_from_card(card)
        analysis = merge_projected_analysis(row.get("analysis") or {}, projected)
        analysis["new_signals"] = derive_new_signals_from_card(card)
        analysis["paid_help"] = bool(
            analysis.get("paid_help") or projected.get("paid_help")
        )
        refreshed.append({**row, "analysis": analysis, "card": card})
    results = refreshed
    progress = load_progress(run_id)
    summary = build_statistics(results, total_records=progress.total_records)
    candidates_doc = load_candidates(run_id)
    if candidates_doc.candidates:
        summary = apply_candidates_to_summary(summary, candidates_doc.candidates)
        matched = sum(1 for c in candidates_doc.candidates if c.research_target_matches)
        summary["research_matched_user_count"] = matched
    save_summary(run_id, summary)

    # Per-video Markdown is a final artifact. Do not overwrite it while the
    # analysis or open-theme pipeline is still incomplete.
    if progress.completed >= progress.total_records and progress.failed == 0:
        try:
            paths = auto_export_artifacts(run_id)
            if paths:
                summary["export_paths"] = paths
                summary.pop("export_error", None)
                save_summary(run_id, summary)
        except Exception as exc:
            # Export is best-effort: never mark the whole analysis as failed.
            summary["export_error"] = str(exc)[:300]
            save_summary(run_id, summary)

    from .run_partitions import partition_run_storage

    try:
        partition_run_storage(run_id)
    except Exception:
        pass

    return summary
