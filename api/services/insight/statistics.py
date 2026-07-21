# -*- coding: utf-8 -*-
"""Aggregate statistics for comment insight runs."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from .field_mapping import resolve_source_links
from .prompts import HYPOTHESES
from .user_identity import user_key

VALID_INTENTS = {
    "gratitude_recognition",
    "check_in",
    "result_feedback",
    "question",
    "difficulty_help_request",
    "complaint",
    "other_valid",
}

SINGLE_VIDEO_LABELS = {
    "video_sufficient": "视频本身足够",
    "one_reply_sufficient": "一次回复即可",
    "personalized_judgment_needed": "需个性化判断",
    "realtime_observation_needed": "需实时观察",
    "unclear": "信息不足",
}

HYPOTHESIS_RELATION_LABELS = {
    "supports": "支持",
    "weakens": "削弱",
    "insufficient": "证据不足",
    "irrelevant": "无关",
}


def contactability(source: Dict[str, Any]) -> str:
    homepage, comment_url = resolve_source_links(source)
    if homepage:
        return "high"
    if comment_url and (source.get("username") or source.get("user_id")):
        return "medium"
    return "low"


def compute_candidate_score(analysis: Dict[str, Any]) -> int:
    score = 0
    evidence = analysis.get("actual_training_evidence") or "none"
    if evidence == "tried":
        score += 1
    elif evidence == "continued":
        score += 2
    if analysis.get("specific_problems"):
        score += 2
    relation = analysis.get("single_video_relation") or "unclear"
    if relation in {"personalized_judgment_needed", "realtime_observation_needed"}:
        score += 2
    if analysis.get("help_seeking"):
        score += 1
    if analysis.get("behavior_costs") or analysis.get("action_gap"):
        score += 1
    impact = analysis.get("training_impact") or "none"
    impact_scores = {
        "skipped": 1,
        "stopped": 2,
        "changed_plan": 1,
        "paid_help": 2,
    }
    score += impact_scores.get(impact, 0)
    if analysis.get("paid_help") and impact != "paid_help":
        score += 2
    fit = analysis.get("product_fit") or "unclear"
    if fit == "high":
        score += 2
    elif fit == "medium":
        score += 1
    return score


def candidate_priority(score: int) -> str:
    if score >= 7:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _quote_from_row(row: Dict[str, Any], relation: Dict[str, Any]) -> str:
    """Only use verbatim hypothesis evidence — full comment fallback polluted the dashboard."""
    return (relation.get("evidence_quote") or "").strip()


def _hypothesis_quote_score(hid: str, rel: str, quote: str, analysis: Dict[str, Any]) -> float:
    """Rank representative quotes; demote clearly off-topic examples for the dashboard."""
    if not quote or len(quote.strip()) < 4:
        return -10.0
    score = float(analysis.get("confidence") or 0.0)
    score += min(len(quote), 60) / 60.0
    intent = analysis.get("primary_intent") or ""
    signals = set(analysis.get("signals") or [])
    video_rel = analysis.get("single_video_relation") or ""
    text = quote

    process_signals = {
        "form_uncertainty",
        "cannot_complete",
        "no_target_muscle_sensation",
        "physical_discomfort",
        "needs_substitution",
        "needs_regression",
        "needs_progression",
        "needs_training_plan",
        "pace_or_counting_problem",
        "instruction_unclear",
        "started_training",
        "continued_training",
        "positive_result",
        "negative_result",
    }
    motivation_signals = {"motivation_or_accountability", "stopped_training", "skipped_exercise"}

    if intent in {"invalid_or_unclear", "other_valid"} and "谢谢" not in text:
        score -= 0.5
    if intent == "gratitude_recognition":
        score -= 1.5
    if any(token in text for token in ("谢谢", "感谢", "多谢")):
        score -= 1.0

    if hid == "H1":
        if rel == "supports":
            if signals & process_signals:
                score += 2.0
            if intent in {"difficulty_help_request", "result_feedback", "check_in"}:
                score += 1.0
            if intent == "question" and not (signals & process_signals):
                score -= 1.5
        elif rel == "weakens":
            if signals & motivation_signals:
                score += 2.0
            if any(token in text for token in ("懒", "坚持不", "没动力", "不想练", "提不起")):
                score += 1.5
            if signals & process_signals and not (signals & motivation_signals):
                score -= 1.5
            if any(token in text for token in ("真的有用", "有效", "舒服多了", "放松", "改善", "谢谢")):
                score -= 3.0
    elif hid == "H2":
        if rel == "supports":
            if video_rel in {"personalized_judgment_needed", "realtime_observation_needed"}:
                score += 2.5
            if signals & {"form_uncertainty", "asks_coach_reply", "recorded_self_for_review"}:
                score += 1.5
            if intent == "question" and video_rel in {"one_reply_sufficient", "video_sufficient", "unclear"}:
                score -= 2.0
            if any(token in text for token in ("帮我看", "看看我", "哪里不对", "姿势对不对")):
                score += 2.0
        elif rel == "weakens":
            if video_rel in {"video_sufficient", "one_reply_sufficient"}:
                score += 2.0
            if any(token in text for token in ("看懂了", "跟着练", "看第二遍", "就会了")):
                score += 1.5
            if intent == "gratitude_recognition" or any(token in text for token in ("谢谢", "感谢", "真的有用", "有效")):
                score -= 3.0
    elif hid == "H3":
        if rel == "supports":
            if signals & {"needs_training_plan", "needs_progression", "needs_regression", "changed_training_plan"}:
                score += 2.0
            if any(token in text for token in ("怎么安排", "训练计划", "怎么练", "进阶", "帮我安排")):
                score += 1.5
            if intent == "question" and "安排" not in text and "计划" not in text:
                score -= 1.0
        elif rel == "weakens":
            if any(token in text for token in ("自己安排", "自己计划", "随便练")):
                score += 1.5

    return score


def build_statistics(results: List[Dict[str, Any]], *, total_records: int = 0) -> Dict[str, Any]:
    total_analyzed = len(results)
    intent_counts: Dict[str, int] = defaultdict(int)
    signal_counts: Dict[str, int] = defaultdict(int)
    hypothesis_counts: Dict[str, Dict[str, int]] = {
        hid: {"supports": 0, "weakens": 0, "insufficient": 0, "irrelevant": 0}
        for hid in ("H1", "H2", "H3")
    }
    hypothesis_users: Dict[str, Dict[str, Set[str]]] = {
        hid: {rel: set() for rel in ("supports", "weakens", "insufficient", "irrelevant")}
        for hid in ("H1", "H2", "H3")
    }
    hypothesis_by_creator: Dict[str, Dict[str, Dict[str, int]]] = {
        hid: defaultdict(lambda: defaultdict(int)) for hid in ("H1", "H2", "H3")
    }
    hypothesis_quote_candidates: Dict[str, Dict[str, List[Tuple[float, str]]]] = {
        hid: {"supports": [], "weakens": []} for hid in ("H1", "H2", "H3")
    }
    single_video_counts: Dict[str, int] = defaultdict(int)
    product_fit_counts: Dict[str, int] = defaultdict(int)

    unique_users: Set[str] = set()
    trained_users: Set[str] = set()
    source_videos: Set[str] = set()
    source_creators: Set[str] = set()
    source_files: Set[str] = set()
    contactable_homepage = 0
    high_priority_users: Set[str] = set()
    high_priority_candidate_comments = 0

    gratitude_signal = 0
    check_in_intent = 0
    result_feedback_intent = 0
    question_intent = 0
    difficulty_intent = 0
    personalized_needed = 0
    realtime_needed = 0
    product_fit_high = 0

    valid_comments = 0

    for row in results:
        source = row.get("source") or {}
        analysis = row.get("analysis") or {}
        ukey = user_key(source)
        if ukey:
            unique_users.add(ukey)

        video_key = str(source.get("video_title") or source.get("source_file") or "").strip()
        if video_key:
            source_videos.add(video_key)
        creator = str(source.get("creator_name") or "").strip()
        if creator:
            source_creators.add(creator)
        source_file = str(source.get("source_file") or "").strip()
        if source_file:
            source_files.add(source_file)

        intent = analysis.get("primary_intent") or ""
        if intent in VALID_INTENTS:
            valid_comments += 1
        intent_counts[intent] += 1

        if intent == "check_in":
            check_in_intent += 1
        elif intent == "result_feedback":
            result_feedback_intent += 1
        elif intent == "question":
            question_intent += 1
        elif intent == "difficulty_help_request":
            difficulty_intent += 1

        signals = analysis.get("signals") or []
        if "gratitude" in signals:
            gratitude_signal += 1
        for signal in signals:
            signal_counts[signal] += 1

        evidence = analysis.get("actual_training_evidence") or "none"
        if evidence in {"tried", "continued"} and ukey:
            trained_users.add(ukey)

        relation = analysis.get("single_video_relation") or "unclear"
        single_video_counts[relation] += 1
        if relation == "personalized_judgment_needed":
            personalized_needed += 1
        elif relation == "realtime_observation_needed":
            realtime_needed += 1

        fit = analysis.get("product_fit") or "unclear"
        product_fit_counts[fit] += 1
        if fit == "high":
            product_fit_high += 1

        if contactability(source) == "high":
            contactable_homepage += 1

        score = compute_candidate_score(analysis)
        if candidate_priority(score) == "high":
            high_priority_candidate_comments += 1
            if ukey:
                high_priority_users.add(ukey)

        creator_type = source.get("creator_type") or "未知"
        for hyp in analysis.get("hypothesis_relations") or []:
            hid = hyp.get("hypothesis_id")
            rel = hyp.get("relation")
            if hid not in hypothesis_counts or rel not in hypothesis_counts[hid]:
                continue
            hypothesis_counts[hid][rel] += 1
            if ukey:
                hypothesis_users[hid][rel].add(ukey)
            hypothesis_by_creator[hid][creator_type][rel] += 1
            if rel in {"supports", "weakens"}:
                quote = _quote_from_row(row, hyp)
                if quote:
                    scored = _hypothesis_quote_score(hid, rel, quote, analysis)
                    if scored >= 0:
                        hypothesis_quote_candidates[hid][rel].append((scored, quote))

    hypothesis_quotes: Dict[str, Dict[str, List[str]]] = {
        hid: {"supports": [], "weakens": []} for hid in ("H1", "H2", "H3")
    }
    for hid in ("H1", "H2", "H3"):
        for rel in ("supports", "weakens"):
            ranked = sorted(hypothesis_quote_candidates[hid][rel], key=lambda item: (-item[0], -len(item[1])))
            seen: Set[str] = set()
            for _, quote in ranked:
                if quote in seen:
                    continue
                seen.add(quote)
                hypothesis_quotes[hid][rel].append(quote)
                if len(hypothesis_quotes[hid][rel]) >= 5:
                    break

    intent_total = sum(intent_counts.values()) or 1
    intent_percentages = {k: round(v / intent_total * 100, 2) for k, v in intent_counts.items()}

    signal_coverage = {
        signal: {
            "count": count,
            "coverage_pct": round(count / total_analyzed * 100, 2) if total_analyzed else 0,
        }
        for signal, count in sorted(signal_counts.items(), key=lambda item: (-item[1], item[0]))
    }

    single_video_stats = {
        key: {
            "count": single_video_counts.get(key, 0),
            "coverage_pct": round(single_video_counts.get(key, 0) / total_analyzed * 100, 2)
            if total_analyzed
            else 0,
        }
        for key in SINGLE_VIDEO_LABELS
    }

    hypothesis_details = {}
    for hid in ("H1", "H2", "H3"):
        hypothesis_details[hid] = {
            "label": HYPOTHESES[hid],
            "counts": hypothesis_counts[hid],
            "unique_users": {rel: len(users) for rel, users in hypothesis_users[hid].items()},
            "by_creator_type": {
                creator: dict(rels) for creator, rels in hypothesis_by_creator[hid].items()
            },
            "support_quotes": hypothesis_quotes[hid]["supports"],
            "weaken_quotes": hypothesis_quotes[hid]["weakens"],
        }

    contradictions = _build_contradictions(hypothesis_details)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_analyzed": total_analyzed,
        "total_records": total_records or total_analyzed,
        "valid_comments": valid_comments,
        "unique_users": len(unique_users),
        "source_video_count": len(source_videos),
        "source_creator_count": len(source_creators),
        "source_file_count": len(source_files),
        "trained_users": len(trained_users),
        "gratitude_signal_count": gratitude_signal,
        "check_in_count": check_in_intent,
        "result_feedback_count": result_feedback_intent,
        "question_count": question_intent,
        "difficulty_count": difficulty_intent,
        "personalized_needed_count": personalized_needed,
        "realtime_needed_count": realtime_needed,
        "product_fit_high_count": product_fit_high,
        "high_priority_user_count": len(high_priority_users),
        "high_priority_candidate_comment_count": high_priority_candidate_comments,
        "contactable_homepage_count": contactable_homepage,
        "primary_intent_counts": dict(intent_counts),
        "primary_intent_percentages": intent_percentages,
        "signal_counts": dict(signal_counts),
        "signal_coverage": signal_coverage,
        "hypothesis_counts": hypothesis_counts,
        "hypothesis_details": hypothesis_details,
        "single_video_counts": dict(single_video_counts),
        "single_video_stats": single_video_stats,
        "product_fit_counts": dict(product_fit_counts),
        "contradictions": contradictions,
    }


def apply_candidates_to_summary(summary: Dict[str, Any], candidates: List[Any]) -> Dict[str, Any]:
    if not candidates:
        summary["high_priority_user_count_source"] = "analysis_results"
        return summary
    high_users = [c for c in candidates if getattr(c, "priority", None) == "high" or (isinstance(c, dict) and c.get("priority") == "high")]
    summary["high_priority_user_count"] = len(high_users)
    summary["high_priority_user_count_source"] = "candidates_json"
    summary["total_candidates"] = len(candidates)
    return summary


def _build_contradictions(hypothesis_details: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for hid in ("H1", "H2", "H3"):
        detail = hypothesis_details[hid]
        counts = detail["counts"]
        weakens = counts.get("weakens", 0)
        if weakens <= 0:
            continue
        supports = counts.get("supports", 0)
        related_total = sum(counts.get(key, 0) for key in ("supports", "weakens", "insufficient", "irrelevant"))
        weaken_ratio = weakens / related_total if related_total else 0
        importance = "important" if weakens >= 5 or weaken_ratio >= 0.1 else "normal"
        quotes = detail.get("weaken_quotes") or []
        items.append(
            {
                "hypothesis_id": hid,
                "hypothesis_label": detail["label"],
                "weaken_count": weakens,
                "support_count": supports,
                "importance": importance,
                "representative_quotes": quotes[:5],
                "caution_note": _contradiction_note(hid, weakens, supports),
            }
        )
    return items


def _contradiction_note(hid: str, weakens: int, supports: int) -> str:
    if hid == "H2":
        return (
            f"当前样本中有 {weakens} 条评论提供了与 H2（需实时反馈/交互指导）不一致的证据，"
            f"同时有 {supports} 条支持性评论。需结合原话判断单向视频是否足够。"
        )
    if hid == "H3":
        return (
            f"当前样本中有 {weakens} 条评论表明用户未必需要 Agent 规划训练，"
            f"与 H3 预期存在偏差，建议查看削弱性原话。"
        )
    return (
        f"当前样本中有 {weakens} 条评论与 H1（训练过程/质量假设）不一致，"
        f"请查看代表性原话后再下结论。"
    )
