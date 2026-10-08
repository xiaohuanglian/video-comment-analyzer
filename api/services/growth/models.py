# -*- coding: utf-8 -*-
"""Growth domain data models (Phase 1).

Everything here is product-scoped: two products never share a record id.
AI reasoning is never stored as business fact — only structured outputs,
evidence references and action records are persisted.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- product profile ---------------------------------------------------------


class AttributionCapability(str, Enum):
    NONE = "none"  # 站外表现可见，站内转化不可验证
    URL_TRACKING = "url_tracking"  # 可追踪点击 / 到站访问
    EVENT_API = "event_api"  # 注册/首次核心行为等真实埋点


class ProductProfile(BaseModel):
    product_id: str
    name: str
    domain: str = ""
    growth_goal: str = ""
    target_audience: str = ""
    value_props: List[str] = Field(default_factory=list)
    positioning_status: str = ""  # e.g. "未验证定位，优先探索内容-用户匹配"
    forbidden_claims: str = ""
    attribution_capability: AttributionCapability = AttributionCapability.NONE
    distribution_accounts: List[Dict[str, str]] = Field(default_factory=list)
    # Link to the insight-layer project profile (intents/signals taxonomy).
    insight_profile_id: str = "default"
    data_rights: str = ""  # 素材/数据使用边界说明
    is_builtin: bool = False
    created_at: str = ""
    updated_at: str = ""


# --- unified signal ----------------------------------------------------------


class SignalSourceType(str, Enum):
    EXTERNAL_COMMENT = "external_comment"
    USER_QUESTION = "user_question"
    CONTENT_PERFORMANCE = "content_performance"
    PRODUCT_FEEDBACK = "product_feedback"
    BEHAVIOR_EVENT = "behavior_event"
    EXPERIMENT_RESULT = "experiment_result"


class EvidenceQuality(str, Enum):
    HIGH = "high"  # 原始记录可直接回溯
    MEDIUM = "medium"  # 已脱敏/聚合，可回溯到批次
    LOW = "low"  # 二手转述或样本极少


class Signal(BaseModel):
    signal_id: str
    product_id: str
    source_type: SignalSourceType
    source_platform: str = ""  # bilibili / xiaohongshu / in_app / ...
    dataset_ref: str = ""  # 来源数据集（run_id / 文件名 / 导入批次）
    evidence_refs: List[str] = Field(default_factory=list)  # 原始记录 ID / 引用
    collected_at: str = ""
    signal_type: str = ""  # 业务信号 key（对齐 insight profile taxonomy，可为新信号）
    need_or_problem: str = ""  # 用户表达的需求或问题（归一化表述）
    product_area: str = ""  # 关联的产品场景/功能
    ai_classification: Dict[str, Any] = Field(default_factory=dict)  # intent/signals/置信度等
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quality: EvidenceQuality = EvidenceQuality.MEDIUM
    usage_rights: str = "internal_only"  # internal_only / deidentified_ok / public_ok
    raw_excerpt_hash: str = ""  # 敏感原文不落地，只留哈希；公开来源可留原文于 evidence_refs


# --- content asset -----------------------------------------------------------


class LicenseStatus(str, Enum):
    OWNED = "owned"  # 内部原创
    LICENSED = "licensed"  # 已获授权
    UNKNOWN = "unknown"  # 未确认，禁止对外使用


class ContentAsset(BaseModel):
    asset_id: str
    product_id: str
    title: str
    summary: str = ""
    uri: str = ""  # 链接或本地文件路径
    asset_type: str = "video"  # video/image/article/mixed
    topics: List[str] = Field(default_factory=list)
    target_audience: str = ""
    highlights: str = ""  # 内容展示重点
    landing_page: str = ""  # 对应站内落地页
    license_status: LicenseStatus = LicenseStatus.UNKNOWN
    published_channels: List[str] = Field(default_factory=list)
    linked_metrics: List[str] = Field(default_factory=list)  # MetricsObservation ids
    created_at: str = ""


# --- growth opportunity ------------------------------------------------------


class OpportunityVerdict(str, Enum):
    RECOMMEND = "recommend"
    HOLD = "hold"  # 证据不足，暂缓
    REJECT = "reject"  # 明确不建议行动
    NEEDS_DATA = "needs_data"  # 提出但需先补数据


class GrowthOpportunity(BaseModel):
    opportunity_id: str
    product_id: str
    target_segment: str = ""
    problem: str = ""
    evidence_refs: List[str] = Field(default_factory=list)  # signal/asset/observation ids
    linked_value: str = ""  # 关联的产品价值
    growth_mechanism: str = ""  # 预期增长机制（搜索获客/教程导流/...）
    usable_assets: List[str] = Field(default_factory=list)  # asset ids
    recommended_action: str = ""
    cost_estimate: str = ""  # 自由文本（人力/制作成本量级）
    risks: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertainty_level: Literal["fact", "inference", "hypothesis", "guess"] = "hypothesis"
    verdict: OpportunityVerdict = OpportunityVerdict.HOLD
    verdict_rationale: str = ""  # 为什么推荐/不建议（禁止只有分数）
    metrics_to_verify: List[str] = Field(default_factory=list)  # 待验证指标
    status: Literal["open", "accepted", "rejected", "converted"] = "open"
    created_by: str = "agent"  # agent / human
    created_at: str = ""


# --- growth experiment & metrics --------------------------------------------


class MetricKind(str, Enum):
    REACH = "reach"  # 曝光/播放/完播/点赞/收藏/评论
    TRAFFIC = "traffic"  # 可追踪点击 / 有效到站访问
    PRODUCT = "product"  # 注册/首次核心行为/留存（仅真实数据）
    EFFICIENCY = "efficiency"  # 制作成本 / 有效获客成本（仅归因充分时）


class MetricsObservation(BaseModel):
    observation_id: str
    product_id: str
    experiment_id: str = ""
    asset_id: str = ""
    metric_kind: MetricKind
    name: str  # views / likes / tracked_clicks / valid_visits / signups ...
    value: float = 0.0
    unit: str = ""
    channel: str = ""
    source: str = "manual_import"  # manual_import / platform_export / event_api
    verified: bool = False  # 是否来自可核验数据源（而非人工估算）
    collected_at: str = ""


class PublishRecord(BaseModel):
    channel: str
    account: str = ""
    url: str = ""
    published_at: str = ""
    variant_id: str = ""


class ExperimentStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    ANALYZING = "analyzing"
    CONCLUDED = "concluded"
    STOPPED = "stopped"


class GrowthExperiment(BaseModel):
    experiment_id: str
    product_id: str
    opportunity_id: str = ""
    goal: str = ""
    audience: str = ""
    hypothesis: str = ""
    asset_ids: List[str] = Field(default_factory=list)
    content_variants: List[Dict[str, Any]] = Field(default_factory=list)  # 版本差异描述/任务书引用
    channels: List[str] = Field(default_factory=list)
    publish_records: List[PublishRecord] = Field(default_factory=list)
    target_metrics: List[str] = Field(default_factory=list)
    attribution_limits: str = ""  # 归因能力与限制
    comparison_notes: str = ""  # 渠道/发布时间/受众/样本差异记录
    status: ExperimentStatus = ExperimentStatus.PLANNED
    conclusion: str = ""
    next_actions: List[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


# --- learning & decision memory ---------------------------------------------


class LearningRecord(BaseModel):
    """结构化增长经验——实验结束或人工反馈后写入，供后续规划检索。"""

    learning_id: str
    product_id: str
    experiment_id: str = ""
    what_tested: str = ""
    outcome: str = ""
    evidence_strength: Literal["strong", "moderate", "weak", "insufficient"] = "insufficient"
    supported_hypotheses: List[str] = Field(default_factory=list)
    rejected_hypotheses: List[str] = Field(default_factory=list)
    remaining_uncertainties: List[str] = Field(default_factory=list)
    next_adjustments: List[str] = Field(default_factory=list)
    # 人工反馈：verdict=accepted/rejected/modified，reason 必填；是可推翻的经验而非铁律。
    human_feedback: Optional[Dict[str, str]] = None
    created_at: str = ""


class AuditRecord(BaseModel):
    """每一次 Agent / 工具动作的可追溯记录。"""

    audit_id: str
    product_id: str
    session_id: str = ""
    actor: str = "agent"  # agent / system / human
    action: str = ""  # tool 名或系统动作
    input_summary: str = ""
    output_refs: List[str] = Field(default_factory=list)  # 产出记录的 id
    permission_level: str = "L1"
    status: Literal["ok", "denied", "error"] = "ok"
    detail: str = ""
    cost_cny: float = 0.0
    created_at: str = ""
