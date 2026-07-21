# -*- coding: utf-8 -*-
"""Schemas for evidence-items pipeline (final convergence — evidence_items_v1)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

EVIDENCE_PROMPT_VERSION = "evidence_extract_v5"
ANALYSIS_VERSION_EVIDENCE = "evidence_items_v1"
ANALYSIS_VERSION_EVIDENCE_LEGACY = "evidence_agent_v1"  # B1–B3 artifacts
ANALYSIS_VERSION_LEGACY = "legacy_per_record"


# ---------------------------------------------------------------------------
# Status / level
# ---------------------------------------------------------------------------


class RecordStatus(str, Enum):
    USABLE = "usable"
    OFF_TOPIC = "off_topic"
    MACHINE_GENERATED = "machine_generated"
    SPAM = "spam"
    GARBLED = "garbled"
    UNCLEAR = "unclear"
    SPAM_OR_GARBLED = "spam_or_garbled"  # legacy alias → SPAM via normalize


class EvidenceLevel(str, Enum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    NONE = "none"


class Validity(str, Enum):
    """Legacy mirror for old readers."""

    MEANINGFUL_EVIDENCE = "meaningful_evidence"
    LOW_INFORMATION_BUT_VALID = "low_information_but_valid"
    SPAM_OR_GARBLED = "spam_or_garbled"
    UNCLEAR = "unclear"
    VALID = "valid"
    INVALID = "invalid"


def normalize_record_status(value: Any) -> RecordStatus:
    raw = (value.value if isinstance(value, Enum) else str(value or "")).strip()
    mapping = {
        "usable": RecordStatus.USABLE,
        "off_topic": RecordStatus.OFF_TOPIC,
        "machine_generated": RecordStatus.MACHINE_GENERATED,
        "spam": RecordStatus.SPAM,
        "garbled": RecordStatus.GARBLED,
        "unclear": RecordStatus.UNCLEAR,
        "spam_or_garbled": RecordStatus.SPAM,
        "valid": RecordStatus.USABLE,
        "meaningful_evidence": RecordStatus.USABLE,
        "low_information_but_valid": RecordStatus.USABLE,
        "invalid": RecordStatus.SPAM,
    }
    return mapping.get(raw, RecordStatus.UNCLEAR)


def normalize_evidence_level(value: Any) -> EvidenceLevel:
    raw = (value.value if isinstance(value, Enum) else str(value or "")).strip()
    mapping = {
        "strong": EvidenceLevel.STRONG,
        "medium": EvidenceLevel.MEDIUM,
        "weak": EvidenceLevel.WEAK,
        "none": EvidenceLevel.NONE,
        "meaningful_evidence": EvidenceLevel.STRONG,
        "low_information_but_valid": EvidenceLevel.WEAK,
        "valid": EvidenceLevel.MEDIUM,
        "invalid": EvidenceLevel.NONE,
        "spam_or_garbled": EvidenceLevel.NONE,
        "spam": EvidenceLevel.NONE,
        "garbled": EvidenceLevel.NONE,
        "machine_generated": EvidenceLevel.NONE,
        "off_topic": EvidenceLevel.NONE,
        "unclear": EvidenceLevel.NONE,
    }
    return mapping.get(raw, EvidenceLevel.NONE)


def normalize_validity(value: Any) -> Validity:
    raw = (value.value if isinstance(value, Validity) else str(value or "")).strip()
    mapping = {
        "valid": Validity.MEANINGFUL_EVIDENCE,
        "meaningful_evidence": Validity.MEANINGFUL_EVIDENCE,
        "low_information_but_valid": Validity.LOW_INFORMATION_BUT_VALID,
        "invalid": Validity.SPAM_OR_GARBLED,
        "spam_or_garbled": Validity.SPAM_OR_GARBLED,
        "spam": Validity.SPAM_OR_GARBLED,
        "garbled": Validity.SPAM_OR_GARBLED,
        "machine_generated": Validity.SPAM_OR_GARBLED,
        "unclear": Validity.UNCLEAR,
        "usable": Validity.LOW_INFORMATION_BUT_VALID,
        "off_topic": Validity.SPAM_OR_GARBLED,
    }
    return mapping.get(raw, Validity.UNCLEAR)


def is_meaningful_level(value: Any) -> bool:
    return normalize_evidence_level(value) in {EvidenceLevel.STRONG, EvidenceLevel.MEDIUM}


def is_participating_status(value: Any) -> bool:
    return normalize_record_status(value) in {RecordStatus.USABLE, RecordStatus.UNCLEAR}


def is_excluded_status(value: Any) -> bool:
    return normalize_record_status(value) in {
        RecordStatus.SPAM,
        RecordStatus.GARBLED,
        RecordStatus.MACHINE_GENERATED,
        RecordStatus.OFF_TOPIC,
        RecordStatus.SPAM_OR_GARBLED,
    }


def is_participating_validity(value: Any) -> bool:
    if isinstance(value, dict):
        if "record_status" in value:
            return is_participating_status(value.get("record_status"))
        value = value.get("validity")
    raw = str(value or "")
    if raw in {s.value for s in RecordStatus}:
        return is_participating_status(raw)
    v = normalize_validity(value)
    return v in {
        Validity.MEANINGFUL_EVIDENCE,
        Validity.LOW_INFORMATION_BUT_VALID,
        Validity.UNCLEAR,
        Validity.VALID,
    }


def is_spam_validity(value: Any) -> bool:
    raw = str(value or "")
    if raw in {s.value for s in RecordStatus}:
        return is_excluded_status(raw)
    v = normalize_validity(value)
    return v in {Validity.SPAM_OR_GARBLED, Validity.INVALID}


# ---------------------------------------------------------------------------
# Expression / evidence item enums
# ---------------------------------------------------------------------------


class PrimaryExpression(str, Enum):
    QUESTION = "question"
    HELP_REQUEST = "help_request"
    COMPLAINT = "complaint"
    RESULT_FEEDBACK = "result_feedback"
    CHECK_IN = "check_in"
    PRAISE = "praise"
    GRATITUDE = "gratitude"  # legacy alias; prefer praise
    OTHER = "other"


class EvidenceItemType(str, Enum):
    PROBLEM = "problem"
    BEHAVIOR = "behavior"
    RESULT = "result"
    CONTEXT = "context"
    SOLUTION = "solution"
    BARRIER = "barrier"
    ACTION_GAP = "action_gap"
    ENGAGEMENT = "engagement"
    OPINION = "opinion"
    QUANTITATIVE = "quantitative"


class SpeakerScope(str, Enum):
    SELF = "self"
    OTHER_USER = "other_user"
    GENERAL_OBSERVATION = "general_observation"
    GENERAL_PEOPLE = "general_people"  # legacy → general_observation
    CREATOR_OR_CONTENT = "creator_or_content"
    UNCLEAR = "unclear"


class ItemCertainty(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Legacy enums kept for reading B1–B3 artifacts / projection
class ExpressionSignal(str, Enum):
    OPINION = "opinion"
    ADVICE = "advice"
    HUMOR = "humor"
    EXPERIENCE_SHARING = "experience_sharing"
    CONTENT_REQUEST = "content_request"
    DIFFICULTY = "difficulty"
    ACTION_GAP = "action_gap"
    OTHER = "other"


class TrainingBehaviorType(str, Enum):
    PLANNED = "planned"
    ATTEMPTED = "attempted"
    COMPLETED_ONCE = "completed_once"
    CONTINUED = "continued"
    PROGRESS = "progress"
    STOPPED = "stopped"
    CHANGED_PLAN = "changed_plan"
    SOUGHT_PAID_HELP = "sought_paid_help"
    SELF_REPORTED_ABILITY = "self_reported_ability"
    OTHER = "other"


class ContentEngagementType(str, Enum):
    VIEWED = "viewed"
    SAVED = "saved"
    FOLLOWED = "followed"
    COMMENTED = "commented"
    CHECKED_IN = "checked_in"
    SHARED = "shared"
    SKIPPED = "skipped"
    OTHER = "other"


class BehaviorCertainty(str, Enum):
    EXPLICIT = "explicit"
    IMPLIED = "implied"
    UNCERTAIN = "uncertain"


class BehaviorType(str, Enum):
    PLANNED = "planned"
    TRIED = "tried"
    CONTINUED = "continued"
    SEARCHED = "searched"
    ASKED_OTHERS = "asked_others"
    CHANGED_BEHAVIOR = "changed_behavior"
    STOPPED = "stopped"
    PAID_HELP = "paid_help"
    OTHER = "other"


class NewSignalKind(str, Enum):
    NEW_USER_SEGMENT = "new_user_segment"
    NEW_PROBLEM = "new_problem"
    NEW_SCENE = "new_scene"
    NEW_BARRIER = "new_barrier"
    NEW_MOTIVATION = "new_motivation"
    NEW_SOLUTION = "new_solution"
    NEW_EXPECTATION = "new_expectation"
    OTHER = "other"


class ResearchRelevance(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCLEAR = "unclear"


class ContactValue(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCLEAR = "unclear"


class StatementMode(str, Enum):
    PERSONAL_EXPERIENCE = "personal_experience"
    OPINION = "opinion"
    ADVICE = "advice"
    QUESTION = "question"
    HUMOR = "humor"
    REPORT = "report"
    UNCLEAR = "unclear"


def normalize_speaker_scope(value: Any) -> SpeakerScope:
    raw = (value.value if isinstance(value, Enum) else str(value or "")).strip()
    mapping = {
        "self": SpeakerScope.SELF,
        "other_user": SpeakerScope.OTHER_USER,
        "general_observation": SpeakerScope.GENERAL_OBSERVATION,
        "general_people": SpeakerScope.GENERAL_OBSERVATION,
        "creator_or_content": SpeakerScope.CREATOR_OR_CONTENT,
        "unclear": SpeakerScope.UNCLEAR,
    }
    return mapping.get(raw, SpeakerScope.UNCLEAR)


def normalize_certainty(value: Any) -> ItemCertainty:
    raw = (value.value if isinstance(value, Enum) else str(value or "")).strip()
    mapping = {
        "high": ItemCertainty.HIGH,
        "medium": ItemCertainty.MEDIUM,
        "low": ItemCertainty.LOW,
        "explicit": ItemCertainty.HIGH,
        "implied": ItemCertainty.MEDIUM,
        "uncertain": ItemCertainty.LOW,
    }
    return mapping.get(raw, ItemCertainty.MEDIUM)


# ---------------------------------------------------------------------------
# Unified evidence item
# ---------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    type: EvidenceItemType
    text: str = ""
    evidence_quote: str = ""
    speaker_scope: SpeakerScope = SpeakerScope.UNCLEAR
    certainty: ItemCertainty = ItemCertainty.MEDIUM
    subtype: str = ""
    evidence_item_id: str = ""  # assigned by code: {record_id}::e{index}

    @field_validator("type", mode="before")
    @classmethod
    def coerce_type(cls, value: Any) -> EvidenceItemType:
        raw = (value.value if isinstance(value, Enum) else str(value or "")).strip()
        # legacy field name bridges
        aliases = {
            "problem_or_need": "problem",
            "training_behavior": "behavior",
            "content_engagement": "engagement",
            "current_solution": "solution",
            "impact_or_cost": "barrier",
            "user_context": "context",
            "explicit_facts": "opinion",
            "possible_new_signal": "context",
            "quantitative_evidence": "quantitative",
            "fact": "opinion",
        }
        raw = aliases.get(raw, raw)
        try:
            return EvidenceItemType(raw)
        except ValueError as exc:
            raise ValueError(f"非法 evidence type: {raw}") from exc

    @field_validator("speaker_scope", mode="before")
    @classmethod
    def coerce_scope(cls, value: Any) -> SpeakerScope:
        return normalize_speaker_scope(value)

    @field_validator("certainty", mode="before")
    @classmethod
    def coerce_certainty(cls, value: Any) -> ItemCertainty:
        return normalize_certainty(value)


# Legacy list item shapes (read-only / projection)
class QuotedItem(BaseModel):
    text: str = ""
    evidence_quote: str = ""


class FactItem(BaseModel):
    fact: str = ""
    evidence_quote: str = ""


class TrainingBehaviorItem(BaseModel):
    type: TrainingBehaviorType = TrainingBehaviorType.OTHER
    text: str = ""
    evidence_quote: str = ""
    certainty: BehaviorCertainty = BehaviorCertainty.EXPLICIT


class ContentEngagementItem(BaseModel):
    type: ContentEngagementType = ContentEngagementType.OTHER
    text: str = ""
    evidence_quote: str = ""


class ActionGapItem(BaseModel):
    text: str = ""
    evidence_quote: str = ""
    subtype: str = ""


class BehaviorItem(BaseModel):
    type: BehaviorType = BehaviorType.OTHER
    text: str = ""
    evidence_quote: str = ""


class PossibleNewSignal(BaseModel):
    type: NewSignalKind = NewSignalKind.OTHER
    text: str = ""
    evidence_quote: str = ""


class QuantitativeEvidence(BaseModel):
    metric: str = ""
    value_text: str = ""
    evidence_quote: str = ""


# ---------------------------------------------------------------------------
# Evidence card
# ---------------------------------------------------------------------------


class EvidenceCard(BaseModel):
    """Per-comment evidence — unified evidence_items; legacy arrays projected for compatibility."""

    record_id: str
    record_status: RecordStatus = RecordStatus.USABLE
    primary_expression: PrimaryExpression = PrimaryExpression.OTHER
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    # Code-computed (not from LLM)
    evidence_level: EvidenceLevel = EvidenceLevel.WEAK
    status_reason: str = ""
    downgrade_reason: str = ""
    # Legacy mirrors
    validity: Validity = Validity.LOW_INFORMATION_BUT_VALID
    invalid_reason: str = ""
    secondary_expressions: List[PrimaryExpression] = Field(default_factory=list)
    expression_signals: List[ExpressionSignal] = Field(default_factory=list)
    speaker_scope: SpeakerScope = SpeakerScope.UNCLEAR
    statement_mode: StatementMode = StatementMode.UNCLEAR
    explicit_facts: List[FactItem] = Field(default_factory=list)
    problem_or_need: List[QuotedItem] = Field(default_factory=list)
    training_behavior: List[TrainingBehaviorItem] = Field(default_factory=list)
    content_engagement: List[ContentEngagementItem] = Field(default_factory=list)
    action_gap: List[ActionGapItem] = Field(default_factory=list)
    actual_behavior: List[BehaviorItem] = Field(default_factory=list)
    current_solution: List[QuotedItem] = Field(default_factory=list)
    impact_or_cost: List[QuotedItem] = Field(default_factory=list)
    user_context: List[QuotedItem] = Field(default_factory=list)
    quantitative_evidence: List[QuantitativeEvidence] = Field(default_factory=list)
    possible_new_signal: List[PossibleNewSignal] = Field(default_factory=list)
    research_relevance: ResearchRelevance = ResearchRelevance.UNCLEAR
    research_relevance_reason: str = ""
    contact_value: ContactValue = ContactValue.UNCLEAR
    contact_value_reason: str = ""
    confidence: float = 0.0
    reused_from_record_id: str = ""

    @field_validator("record_status", mode="before")
    @classmethod
    def coerce_status(cls, value: Any) -> RecordStatus:
        return normalize_record_status(value)

    @field_validator("evidence_level", mode="before")
    @classmethod
    def coerce_level(cls, value: Any) -> EvidenceLevel:
        return normalize_evidence_level(value)

    @field_validator("validity", mode="before")
    @classmethod
    def coerce_validity(cls, value: Any) -> Validity:
        return normalize_validity(value)

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @model_validator(mode="before")
    @classmethod
    def bridge_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if "record_status" not in payload and "validity" in payload:
            payload["record_status"] = normalize_record_status(payload.get("validity")).value
        if "status_reason" not in payload and payload.get("invalid_reason"):
            payload["status_reason"] = payload.get("invalid_reason") or ""
        # Build evidence_items from legacy arrays when missing
        if not payload.get("evidence_items"):
            from .evidence_adapter import legacy_arrays_to_items

            items = legacy_arrays_to_items(payload)
            if items:
                payload["evidence_items"] = items
        # Mirror status → validity
        if "validity" not in payload and "record_status" in payload:
            status = normalize_record_status(payload.get("record_status"))
            level = normalize_evidence_level(payload.get("evidence_level"))
            if status in {
                RecordStatus.SPAM,
                RecordStatus.GARBLED,
                RecordStatus.MACHINE_GENERATED,
                RecordStatus.SPAM_OR_GARBLED,
                RecordStatus.OFF_TOPIC,
            }:
                payload["validity"] = Validity.SPAM_OR_GARBLED.value
            elif status == RecordStatus.UNCLEAR:
                payload["validity"] = Validity.UNCLEAR.value
            elif level in {EvidenceLevel.STRONG, EvidenceLevel.MEDIUM}:
                payload["validity"] = Validity.MEANINGFUL_EVIDENCE.value
            else:
                payload["validity"] = Validity.LOW_INFORMATION_BUT_VALID.value
        if "research_relevance" not in payload and payload.get("contact_value"):
            cv = str(payload.get("contact_value") or "unclear")
            payload["research_relevance"] = cv if cv in {"high", "medium", "low", "unclear"} else "unclear"
        return payload


class EvidenceCardLLMItem(BaseModel):
    """LLM batch item — only unified fields."""

    record_id: str
    record_status: RecordStatus = RecordStatus.USABLE
    primary_expression: PrimaryExpression = PrimaryExpression.OTHER
    evidence_items: List[EvidenceItem] = Field(default_factory=list)
    status_reason: str = ""

    @field_validator("record_status", mode="before")
    @classmethod
    def coerce_status(cls, value: Any) -> RecordStatus:
        return normalize_record_status(value)


class EvidenceBatchLLMOutput(BaseModel):
    cards: List[EvidenceCardLLMItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Code-owned evidence_level
# ---------------------------------------------------------------------------

_STRONG_BEHAVIOR_SUBTYPES: Set[str] = {
    "attempted",
    "completed_once",
    "continued",
    "progress",
    "stopped",
    "changed_plan",
    "sought_paid_help",
}
_MEDIUM_TYPES: Set[EvidenceItemType] = {
    EvidenceItemType.PROBLEM,
    EvidenceItemType.SOLUTION,
    EvidenceItemType.BARRIER,
    EvidenceItemType.BEHAVIOR,
    EvidenceItemType.ACTION_GAP,
    EvidenceItemType.RESULT,
}


def compute_evidence_level(items: List[EvidenceItem], *, status: RecordStatus = RecordStatus.USABLE) -> EvidenceLevel:
    """Code-owned level — LLM must not set this."""
    if is_excluded_status(status) and status != RecordStatus.UNCLEAR:
        if not items:
            return EvidenceLevel.NONE
    if not items:
        return EvidenceLevel.NONE if status != RecordStatus.USABLE else EvidenceLevel.WEAK

    has_strong = False
    has_medium = False
    for item in items:
        if item.type == EvidenceItemType.QUANTITATIVE and item.certainty != ItemCertainty.LOW:
            has_strong = True
        if item.type == EvidenceItemType.BEHAVIOR and (
            item.subtype in _STRONG_BEHAVIOR_SUBTYPES or item.speaker_scope == SpeakerScope.SELF
        ):
            if item.certainty == ItemCertainty.HIGH or item.subtype in _STRONG_BEHAVIOR_SUBTYPES:
                has_strong = True
            else:
                has_medium = True
        if item.type == EvidenceItemType.ACTION_GAP and item.certainty == ItemCertainty.HIGH:
            has_strong = True
        if item.type in _MEDIUM_TYPES:
            has_medium = True
        if item.type == EvidenceItemType.RESULT and item.speaker_scope == SpeakerScope.SELF:
            has_strong = True

    if has_strong:
        return EvidenceLevel.STRONG
    if has_medium:
        return EvidenceLevel.MEDIUM
    # only opinion / low engagement
    return EvidenceLevel.WEAK


# ---------------------------------------------------------------------------
# Research schemas
# ---------------------------------------------------------------------------


class HypothesisConclusion(str, Enum):
    SUPPORTED = "supported"
    WEAKENED = "weakened"
    MIXED = "mixed"
    INSUFFICIENT = "insufficient"


class EvidenceStrength(str, Enum):
    DIRECT = "direct"
    BEHAVIORAL = "behavioral"
    WEAK_CONTEXT = "weak_context"


class DatasetSummaryCounts(BaseModel):
    total_comments: int = 0
    usable_comments: int = 0
    unclear_comments: int = 0
    off_topic_comments: int = 0
    machine_generated_comments: int = 0
    spam_comments: int = 0
    garbled_comments: int = 0
    strong_evidence_comments: int = 0
    medium_evidence_comments: int = 0
    weak_evidence_comments: int = 0
    none_evidence_comments: int = 0
    problem_comments: int = 0
    behavior_comments: int = 0
    action_gap_comments: int = 0
    valid_comments: int = 0
    meaningful_comments: int = 0
    low_information_comments: int = 0
    unique_users: int = 0
    source_files: int = 0
    videos: int = 0
    creators: int = 0
    theme_covered_comments: int = 0
    theme_coverage_rate: float = 0.0
    unthemed_usable_comments: int = 0
    unthemed_meaningful_comments: int = 0


class ResearchTheme(BaseModel):
    theme_id: str
    theme_name: str
    theme_definition: str = ""
    comment_record_ids: List[str] = Field(default_factory=list)
    comment_count: int = 0
    unique_user_count: int = 0
    source_count: int = 0
    # Research agent returns refs only; quotes are code-backfilled for display
    representative_evidence_refs: List["EvidenceRef"] = Field(default_factory=list)
    representative_quotes: List[str] = Field(default_factory=list)  # display only / legacy
    current_solutions: List[str] = Field(default_factory=list)
    impact_or_cost: List[str] = Field(default_factory=list)
    counter_evidence: List[str] = Field(default_factory=list)
    confidence: float = 0.0


class EvidenceRef(BaseModel):
    """Stable pointer into evidence_cards — never carries rewritten quote text."""

    record_id: str
    evidence_item_id: str = ""


class HypothesisEvidenceRef(BaseModel):
    record_id: str
    evidence_item_id: str = ""
    strength: EvidenceStrength = EvidenceStrength.WEAK_CONTEXT
    note: str = ""


class HypothesisAssessment(BaseModel):
    hypothesis_id: str
    conclusion: HypothesisConclusion = HypothesisConclusion.INSUFFICIENT
    supporting_record_ids: List[str] = Field(default_factory=list)
    weakening_record_ids: List[str] = Field(default_factory=list)
    supporting_evidence_refs: List[HypothesisEvidenceRef] = Field(default_factory=list)
    weakening_evidence_refs: List[HypothesisEvidenceRef] = Field(default_factory=list)
    reasoning_summary: str = ""
    unknowns: List[str] = Field(default_factory=list)


class UnexpectedFinding(BaseModel):
    finding: str
    record_ids: List[str] = Field(default_factory=list)
    supporting_evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    why_it_matters: str = ""
    conclusion: str = ""
    limitations: str = ""
    next_step: str = ""


class OpportunityHypothesis(BaseModel):
    opportunity_name: str
    supporting_evidence: List[str] = Field(default_factory=list)  # short notes, not quotes
    supporting_evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    counter_evidence: List[str] = Field(default_factory=list)
    counter_evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    possible_product_form: List[str] = Field(default_factory=list)
    possible_content_form: List[str] = Field(default_factory=list)
    current_unknowns: List[str] = Field(default_factory=list)
    recommended_validation: List[str] = Field(default_factory=list)
    supporting_record_ids: List[str] = Field(default_factory=list)
    target_users: str = ""
    concrete_problem: str = ""
    current_alternatives: List[str] = Field(default_factory=list)
    behavior_evidence_refs: List[EvidenceRef] = Field(default_factory=list)


class ResearchAnalysis(BaseModel):
    dataset_summary: DatasetSummaryCounts = Field(default_factory=DatasetSummaryCounts)
    themes: List[ResearchTheme] = Field(default_factory=list)
    hypothesis_assessment: List[HypothesisAssessment] = Field(default_factory=list)
    unexpected_findings: List[UnexpectedFinding] = Field(default_factory=list)
    opportunity_hypotheses: List[OpportunityHypothesis] = Field(default_factory=list)
    research_conclusions: List[str] = Field(default_factory=list)
    recommended_interviews: List[str] = Field(default_factory=list)
    recommended_experiments: List[str] = Field(default_factory=list)
    model_draft: Dict[str, Any] = Field(default_factory=dict)


class ReviewIssueType(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    MISSING_COUNTER_EVIDENCE = "missing_counter_evidence"
    COUNT_MISMATCH = "count_mismatch"
    OVERGENERALIZATION = "overgeneralization"
    EMPTY_EVIDENCE_QUOTE = "empty_evidence_quote"
    OTHER = "other"


class ReviewIssue(BaseModel):
    type: ReviewIssueType = ReviewIssueType.OTHER
    description: str = ""
    related_record_ids: List[str] = Field(default_factory=list)


class ConclusionReview(BaseModel):
    structural_review_passed: bool = True
    issues: List[ReviewIssue] = Field(default_factory=list)
    corrected_sections: Dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.structural_review_passed
