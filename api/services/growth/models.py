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

from pydantic import BaseModel, Field, field_validator




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
    is_demo: bool = False  # 演示产品：写入自动标 demo，与正式决策隔离
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
    # 两种模式：asset_ready=已有授权素材可承接；demand_first=素材库没有，
    # 属「待制作机会」，只能指导内部制作方向，不得声称可直接发布。
    opportunity_kind: Literal["asset_ready", "demand_first"] = "asset_ready"
    production_need: str = ""  # demand_first：应制作什么（题材/形式/要点）
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
    created_by_session: str = ""  # 任务归属（创建它的会话）
    data_nature: Literal["real", "demo", "mock"] = "real"  # mock 不进正式决策
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
    value: Optional[float] = None  # None = Unknown（未获取），禁止用 0 冒充
    unit: str = ""
    channel: str = ""
    source: str = "manual_import"  # manual_import / platform_export / event_api
    period_start: str = ""  # 统计区间开始
    period_end: str = ""    # 统计区间结束
    stats_method: str = ""  # 统计口径说明
    attribution_note: str = ""  # 归因限制
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
    brief_id: str = ""  # 由已批准任务书创建时记录
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


# --- content brief（内容任务书） --------------------------------------------


class BriefStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"  # 人工批准后才可以建实验/分发
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ContentBrief(BaseModel):
    """可直接交给内部内容人员执行的任务书。每个字段都要可解释，禁止拼凑。"""

    brief_id: str
    product_id: str
    opportunity_id: str = ""
    title: str = ""
    audience: str = ""          # 面向什么用户
    problem: str = ""           # 解决什么问题
    asset_ids: List[str] = Field(default_factory=list)  # 使用哪份真实素材
    rationale: str = ""         # 为什么推荐它（含证据引用）
    evidence_refs: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)  # 适合什么渠道
    hook: str = ""              # 推荐怎样开头（前几秒/首句）
    value_props: List[str] = Field(default_factory=list)  # 应突出什么产品价值
    visit_reason: str = ""      # 用户为什么要访问产品站
    review_requirements: str = ""  # 需要怎样的审核与素材准备
    validation_metrics: List[str] = Field(default_factory=list)  # 什么指标验证有效性
    priority: int = 0           # 1 最高
    status: BriefStatus = BriefStatus.DRAFT
    review_note: str = ""       # 人工审批备注/拒绝原因
    created_by: str = "agent"
    created_by_session: str = ""  # 任务归属
    data_nature: Literal["real", "demo", "mock"] = "real"
    created_at: str = ""
    updated_at: str = ""


# --- user segment research（潜在用户研究） -------------------------------------


class SegmentCertainty(str, Enum):
    EVIDENCED = "evidenced"        # 有证据支持的用户需求
    INFERRED = "inferred"          # 推断出的潜在群体
    UNVERIFIED = "unverified"      # 缺少验证的画像


class ProductFitLevel(str, Enum):
    MATCHED = "matched"
    WEAK = "weak"
    MISMATCH = "mismatch"


_FIT_SYNONYMS = {
    "high": "matched", "strong": "matched", "match": "matched", "good": "matched", "高": "matched",
    "medium": "weak", "mid": "weak", "partial": "weak", "moderate": "weak", "中": "weak", "一般": "weak",
    "low": "mismatch", "none": "mismatch", "poor": "mismatch", "no": "mismatch", "低": "mismatch", "不匹配": "mismatch",
    "unverified": "weak", "unknown": "weak", "clear": "weak", "unclear": "weak",
}

_CERTAINTY_SYNONYMS = {
    "fact": "evidenced", "proven": "evidenced", "confirmed": "evidenced", "high": "evidenced",
    "hypothesis": "inferred", "inference": "inferred", "likely": "inferred", "medium": "inferred",
    "guess": "unverified", "unknown": "unverified", "low": "unverified", "assumed": "unverified",
}


class UserSegment(BaseModel):
    name: str = ""
    core_needs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)  # 必须可解析（signal/record id）
    platforms: List[str] = Field(default_factory=list)  # 真实可确认的出现平台（来自数据）
    product_fit: ProductFitLevel = ProductFitLevel.WEAK
    product_fit_reason: str = ""
    reach_methods: List[str] = Field(default_factory=list)  # 合规触达方式
    hypothesized_channels: List[str] = Field(default_factory=list)  # 推测渠道（单列，不得混为已确认）
    certainty: SegmentCertainty = SegmentCertainty.UNVERIFIED

    @field_validator("product_fit", mode="before")
    @classmethod
    def _coerce_fit(cls, v):
        if isinstance(v, str):
            return _FIT_SYNONYMS.get(v.strip().lower(), v)
        return v

    @field_validator("certainty", mode="before")
    @classmethod
    def _coerce_certainty(cls, v):
        if isinstance(v, str):
            return _CERTAINTY_SYNONYMS.get(v.strip().lower(), v)
        return v


class UserSegmentReport(BaseModel):
    """潜在用户研究报告：区别于内容机会，禁止声称已确认全部目标用户。"""

    report_id: str
    product_id: str
    goal: str = ""
    segments: List[UserSegment] = Field(default_factory=list)
    data_limitations: str = ""  # 数据边界（如：仅两个视频的评论区，代理受众，不能代表全部目标用户）
    recommended_next: List[str] = Field(default_factory=list)
    not_recommended: List[str] = Field(default_factory=list)  # 明确不建议当作目标的群体（允许否定结论）
    created_by: str = "agent"
    created_by_session: str = ""
    data_nature: Literal["real", "demo", "mock"] = "real"
    created_at: str = ""


# --- learning & decision memory ---------------------------------------------


class LearningRecord(BaseModel):
    """结构化增长经验——实验结束或人工反馈后写入，供后续规划检索。"""

    learning_id: str
    product_id: str
    experiment_id: str = ""
    # 数据性质：mock 演示记录不进入正式策略检索（recall_learnings 默认排除）
    data_nature: Literal["real", "demo", "mock"] = "real"
    created_by_session: str = ""
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
