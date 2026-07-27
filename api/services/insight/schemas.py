# -*- coding: utf-8 -*-
"""Pydantic schemas for comment insight analysis."""

from collections import Counter
from enum import Enum
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

from .evidence_schemas import EVIDENCE_PROMPT_VERSION
from .pricing import DEFAULT_BASE_URL, DEFAULT_MODEL


def coerce_boolish(value: Any) -> bool:
    """LLM sometimes returns [], free text, or intent labels instead of bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, (list, tuple, set, dict)):
        return False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "是", "有"}:
            return True
        if lowered in {"false", "no", "n", "0", "否", "无", "", "none", "null"}:
            return False
        return False
    return False


def is_status_only_message(message: str) -> bool:
    text = (message or "").strip()
    return text.startswith("用户已停止") or text.startswith("已达到预算上限")


def summarize_error_message(message: str) -> str:
    """Collapse noisy per-record validation text into a stable reason key."""
    text = (message or "").strip()
    if not text:
        return "未知错误"
    if is_status_only_message(text):
        return text
    pipeline_prefix = ""
    if text.startswith("研究阶段"):
        pipeline_prefix = "研究阶段失败: "
    elif text.startswith("自动导出失败"):
        pipeline_prefix = "自动导出失败: "
    match = re.search(
        r"validation error for \w+\s+(\w+)\s+.*?\[type=(\w+)",
        text,
        flags=re.DOTALL,
    )
    if match:
        field, err_type = match.group(1), match.group(2)
        if field == "help_seeking" and err_type in {"bool_parsing", "bool_type"}:
            detail = "LLM 字段校验失败: help_seeking 应为 true/false（模型偶发填了字符串或数组）"
        else:
            detail = f"LLM 字段校验失败: {field} ({err_type})"
        return f"{pipeline_prefix}{detail}" if pipeline_prefix else detail
    if "Extra data" in text and "JSON" in text:
        return "进度文件读写冲突（已可自动恢复，请重试）"
    if len(text) > 220:
        return text[:217] + "…"
    return text


class PrimaryIntent(str, Enum):
    GRATITUDE = "gratitude_recognition"
    CHECK_IN = "check_in"
    RESULT_FEEDBACK = "result_feedback"
    QUESTION = "question"
    DIFFICULTY = "difficulty_help_request"
    COMPLAINT = "complaint"
    OTHER_VALID = "other_valid"
    INVALID = "invalid_or_unclear"


class TrainingEvidence(str, Enum):
    NONE = "none"
    PLANNED = "planned"
    TRIED = "tried"
    CONTINUED = "continued"


class TrainingImpact(str, Enum):
    NONE = "none"
    UNCLEAR = "unclear"
    SKIPPED = "skipped"
    STOPPED = "stopped"
    CHANGED_PLAN = "changed_plan"
    PAID_HELP = "paid_help"


class SingleVideoRelation(str, Enum):
    VIDEO_SUFFICIENT = "video_sufficient"
    ONE_REPLY = "one_reply_sufficient"
    PERSONALIZED = "personalized_judgment_needed"
    REALTIME = "realtime_observation_needed"
    UNCLEAR = "unclear"


class ProductFit(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCLEAR = "unclear"


class HypothesisRelationType(str, Enum):
    SUPPORTS = "supports"
    WEAKENS = "weakens"
    INSUFFICIENT = "insufficient"
    IRRELEVANT = "irrelevant"


class NewSignalType(str, Enum):
    NEW_USER_SEGMENT = "new_user_segment"
    NEW_PROBLEM = "new_problem"
    NEW_SCENE = "new_scene"
    NEW_BARRIER = "new_barrier"
    NEW_MOTIVATION = "new_motivation"
    NEW_CURRENT_SOLUTION = "new_current_solution"
    NEW_PRODUCT_EXPECTATION = "new_product_expectation"
    OTHER = "other"


class HypothesisRelation(BaseModel):
    hypothesis_id: str
    relation: HypothesisRelationType
    evidence_quote: str = ""

    @field_validator("hypothesis_id")
    @classmethod
    def validate_hypothesis_id(cls, value: str) -> str:
        if value not in {"H1", "H2", "H3"}:
            raise ValueError("hypothesis_id 必须是 H1、H2 或 H3")
        return value


class NewSignal(BaseModel):
    type: NewSignalType
    text: str
    evidence_quote: str


class CommentAnalysisResult(BaseModel):
    record_id: str
    primary_intent: PrimaryIntent
    signals: List[str] = Field(default_factory=list)
    explicit_user_context: List[str] = Field(default_factory=list)
    exercise_mentions: List[str] = Field(default_factory=list)
    specific_problems: List[str] = Field(default_factory=list)
    actual_training_evidence: TrainingEvidence = TrainingEvidence.NONE
    current_workarounds: List[str] = Field(default_factory=list)
    help_seeking: bool = False
    behavior_costs: List[str] = Field(default_factory=list)
    training_impact: TrainingImpact = TrainingImpact.NONE
    single_video_relation: SingleVideoRelation = SingleVideoRelation.UNCLEAR
    single_video_limitation_summary: str = ""
    hypothesis_relations: List[HypothesisRelation] = Field(default_factory=list)
    known_scene_matches: List[str] = Field(default_factory=list)
    new_signals: List[NewSignal] = Field(default_factory=list)
    potential_needs: List[str] = Field(default_factory=list)
    product_fit: ProductFit = ProductFit.UNCLEAR
    product_fit_reason: str = ""
    evidence_quotes: List[str] = Field(default_factory=list)
    confidence: float = 0.0

    @field_validator("help_seeking", mode="before")
    @classmethod
    def coerce_help_seeking(cls, value: Any) -> bool:
        return coerce_boolish(value)

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @field_validator("known_scene_matches")
    @classmethod
    def validate_known_scenes(cls, value: List[str]) -> List[str]:
        for scene in value:
            if scene not in {"S1", "S2", "S3"}:
                raise ValueError("known_scene_matches 只能是 S1、S2 或 S3")
        return value


class CommentAnalysisBatch(BaseModel):
    results: List[CommentAnalysisResult]


class FieldMapping(BaseModel):
    comment_text: str
    username: Optional[str] = None
    user_id: Optional[str] = None
    user_homepage_url: Optional[str] = None
    comment_url: Optional[str] = None
    video_title: Optional[str] = None
    creator_name: Optional[str] = None
    creator_type: Optional[str] = None
    platform: Optional[str] = None


class SourceRecord(BaseModel):
    internal_record_id: str
    source_file: str
    source_sheet: str = ""
    source_row_number: int
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    comment_text: str
    parent_comment: str = ""
    creator_reply: str = ""
    username: str = ""
    user_id: str = ""
    user_homepage_url: str = ""
    comment_url: str = ""
    video_title: str = ""
    video_url: str = ""
    creator_name: str = ""
    creator_type: str = "未知"
    platform: str = "unknown"
    like_count: int = 0
    reply_count: int = 0
    published_at: Optional[str] = None
    status: str = "pending"


class RunConfig(BaseModel):
    run_id: str
    name: str
    file_paths: List[str]
    field_mapping: FieldMapping
    prompt_version: str = EVIDENCE_PROMPT_VERSION
    model_name: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    input_price: float = 0.001
    output_price: float = 0.002
    currency: str = "CNY"
    budget_limit: float = 0.0
    analysis_limit: int = Field(default=100, ge=0, description="Per-batch cap; 0 means all pending")
    use_mock: bool = False
    created_at: str = ""
    research_targets: List[str] = Field(default_factory=list)
    storage_dir: str = ""
    analysis_version: Literal["evidence_items_v1"] = "evidence_items_v1"
    batch_size: int = Field(default=20, ge=1, le=50)
    concurrency: int = Field(default=8, ge=1, le=16)
    project_id: str = "kineo"
    project_version: str = "1"
    project_context_compact: str = ""
    project_context: str = ""  # full context for research agent; extract uses compact
    use_llm_review: bool = False  # default: code-only structural review
    # Keep legacy for existing runs until hybrid quality gates are approved.
    themes_engine: Literal["legacy_llm_v1", "hybrid_cluster_v1"] = "legacy_llm_v1"
    allow_legacy_theme_fallback: bool = True
    theme_embedding_model: str = "BAAI/bge-m3"
    theme_embedding_batch_size: int = Field(default=16, ge=1, le=64)
    theme_embedding_device: str = "auto"
    theme_cluster_min_samples: int = Field(default=3, ge=1, le=20)

    @field_validator("analysis_version", mode="before")
    @classmethod
    def force_evidence_analysis_version(cls, _value: Any) -> str:
        """Migrate old run configs to the only supported analysis engine."""
        return "evidence_items_v1"


class RunProgress(BaseModel):
    status: str = "idle"
    total_records: int = 0
    completed: int = 0
    failed: int = 0
    skipped: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    last_error: str = ""
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    eta_seconds: Optional[int] = None
    cancel_requested: bool = False
    failed_record_ids: List[str] = Field(default_factory=list)
    retry_counts: Dict[str, int] = Field(default_factory=dict)
    # Human-readable label for the CSV/video folder currently being analyzed.
    current_source_label: Optional[str] = None
    current_chunk_index: int = 0
    current_chunk_total: int = 0
    # Cards extracted in the current chunk but not yet written to results.jsonl.
    extracting_count: int = 0
    # record_id -> latest error message for that failed item
    failed_errors: Dict[str, str] = Field(default_factory=dict)

    @computed_field
    @property
    def error_summary(self) -> List[Dict[str, Any]]:
        """Unique failure reasons with counts (for UI; not only the latest)."""
        items: List[Dict[str, Any]] = []
        if self.failed_errors:
            counts = Counter(summarize_error_message(msg) for msg in self.failed_errors.values())
            items = [
                {"message": message, "count": count}
                for message, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            ]
        elif self.last_error and self.failed > 0 and not is_status_only_message(self.last_error):
            # Legacy fallback: never treat stop/budget notices as per-item failure reasons.
            items = [{"message": summarize_error_message(self.last_error), "count": self.failed}]

        # Pipeline-level errors (research/export) must surface even when per-item failed=0.
        if self.last_error and (
            self.last_error.startswith("研究阶段") or self.last_error.startswith("自动导出失败")
        ):
            pipeline_msg = summarize_error_message(self.last_error)
            if not any((item.get("message") or "") == pipeline_msg for item in items):
                items.insert(0, {"message": pipeline_msg, "count": 1})
        return items
