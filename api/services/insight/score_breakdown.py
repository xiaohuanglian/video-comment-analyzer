# -*- coding: utf-8 -*-
"""Explain candidate score components for UI and reports."""

from __future__ import annotations

from typing import Any, Dict, List

SCORE_LABELS = {
    "training_continued": "持续进行 +2",
    "training_tried": "尝试过 +1",
    "specific_problems": "具体问题 +2",
    "video_insufficient": "单向内容可能不足 +2",
    "help_seeking": "主动求助 +1",
    "behavior_costs": "行为成本 +1",
    "impact_skipped": "因此跳过步骤 +1",
    "impact_stopped": "因此停止使用 +2",
    "impact_changed_plan": "因此调整方案 +1",
    "impact_paid_help": "因此付费求助 +2",
    "fit_high": "产品高适配 +2",
    "fit_medium": "产品中适配 +1",
}


def explain_candidate_score(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    evidence = analysis.get("actual_training_evidence") or "none"
    if evidence == "continued":
        items.append({"key": "training_continued", "label": SCORE_LABELS["training_continued"], "points": 2})
    elif evidence == "tried":
        items.append({"key": "training_tried", "label": SCORE_LABELS["training_tried"], "points": 1})

    if analysis.get("specific_problems"):
        items.append({"key": "specific_problems", "label": SCORE_LABELS["specific_problems"], "points": 2})

    relation = analysis.get("single_video_relation") or "unclear"
    if relation in {"personalized_judgment_needed", "realtime_observation_needed"}:
        items.append({"key": "video_insufficient", "label": SCORE_LABELS["video_insufficient"], "points": 2})

    if analysis.get("help_seeking"):
        items.append({"key": "help_seeking", "label": SCORE_LABELS["help_seeking"], "points": 1})

    if analysis.get("behavior_costs") or analysis.get("action_gap"):
        items.append({"key": "behavior_costs", "label": SCORE_LABELS["behavior_costs"], "points": 1})

    impact = analysis.get("training_impact") or "none"
    impact_map = {
        "skipped": ("impact_skipped", 1),
        "stopped": ("impact_stopped", 2),
        "changed_plan": ("impact_changed_plan", 1),
        "paid_help": ("impact_paid_help", 2),
    }
    if impact in impact_map:
        key, points = impact_map[impact]
        items.append({"key": key, "label": SCORE_LABELS[key], "points": points})
    elif analysis.get("paid_help"):
        items.append({"key": "impact_paid_help", "label": SCORE_LABELS["impact_paid_help"], "points": 2})

    fit = analysis.get("product_fit") or "unclear"
    if fit == "high":
        items.append({"key": "fit_high", "label": SCORE_LABELS["fit_high"], "points": 2})
    elif fit == "medium":
        items.append({"key": "fit_medium", "label": SCORE_LABELS["fit_medium"], "points": 1})

    return items
