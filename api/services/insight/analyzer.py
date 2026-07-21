# -*- coding: utf-8 -*-
"""Orchestrate mock/real analysis batches with resume support."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from .evidence_adapter import outreach_analysis_from_card
from .evidence_schemas import ANALYSIS_VERSION_EVIDENCE
from .evidence_extractor import run_evidence_extraction
from .evidence_writer import EvidenceWriterQueue
from .llm_analyzer import analyze_record_llm, build_openai_client, estimate_cost
from .pricing import resolve_pricing
from .mock_analyzer import analyze_record_mock
from .run_locations import run_dir_for_id
from .sampling import DEFAULT_SAMPLE_SEED, stratified_sample
from .schemas import CommentAnalysisResult, RunProgress, TrainingEvidence, TrainingImpact, ProductFit, PrimaryIntent
from .storage import (
    append_result,
    completed_evidence_record_ids,
    completed_record_ids,
    ensure_run_config,
    load_config,
    load_progress,
    load_source_records,
    remove_results_for_records,
    save_config,
    save_progress,
    save_research_report,
)
from .validation import validate_analysis


def _budget_exceeded(progress: RunProgress, config) -> bool:
    if config.budget_limit <= 0:
        return False
    return progress.estimated_cost >= config.budget_limit


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
    return CommentAnalysisResult.model_validate(
        {
            "record_id": projected.get("record_id") or card.record_id,
            "primary_intent": projected.get("primary_intent") or PrimaryIntent.OTHER_VALID,
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
            "new_signals": [],
        }
    )


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
        remove_results_for_records(run_id, set(record_ids))

    done = completed_evidence_record_ids(run_id) | completed_record_ids(run_id)
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
        progress.status = "completed" if progress.completed >= progress.total_records else "paused"
        _persist_progress(run_id, progress)
        return {
            "run_id": run_id,
            "processed": 0,
            "failed": 0,
            "completed": progress.completed,
            "total_records": progress.total_records,
            "status": progress.status,
            "analysis_version": ANALYSIS_VERSION_EVIDENCE,
        }

    result = run_evidence_extraction(
        pending,
        use_mock=mock_mode,
        config=config,
        api_key=api_key or "",
        batch_size=int(getattr(config, "batch_size", 20) or 20),
        concurrency=int(getattr(config, "concurrency", 8) or 8),
    )

    writer = EvidenceWriterQueue(run_id)
    writer.start()
    processed = 0
    failed = 0
    record_by_id = {r.internal_record_id: r for r in pending}
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
    finally:
        writer.close()

    for rid, err in (result.stats.failed_errors or {}).items():
        failed += 1
        if rid not in progress.failed_record_ids:
            progress.failed_record_ids.append(rid)
        progress.failed_errors[rid] = err

    progress.prompt_tokens += result.stats.prompt_tokens
    progress.completion_tokens += result.stats.completion_tokens
    progress.prompt_cache_hit_tokens += result.stats.cache_hit_tokens
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
    progress.completed = len(completed_record_ids(run_id))
    progress.failed = len(progress.failed_record_ids)

    if progress.status != "cancelled":
        if progress.completed >= progress.total_records:
            progress.status = "completed"
            progress.last_error = ""
            # Optional dataset research when fully done
            try:
                _maybe_finish_evidence_research(run_id, config, api_key or "", mock_mode)
            except Exception as exc:  # noqa: BLE001
                progress.last_error = f"研究阶段失败: {exc}"[:300]
        elif processed > 0:
            progress.status = "paused"
        elif failed > 0:
            progress.status = "failed"

    _persist_progress(run_id, progress)
    perf = dict(result.stats.performance or {})
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


def _maybe_finish_evidence_research(run_id: str, config, api_key: str, use_mock: bool) -> None:
    from .conclusion_review import run_conclusion_review
    from .readable_report import build_readable_report
    from .research_agent import run_research_analysis
    from .storage import (
        load_evidence_cards,
        load_source_records,
        save_conclusion_review,
        save_research_analysis,
    )

    records = load_source_records(run_id)
    card_rows = load_evidence_cards(run_id)
    if not card_rows:
        return
    started = time.perf_counter()
    research, _usage = run_research_analysis(
        records, card_rows, use_mock=use_mock, config=config, api_key=api_key
    )
    research_elapsed = time.perf_counter() - started
    save_research_analysis(run_id, research.model_dump())
    review, _ = run_conclusion_review(
        research,
        records,
        card_rows=card_rows,
        use_mock=use_mock,
        config=config,
        api_key=api_key,
        use_llm_review=bool(getattr(config, "use_llm_review", False)),
    )
    save_conclusion_review(run_id, review.model_dump())
    md = build_readable_report(
        research=research.model_dump(),
        records=records,
        card_rows=card_rows,
        run_id=run_id,
        performance={"research_elapsed_seconds": round(research_elapsed, 3)},
    )
    save_research_report(run_id, md)

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
    config = ensure_run_config(load_config(run_id))
    if getattr(config, "analysis_version", "") == ANALYSIS_VERSION_EVIDENCE:
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
    save_config(run_id, config)
    progress = load_progress(run_id)
    records = load_source_records(run_id)
    if force_reanalyze and record_ids:
        remove_results_for_records(run_id, set(record_ids))
        progress.completed = len(completed_record_ids(run_id))
        save_progress(run_id, progress)
    done = completed_record_ids(run_id)
    mock_mode = config.use_mock if use_mock is None else use_mock

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

    progress.status = "running"
    progress.cancel_requested = False
    # Clear stale banner; per-record failed_errors remain until those items succeed.
    progress.last_error = ""
    if not progress.started_at:
        progress.started_at = _utc_now()
    _persist_progress(run_id, progress)

    llm_client = None
    if not mock_mode:
        llm_client = build_openai_client(config.base_url, api_key or "")
    pricing = resolve_pricing(config.base_url, config.model_name)
    input_cache_price = float(pricing["input_price_cache_hit"])

    processed = 0
    failed = 0
    budget_paused = False
    cancelled = False

    for record in pending:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            progress.cancel_requested = True
            progress.status = "cancelled"
            progress.last_error = "用户已停止分析"
            break

        if _budget_exceeded(progress, config):
            budget_paused = True
            progress.status = "paused"
            progress.last_error = f"已达到预算上限 {config.budget_limit} {config.currency}"
            break

        try:
            if mock_mode:
                analysis = analyze_record_mock(record)
                usage_prompt = 0
                usage_completion = 0
            else:
                response = analyze_record_llm(record, config, api_key or "", client=llm_client)
                analysis = response.analysis
                usage_prompt = response.usage.prompt_tokens
                usage_completion = response.usage.completion_tokens
                progress.prompt_tokens += usage_prompt
                progress.completion_tokens += usage_completion
                progress.prompt_cache_hit_tokens += getattr(response.usage, "prompt_cache_hit_tokens", 0) or 0
                progress.estimated_cost = estimate_cost(
                    progress.prompt_tokens,
                    progress.completion_tokens,
                    input_price=config.input_price,
                    output_price=config.output_price,
                    prompt_cache_hit_tokens=progress.prompt_cache_hit_tokens,
                    input_price_cache_hit=input_cache_price,
                )
                progress.actual_cost = progress.estimated_cost

            validate_analysis(record, analysis)
            append_result(
                run_id,
                record,
                analysis,
                prompt_tokens=usage_prompt,
                completion_tokens=usage_completion,
            )
            processed += 1
            done.add(record.internal_record_id)
            rid = record.internal_record_id
            if rid in progress.failed_record_ids:
                progress.failed_record_ids.remove(rid)
            progress.failed_errors.pop(rid, None)
            progress.completed = len(done)
            progress.failed = len(progress.failed_record_ids)
            _persist_progress(run_id, progress)

            if _budget_exceeded(progress, config):
                budget_paused = True
                progress.status = "paused"
                progress.last_error = f"已达到预算上限 {config.budget_limit} {config.currency}"
                break
        except Exception as exc:
            failed += 1
            rid = record.internal_record_id
            err_text = str(exc)
            if rid not in progress.failed_record_ids:
                progress.failed_record_ids.append(rid)
            progress.retry_counts[rid] = progress.retry_counts.get(rid, 0) + 1
            progress.failed_errors[rid] = err_text
            progress.failed = len(progress.failed_record_ids)
            progress.last_error = err_text
            _persist_progress(run_id, progress)

    if cancelled:
        pass
    elif not budget_paused:
        if progress.completed >= progress.total_records:
            progress.status = "completed"
            progress.last_error = ""
        elif failed > 0 and processed == 0:
            progress.status = "failed"
        elif processed > 0 or progress.completed > 0:
            # Partial batch done — "paused" means resumable, not an error
            progress.status = "paused"
            if failed == 0 and not (progress.last_error or "").startswith("已达到预算"):
                progress.last_error = ""
        else:
            progress.status = "running"

    _persist_progress(run_id, progress)

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
        "budget_paused": budget_paused,
        "cancelled": cancelled,
        "use_mock": mock_mode,
        "last_error": progress.last_error,
        "eta_seconds": progress.eta_seconds,
        "started_at": progress.started_at,
        "updated_at": progress.updated_at,
    }


def build_summary(run_id: str) -> Dict[str, object]:
    from .export import auto_export_artifacts
    from .statistics import apply_candidates_to_summary, build_statistics
    from .storage import load_candidates, load_progress, load_results, save_progress, save_summary

    results = load_results(run_id)
    progress = load_progress(run_id)
    summary = build_statistics(results, total_records=progress.total_records)
    candidates_doc = load_candidates(run_id)
    if candidates_doc.candidates:
        summary = apply_candidates_to_summary(summary, candidates_doc.candidates)
        matched = sum(1 for c in candidates_doc.candidates if c.research_target_matches)
        summary["research_matched_user_count"] = matched
    save_summary(run_id, summary)

    try:
        paths = auto_export_artifacts(run_id)
        if paths:
            summary["export_paths"] = paths
            summary.pop("export_error", None)
            save_summary(run_id, summary)
    except Exception as exc:
        summary["export_error"] = str(exc)[:300]
        save_summary(run_id, summary)
        progress.last_error = f"自动导出失败: {exc}"[:300]
        save_progress(run_id, progress)
    return summary
