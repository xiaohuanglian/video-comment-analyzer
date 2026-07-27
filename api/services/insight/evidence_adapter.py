# -*- coding: utf-8 -*-
"""Adapt between unified evidence_items and legacy multi-array cards."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .evidence_schemas import (
    ActionGapItem,
    ContentEngagementItem,
    ContentEngagementType,
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    EvidenceLevel,
    FactItem,
    ItemCertainty,
    PrimaryExpression,
    QuantitativeEvidence,
    QuotedItem,
    RecordStatus,
    SpeakerScope,
    TrainingBehaviorItem,
    TrainingBehaviorType,
    BehaviorCertainty,
    compute_evidence_level,
    normalize_certainty,
    normalize_speaker_scope,
)
from .schemas import SingleVideoRelation

CARD_PROJECTED_KEYS = (
    "single_video_relation",
    "actual_training_evidence",
    "training_impact",
    "help_seeking",
    "specific_problems",
    "product_fit",
    "product_fit_reason",
    "product_fit_source",
    "primary_intent",
    "action_gap",
    "paid_help",
    "behavior_costs",
    "evidence_quotes",
    "explicit_user_context",
    "confidence",
    "signals",
)

CONTINUED_BEHAVIOR_SUBTYPES = {
    "continued",
    "sustained_practice",
    "persistence",
    "completed_repeated",
    "completed_repeatedly",
    "ongoing_period",
}
TRIED_BEHAVIOR_SUBTYPES = {
    "attempted",
    "completed_once",
    "sought_paid_help",
    "progress",
    "completed",
    "attempted_self_correction",
    "self_reported_ability",
}
REALTIME_VIDEO_KEYWORDS = (
    "帮我看",
    "看看我",
    "动作不标准",
    "哪里不对",
    "标准吗",
    "做得对吗",
    "帮我检查",
    "跟练版",
    "找不到感觉",
    "gei不到",
    "感觉不到",
)
PERSONALIZED_VIDEO_KEYWORDS = (
    "判断",
    "左旋",
    "右旋",
    "分不清",
    "方向",
    "怎么测",
    "怎么看",
    "腰突",
    "受伤",
    "疼痛",
    "可不可以练",
    "适合我",
    "因人而异",
)
POSITIVE_RESULT_KEYWORDS = (
    "立竿见影",
    "有效果",
    "改善了",
    "舒服",
    "回正",
    "成功了",
    "矫正成功",
    "明显",
    "没以前",
    "好转",
)

PAID_ACTION_KEYWORDS = (
    "我报了",
    "我报名",
    "我买了",
    "我购买",
    "我付了",
    "我花了",
    "我办卡",
    "我办了卡",
    "我请了",
    "我找了教练",
    "我做了付费",
)
PAID_FAILURE_KEYWORDS = (
    "没效果",
    "没有效果",
    "无效果",
    "没用",
    "没有用",
    "没改善",
    "没有改善",
    "没结果",
    "没有结果",
    "白花",
    "浪费钱",
    "没有一点改变",
)
COST_SAVING_KEYWORDS = ("省钱", "省了钱", "不用花", "没花钱", "避免花")


def has_explicit_paid_action(text: str) -> bool:
    value = text or ""
    return any(keyword in value for keyword in PAID_ACTION_KEYWORDS) or bool(
        re.search(r"我.{0,10}(报了|报名|买了|购买|付了|花了|办卡|办了.{0,3}卡|请了|找了.{0,5}教练)", value)
    )


def has_paid_failure(text: str) -> bool:
    value = text or ""
    return has_explicit_paid_action(value) and any(
        keyword in value for keyword in PAID_FAILURE_KEYWORDS
    )


def is_cost_saving_result(text: str) -> bool:
    return any(keyword in (text or "") for keyword in COST_SAVING_KEYWORDS)


def legacy_arrays_to_items(payload: Dict[str, Any]) -> List[dict]:
    """Convert B1–B3 parallel arrays into evidence_items dicts."""
    items: List[dict] = []

    def add(
        etype: str,
        text: str,
        quote: str,
        *,
        subtype: str = "",
        scope: str = "unclear",
        certainty: str = "medium",
    ) -> None:
        text = (text or "").strip()
        quote = (quote or "").strip()
        if not quote:
            return
        items.append(
            {
                "type": etype,
                "text": text or quote[:40],
                "evidence_quote": quote,
                "speaker_scope": scope,
                "certainty": certainty,
                "subtype": subtype,
            }
        )

    for row in payload.get("explicit_facts") or []:
        if isinstance(row, dict):
            add("opinion", row.get("fact") or row.get("text") or "", row.get("evidence_quote") or "")
    for row in payload.get("problem_or_need") or []:
        if isinstance(row, dict):
            add("problem", row.get("text") or "", row.get("evidence_quote") or "")
    for row in payload.get("training_behavior") or []:
        if isinstance(row, dict):
            cert = str(row.get("certainty") or "explicit")
            add(
                "behavior",
                row.get("text") or "",
                row.get("evidence_quote") or "",
                subtype=str(row.get("type") or ""),
                scope="self",
                certainty="high" if cert == "explicit" else "medium",
            )
    for row in payload.get("actual_behavior") or []:
        if isinstance(row, dict):
            btype = str(row.get("type") or "other")
            mapped = {
                "planned": "planned",
                "tried": "attempted",
                "continued": "continued",
                "stopped": "stopped",
                "paid_help": "sought_paid_help",
                "changed_behavior": "changed_plan",
            }.get(btype, "")
            etype = "behavior" if mapped else "engagement"
            add(
                etype,
                row.get("text") or "",
                row.get("evidence_quote") or "",
                subtype=mapped or "other",
                scope="self",
            )
    for row in payload.get("content_engagement") or []:
        if isinstance(row, dict):
            add(
                "engagement",
                row.get("text") or "",
                row.get("evidence_quote") or "",
                subtype=str(row.get("type") or ""),
                scope="self",
            )
    for row in payload.get("action_gap") or []:
        if isinstance(row, dict):
            add(
                "action_gap",
                row.get("text") or "",
                row.get("evidence_quote") or "",
                subtype=str(row.get("subtype") or ""),
                scope="self",
                certainty="high",
            )
    for row in payload.get("current_solution") or []:
        if isinstance(row, dict):
            add("solution", row.get("text") or "", row.get("evidence_quote") or "")
    for row in payload.get("impact_or_cost") or []:
        if isinstance(row, dict):
            add("barrier", row.get("text") or "", row.get("evidence_quote") or "")
    for row in payload.get("user_context") or []:
        if isinstance(row, dict):
            add("context", row.get("text") or "", row.get("evidence_quote") or "")
    for row in payload.get("quantitative_evidence") or []:
        if isinstance(row, dict):
            text = row.get("value_text") or row.get("metric") or row.get("text") or ""
            add("quantitative", text, row.get("evidence_quote") or "", subtype="reps", certainty="high")
    for row in payload.get("possible_new_signal") or []:
        if isinstance(row, dict):
            add("context", row.get("text") or "", row.get("evidence_quote") or "", certainty="low")
    return items


def project_legacy_arrays(card: EvidenceCard) -> EvidenceCard:
    """Fill legacy parallel arrays from evidence_items for third-column / old readers."""
    facts: List[FactItem] = []
    problems: List[QuotedItem] = []
    training: List[TrainingBehaviorItem] = []
    engagement: List[ContentEngagementItem] = []
    gaps: List[ActionGapItem] = []
    solutions: List[QuotedItem] = []
    barriers: List[QuotedItem] = []
    contexts: List[QuotedItem] = []
    quants: List[QuantitativeEvidence] = []

    for item in card.evidence_items or []:
        quote = item.evidence_quote or ""
        text = item.text or ""
        if item.type == EvidenceItemType.OPINION:
            facts.append(FactItem(fact=text, evidence_quote=quote))
        elif item.type == EvidenceItemType.PROBLEM:
            problems.append(QuotedItem(text=text, evidence_quote=quote))
        elif item.type == EvidenceItemType.BEHAVIOR:
            try:
                btype = TrainingBehaviorType(item.subtype) if item.subtype else TrainingBehaviorType.OTHER
            except ValueError:
                btype = TrainingBehaviorType.OTHER
            cert = (
                BehaviorCertainty.EXPLICIT
                if item.certainty == ItemCertainty.HIGH
                else BehaviorCertainty.IMPLIED
                if item.certainty == ItemCertainty.MEDIUM
                else BehaviorCertainty.UNCERTAIN
            )
            training.append(
                TrainingBehaviorItem(type=btype, text=text, evidence_quote=quote, certainty=cert)
            )
        elif item.type == EvidenceItemType.ENGAGEMENT:
            try:
                etype = ContentEngagementType(item.subtype) if item.subtype else ContentEngagementType.OTHER
            except ValueError:
                etype = ContentEngagementType.OTHER
            engagement.append(ContentEngagementItem(type=etype, text=text, evidence_quote=quote))
        elif item.type == EvidenceItemType.ACTION_GAP:
            gaps.append(ActionGapItem(text=text, evidence_quote=quote, subtype=item.subtype or ""))
        elif item.type == EvidenceItemType.SOLUTION:
            solutions.append(QuotedItem(text=text, evidence_quote=quote))
        elif item.type == EvidenceItemType.BARRIER:
            barriers.append(QuotedItem(text=text, evidence_quote=quote))
        elif item.type in {EvidenceItemType.CONTEXT, EvidenceItemType.RESULT}:
            contexts.append(QuotedItem(text=text, evidence_quote=quote))
        elif item.type == EvidenceItemType.QUANTITATIVE:
            quants.append(
                QuantitativeEvidence(
                    metric=item.subtype or "quantity",
                    value_text=text,
                    evidence_quote=quote,
                )
            )

    card.explicit_facts = facts
    card.problem_or_need = problems
    card.training_behavior = training
    card.content_engagement = engagement
    card.action_gap = gaps
    card.current_solution = solutions
    card.impact_or_cost = barriers
    card.user_context = contexts
    card.quantitative_evidence = quants
    card.possible_new_signal = []
    card.contact_value_reason = ""
    return card


def assign_evidence_item_ids(card: EvidenceCard) -> EvidenceCard:
    """Stable ids: {record_id}::e{index} — required for research refs / report backfill."""
    rid = (card.record_id or "").strip() or "unknown"
    items = list(card.evidence_items or [])
    for idx, item in enumerate(items):
        expected = f"{rid}::e{idx}"
        current = (item.evidence_item_id or "").strip()
        if not current or not current.startswith(f"{rid}::"):
            item.evidence_item_id = expected
        # Cache reuse changes record_id; stale IDs must be rebound to the current record.
    card.evidence_items = items
    return card


def finalize_card(card: EvidenceCard) -> EvidenceCard:
    """Assign item ids, compute evidence_level and project legacy arrays."""
    card = assign_evidence_item_ids(card)
    card.evidence_level = compute_evidence_level(card.evidence_items or [], status=card.record_status)
    # Mirror validity
    if card.record_status in {
        RecordStatus.SPAM,
        RecordStatus.GARBLED,
        RecordStatus.MACHINE_GENERATED,
        RecordStatus.OFF_TOPIC,
    }:
        from .evidence_schemas import Validity

        card.validity = Validity.SPAM_OR_GARBLED
    elif card.record_status == RecordStatus.UNCLEAR:
        from .evidence_schemas import Validity

        card.validity = Validity.UNCLEAR
    elif card.evidence_level in {EvidenceLevel.STRONG, EvidenceLevel.MEDIUM}:
        from .evidence_schemas import Validity

        card.validity = Validity.MEANINGFUL_EVIDENCE
    else:
        from .evidence_schemas import Validity

        card.validity = Validity.LOW_INFORMATION_BUT_VALID
    return project_legacy_arrays(card)


def _card_text_pool(card: EvidenceCard) -> str:
    parts: List[str] = []
    for item in card.evidence_items or []:
        if item.evidence_quote:
            parts.append(item.evidence_quote.strip())
        if item.text:
            parts.append(item.text.strip())
    return "\n".join(parts)


def _behavior_subtypes(card: EvidenceCard) -> set[str]:
    subtypes: set[str] = set()
    for item in card.evidence_items or []:
        if item.type == EvidenceItemType.BEHAVIOR and item.subtype:
            subtypes.add(str(item.subtype))
    for row in card.training_behavior or []:
        if row.type:
            subtypes.add(str(row.type.value if hasattr(row.type, "value") else row.type))
    return subtypes


def infer_training_evidence(card: EvidenceCard) -> str:
    subtypes = _behavior_subtypes(card)
    if subtypes & CONTINUED_BEHAVIOR_SUBTYPES:
        return "continued"
    if subtypes & TRIED_BEHAVIOR_SUBTYPES:
        return "tried"
    if "planned" in subtypes:
        return "planned"
    return "none"


def infer_single_video_relation(card: EvidenceCard) -> str:
    """Rule-based projection for legacy statistics / candidate scoring."""
    if card.record_status != RecordStatus.USABLE:
        return SingleVideoRelation.UNCLEAR.value

    pool = _card_text_pool(card)
    expression = card.primary_expression.value
    has_problem = any(item.type == EvidenceItemType.PROBLEM for item in (card.evidence_items or []))
    has_result = any(item.type == EvidenceItemType.RESULT for item in (card.evidence_items or []))

    if any(keyword in pool for keyword in REALTIME_VIDEO_KEYWORDS):
        return SingleVideoRelation.REALTIME.value

    if expression == PrimaryExpression.HELP_REQUEST.value and has_problem:
        return SingleVideoRelation.PERSONALIZED.value

    if any(keyword in pool for keyword in PERSONALIZED_VIDEO_KEYWORDS):
        return SingleVideoRelation.PERSONALIZED.value

    if expression == PrimaryExpression.COMPLAINT.value and has_problem:
        return SingleVideoRelation.PERSONALIZED.value

    if expression in {PrimaryExpression.RESULT_FEEDBACK.value, PrimaryExpression.PRAISE.value} and (
        has_result or any(keyword in pool for keyword in POSITIVE_RESULT_KEYWORDS)
    ):
        return SingleVideoRelation.VIDEO_SUFFICIENT.value

    if expression == PrimaryExpression.QUESTION.value and not has_problem:
        if not any(keyword in pool for keyword in PERSONALIZED_VIDEO_KEYWORDS + REALTIME_VIDEO_KEYWORDS):
            return SingleVideoRelation.ONE_REPLY.value

    return SingleVideoRelation.UNCLEAR.value


def _normalize_signal_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def infer_legacy_signals(card: EvidenceCard | dict) -> List[str]:
    """Project evidence items into legacy SIGNAL_ENUM tags for statistics / filters."""
    if isinstance(card, dict):
        card = EvidenceCard.model_validate(card)
    card = project_legacy_arrays(card)
    signals: set[str] = set()
    pool = _card_text_pool(card)
    expression = card.primary_expression.value

    if expression == PrimaryExpression.PRAISE.value:
        signals.add("gratitude")

    behavior_map = {
        "planned": "saved_or_plan_to_try",
        "attempted": "started_training",
        "completed_once": "started_training",
        "continued": "continued_training",
        "ongoing_period": "continued_training",
        "stopped": "stopped_training",
        "changed_plan": "changed_training_plan",
        "sought_paid_help": "paid_professional_help",
    }
    for subtype in _behavior_subtypes(card):
        mapped = behavior_map.get(subtype)
        if mapped:
            signals.add(mapped)

    gap_map = {
        "saved_but_not_started": "skipped_exercise",
        "watched_but_not_practiced": "skipped_exercise",
        "started_but_stopped": "stopped_training",
        "planned_but_not_started": "skipped_exercise",
    }

    for item in card.evidence_items or []:
        text = f"{item.text or ''}{item.evidence_quote or ''}"
        if item.type == EvidenceItemType.ENGAGEMENT:
            if item.subtype in {"saved", "bookmarked"}:
                signals.add("saved_or_plan_to_try")
            elif item.subtype in {"searched", "searched_other"}:
                signals.add("searched_other_content")
        elif item.type == EvidenceItemType.ACTION_GAP and item.subtype in gap_map:
            signals.add(gap_map[item.subtype])
        elif item.type == EvidenceItemType.RESULT:
            if any(k in text for k in ("无效", "没变化", "没用", "更疼", "更痛", "没改善")):
                signals.add("negative_result")
            elif any(k in text for k in ("没感觉", "无感", "感受不到")):
                signals.add("no_target_muscle_sensation")
            elif any(k in text for k in ("有效", "有用", "改善", "学会", "进步", "立竿见影")):
                signals.add("positive_result")
            elif text.strip():
                signals.add("positive_result")
        elif item.type == EvidenceItemType.PROBLEM:
            if any(k in text for k in ("标准", "对不对", "是不是我", "姿势", "动作不")):
                signals.add("form_uncertainty")
            if any(k in text for k in ("怎么", "为什么", "正常吗", "区别", "是否")):
                signals.add("applicability_question")
            if any(k in text for k in ("做不了", "太难", "做不到", "学不会")):
                signals.add("cannot_complete")
            if any(k in text for k in ("没感觉", "感受不到")):
                signals.add("no_target_muscle_sensation")
            if any(k in text for k in ("疼", "痛", "伤", "不适")):
                signals.add("physical_discomfort")
            if any(k in text for k in ("替代", "换成", "没有器械", "没器械")):
                signals.add("needs_substitution")
            if any(k in text for k in ("进阶", "加大", "提高难度")):
                signals.add("needs_progression")
            if any(k in text for k in ("退阶", "简化", "降低难度")):
                signals.add("needs_regression")
            if any(k in text for k in ("计划", "安排", "怎么练", "练什么")):
                signals.add("needs_training_plan")
        elif item.type == EvidenceItemType.BARRIER:
            if any(k in text for k in ("疼", "痛", "伤")):
                signals.add("physical_discomfort")
            if any(k in text for k in ("太难", "做不到", "做不了")):
                signals.add("cannot_complete")
            if any(k in text for k in ("空间", "器械", "设备", "哑铃")):
                signals.add("equipment_or_space_constraint")
            if any(k in text for k in ("隐私", "尴尬")):
                signals.add("privacy_concern")

    if expression == PrimaryExpression.QUESTION.value:
        if not signals & {"form_uncertainty", "applicability_question"}:
            if any(k in pool for k in ("标准", "对不对", "是不是")):
                signals.add("form_uncertainty")
            else:
                signals.add("applicability_question")
    if any(k in pool for k in ("回复", "看看我", "帮我看看", "教练", "博主回")):
        signals.add("asks_coach_reply")
    if any(k in pool for k in ("录像", "拍视频", "录自己", "拍下来")):
        signals.add("recorded_self_for_review")
    if any(k in pool for k in ("坚持", "打卡", "动力", "懒", "自律")):
        signals.add("motivation_or_accountability")
    if any(k in pool for k in ("看不懂", "讲不清楚", "太快", "数错")):
        signals.add("instruction_unclear")
    if any(k in pool for k in ("太快", "跟不上", "节奏", "数")):
        signals.add("pace_or_counting_problem")
    if any(k in pool for k in ("产后", "膝盖", "腰间盘", "受伤", "手术")):
        signals.add("injury_or_special_condition")

    return sorted(signals)


def derive_new_signals_from_card(card: EvidenceCard | dict) -> List[Dict[str, Any]]:
    """Turn meaningful evidence items into open-discovery new_signals."""
    if isinstance(card, dict):
        card = EvidenceCard.model_validate(card)
    card = project_legacy_arrays(card)
    signals: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def add(signal_type: str, text: str, quote: str) -> None:
        text = (text or "").strip()
        quote = (quote or "").strip()
        if not text and not quote:
            return
        key = _normalize_signal_text(text or quote)
        if not key or key in seen:
            return
        seen.add(key)
        signals.append(
            {
                "type": signal_type,
                "text": text or quote[:40],
                "evidence_quote": quote or text[:80],
            }
        )

    type_map = {
        EvidenceItemType.PROBLEM: "new_problem",
        EvidenceItemType.BARRIER: "new_barrier",
        EvidenceItemType.ACTION_GAP: "new_barrier",
        EvidenceItemType.CONTEXT: "new_user_segment",
        EvidenceItemType.SOLUTION: "new_current_solution",
    }
    for item in card.evidence_items or []:
        mapped_type = type_map.get(item.type)
        if not mapped_type:
            continue
        if item.type == EvidenceItemType.CONTEXT and item.certainty == ItemCertainty.LOW:
            continue
        add(mapped_type, item.text or "", item.evidence_quote or "")

    return signals[:5]


def merge_projected_analysis(existing: Dict[str, Any] | None, projected: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing or {})
    for key in CARD_PROJECTED_KEYS:
        if key in projected:
            merged[key] = projected[key]
    return merged


def card_to_research_summary(card: EvidenceCard | dict, *, for_research: bool = False) -> Dict[str, Any]:
    """Compact summary for dataset research agent (evidence_items only)."""
    if isinstance(card, dict):
        card = EvidenceCard.model_validate(card)
    card = assign_evidence_item_ids(card)
    items = []
    for item in card.evidence_items or []:
        item_payload = {
            "evidence_item_id": item.evidence_item_id,
            "type": item.type.value,
            "subtype": item.subtype,
            "text": (item.text or "")[:24],
            "speaker_scope": item.speaker_scope.value,
            "certainty": item.certainty.value,
        }
        if for_research:
            items.append(item_payload)
        else:
            item_payload["evidence_quote"] = item.evidence_quote
            items.append(item_payload)
    return {
        "record_id": card.record_id,
        "record_status": card.record_status.value,
        "primary_expression": card.primary_expression.value,
        "evidence_level": card.evidence_level.value,
        "evidence_items": items,
    }


def third_column_fields(card: EvidenceCard | dict) -> Dict[str, Any]:
    """Adapter fields for outreach / candidate scoring — do not use contact_value."""
    if isinstance(card, dict):
        card = EvidenceCard.model_validate(card)
    card = project_legacy_arrays(card)
    return {
        "specific_problems": [p.text for p in card.problem_or_need if p.text],
        "actual_behavior": [
            {"type": t.type.value, "text": t.text, "evidence_quote": t.evidence_quote}
            for t in card.training_behavior
        ],
        "action_gap": [{"text": g.text, "subtype": g.subtype, "evidence_quote": g.evidence_quote} for g in card.action_gap],
        "paid_help": any(t.type == TrainingBehaviorType.SOUGHT_PAID_HELP for t in card.training_behavior)
        or any(i.subtype == "sought_paid_help" for i in card.evidence_items if i.type == EvidenceItemType.BEHAVIOR),
        "results": [i.text for i in card.evidence_items if i.type == EvidenceItemType.RESULT],
        "research_relevance": card.research_relevance.value,
        "evidence_level": card.evidence_level.value,
    }


def outreach_analysis_from_card(card: EvidenceCard | dict) -> Dict[str, Any]:
    """Project evidence card into legacy analysis-shaped dict for candidates / scoring."""
    if isinstance(card, dict):
        card = EvidenceCard.model_validate(card)
    fields = third_column_fields(card)
    training = infer_training_evidence(card)

    gap_subtypes = {g.get("subtype") or "" for g in fields["action_gap"]}
    if fields["paid_help"] or gap_subtypes & {"paid_but_no_result", "paid_but_not_used"}:
        impact = "paid_help"
    elif "started_but_stopped" in gap_subtypes:
        impact = "stopped"
    elif gap_subtypes & {"saved_but_not_started", "watched_but_not_practiced", "planned_but_not_started"}:
        impact = "skipped"
    else:
        impact = "none"

    help_seeking = card.primary_expression.value == "help_request" or bool(fields["specific_problems"])
    level = fields["evidence_level"]
    if level == "strong":
        fit = "high"
    elif level == "medium":
        fit = "medium"
    else:
        fit = "unclear"

    quotes = [i.evidence_quote for i in (card.evidence_items or []) if i.evidence_quote][:5]
    return {
        "record_id": card.record_id,
        "primary_intent": _expression_to_intent(card.primary_expression.value),
        "signals": infer_legacy_signals(card),
        "specific_problems": fields["specific_problems"],
        "actual_training_evidence": training,
        "help_seeking": help_seeking,
        "behavior_costs": [g.get("text") or "" for g in fields["action_gap"] if g.get("text")],
        "training_impact": impact,
        "single_video_relation": infer_single_video_relation(card),
        "product_fit": fit,
        "product_fit_reason": f"evidence_level={level}",
        "product_fit_source": "rule_based_projection",
        "evidence_quotes": quotes,
        "confidence": float(card.confidence or 0.7),
        "action_gap": fields["action_gap"],
        "paid_help": fields["paid_help"],
        "explicit_user_context": [i.text for i in card.evidence_items if i.type == EvidenceItemType.CONTEXT],
    }


def _expression_to_intent(expression: str) -> str:
    return {
        "question": "question",
        "help_request": "difficulty_help_request",
        "complaint": "complaint",
        "result_feedback": "result_feedback",
        "check_in": "check_in",
        "praise": "gratitude_recognition",
    }.get(expression, "other_valid")


def analysis_dict_from_result_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy results.jsonl or evidence_cards.jsonl rows for outreach scoring."""
    analysis = dict(row.get("analysis") or {})
    card_payload = row.get("card")
    if card_payload:
        projected = outreach_analysis_from_card(card_payload)
        analysis = merge_projected_analysis(analysis, projected)
        analysis["paid_help"] = bool(analysis.get("paid_help") or projected.get("paid_help"))
        return analysis
    return analysis
