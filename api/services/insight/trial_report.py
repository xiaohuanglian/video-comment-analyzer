# -*- coding: utf-8 -*-
"""Trial run reporting and cost extrapolation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .llm_analyzer import estimate_cost
from .schemas import RunConfig
from .storage import load_config, load_progress, load_results, load_source_records, load_trial_sample

LOW_CONFIDENCE_THRESHOLD = 0.72
THEME_MERGE_TOKENS_PER_SIGNAL = 120
SAFETY_MARGIN = 1.2


def _results_for_ids(run_id: str, record_ids: Set[str]) -> List[Dict[str, Any]]:
    return [row for row in load_results(run_id) if row.get("record_id") in record_ids]


def build_trial_report(run_id: str) -> Dict[str, Any]:
    config = load_config(run_id)
    progress = load_progress(run_id)
    trial = load_trial_sample(run_id)
    if not trial or not trial.get("record_ids"):
        raise ValueError("尚未生成试跑样本，请先选择试跑数量并开始试跑")

    sample_ids = set(trial["record_ids"])
    sample_count = len(sample_ids)
    total_records = progress.total_records
    rows = _results_for_ids(run_id, sample_ids)
    analyzed_count = len(rows)

    prompt_tokens = 0
    completion_tokens = 0
    for row in rows:
        usage = row.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
    actual_cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
    )

    avg_prompt = prompt_tokens / analyzed_count if analyzed_count else 0
    avg_completion = completion_tokens / analyzed_count if analyzed_count else 0
    avg_cost = actual_cost / analyzed_count if analyzed_count else 0

    low_confidence = 0
    with_new_signals = 0
    for row in rows:
        analysis = row.get("analysis") or {}
        if float(analysis.get("confidence") or 0) < LOW_CONFIDENCE_THRESHOLD:
            low_confidence += 1
        if analysis.get("new_signals"):
            with_new_signals += 1

    failed_in_sample = max(0, sample_count - analyzed_count)

    est_full_prompt = int(avg_prompt * total_records) if analyzed_count else 0
    est_full_completion = int(avg_completion * total_records) if analyzed_count else 0
    est_full_cost = estimate_cost(
        est_full_prompt,
        est_full_completion,
        input_price=config.input_price,
        output_price=config.output_price,
    )

    unique_new_signal_count = _estimate_unique_new_signals(rows)
    est_theme_prompt = int(unique_new_signal_count * THEME_MERGE_TOKENS_PER_SIGNAL * 1.5)
    est_theme_completion = int(unique_new_signal_count * 40)
    est_theme_cost = estimate_cost(
        est_theme_prompt,
        est_theme_completion,
        input_price=config.input_price,
        output_price=config.output_price,
    )

    subtotal = est_full_cost + est_theme_cost
    with_margin = round(subtotal * SAFETY_MARGIN, 6)

    budget_limit = config.budget_limit
    within_budget = budget_limit <= 0 or with_margin <= budget_limit

    return {
        "run_id": run_id,
        "prompt_version": config.prompt_version,
        "model_name": config.model_name,
        "sample_size": sample_count,
        "sample_analyzed": analyzed_count,
        "sample_failed": failed_in_sample,
        "total_records": total_records,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "actual_cost": actual_cost,
        "avg_prompt_tokens": round(avg_prompt, 2),
        "avg_completion_tokens": round(avg_completion, 2),
        "avg_cost_per_record": round(avg_cost, 6),
        "low_confidence_count": low_confidence,
        "low_confidence_ratio": round(low_confidence / analyzed_count, 4) if analyzed_count else 0,
        "new_signals_count": with_new_signals,
        "new_signals_ratio": round(with_new_signals / analyzed_count, 4) if analyzed_count else 0,
        "estimated_full_prompt_tokens": est_full_prompt,
        "estimated_full_completion_tokens": est_full_completion,
        "estimated_full_cost": est_full_cost,
        "estimated_theme_merge_cost": est_theme_cost,
        "estimated_total_with_margin": with_margin,
        "safety_margin": SAFETY_MARGIN,
        "currency": config.currency,
        "budget_limit": budget_limit,
        "within_budget": within_budget,
        "trial_completed": analyzed_count >= sample_count and failed_in_sample == 0,
        "seed": trial.get("seed"),
    }


def _estimate_unique_new_signals(rows: List[Dict[str, Any]]) -> int:
    seen: set[str] = set()
    for row in rows:
        analysis = row.get("analysis") or {}
        for signal in analysis.get("new_signals") or []:
            text = str(signal.get("text") or "").strip().lower()
            if text:
                seen.add(text)
    return max(len(seen), 1)
