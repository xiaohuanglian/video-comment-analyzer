# -*- coding: utf-8 -*-
"""Adapt between unified evidence_items and legacy multi-array cards."""

from __future__ import annotations

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
        if not (item.evidence_item_id or "").strip():
            item.evidence_item_id = expected
        # Keep existing ids if already set (resume / cache); reindex only blanks
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


def card_to_research_summary(card: EvidenceCard | dict) -> Dict[str, Any]:
    """Compact summary for dataset research agent (evidence_items only)."""
    if isinstance(card, dict):
        card = EvidenceCard.model_validate(card)
    card = assign_evidence_item_ids(card)
    items = []
    for item in card.evidence_items or []:
        items.append(
            {
                "evidence_item_id": item.evidence_item_id,
                "type": item.type.value,
                "subtype": item.subtype,
                "text": item.text,
                "evidence_quote": item.evidence_quote,
                "speaker_scope": item.speaker_scope.value,
                "certainty": item.certainty.value,
            }
        )
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
    subtypes = [b.get("type") or "" for b in fields["actual_behavior"]]
    if "continued" in subtypes:
        training = "continued"
    elif any(s in subtypes for s in ("attempted", "completed_once", "sought_paid_help", "progress")):
        training = "tried"
    elif "planned" in subtypes:
        training = "planned"
    else:
        training = "none"

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
        "signals": [],
        "specific_problems": fields["specific_problems"],
        "actual_training_evidence": training,
        "help_seeking": help_seeking,
        "behavior_costs": [g.get("text") or "" for g in fields["action_gap"] if g.get("text")],
        "training_impact": impact,
        "single_video_relation": "unclear",
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
        for key, value in projected.items():
            if key == "action_gap":
                analysis[key] = value
                continue
            if key == "paid_help":
                analysis[key] = bool(analysis.get(key) or value)
                continue
            if not analysis.get(key):
                analysis[key] = value
        return analysis
    return analysis
