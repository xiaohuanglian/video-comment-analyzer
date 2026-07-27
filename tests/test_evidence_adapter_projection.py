# -*- coding: utf-8 -*-
"""Rule-based projections from evidence cards to legacy analysis fields."""

from __future__ import annotations

from api.services.insight.evidence_adapter import (
    derive_new_signals_from_card,
    infer_single_video_relation,
    infer_training_evidence,
    outreach_analysis_from_card,
)
from api.services.insight.schemas import CommentAnalysisResult
from api.services.insight.evidence_schemas import (
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    ItemCertainty,
    PrimaryExpression,
    RecordStatus,
    SpeakerScope,
)


def _card(**kwargs) -> EvidenceCard:
    return EvidenceCard.model_validate(kwargs)


def test_infer_single_video_relation_for_direction_judgment():
    card = _card(
        record_id="r1",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.HELP_REQUEST,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.PROBLEM,
                text="无法判断旋转方向",
                evidence_quote="无法判断骨盆是左旋还是右旋",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
            )
        ],
    )
    assert infer_single_video_relation(card) == "personalized_judgment_needed"


def test_infer_single_video_relation_for_realtime_form_check():
    card = _card(
        record_id="r2",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.HELP_REQUEST,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.PROBLEM,
                text="怀疑动作不标准",
                evidence_quote="不知道是不是我动作不标准",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.MEDIUM,
            )
        ],
    )
    assert infer_single_video_relation(card) == "realtime_observation_needed"


def test_infer_single_video_relation_for_positive_result():
    card = _card(
        record_id="r3",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.RESULT_FEEDBACK,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.RESULT,
                text="立竿见影",
                evidence_quote="立竿见影",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
            )
        ],
    )
    assert infer_single_video_relation(card) == "video_sufficient"


def test_infer_training_evidence_from_ongoing_period():
    card = _card(
        record_id="r4",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.RESULT_FEEDBACK,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.BEHAVIOR,
                text="已锻炼一星期",
                evidence_quote="这个视频里的动作我已经锻炼一个星期了",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
                subtype="ongoing_period",
            )
        ],
    )
    assert infer_training_evidence(card) == "continued"
    projected = outreach_analysis_from_card(card)
    assert projected["actual_training_evidence"] == "continued"


def test_infer_legacy_signals_from_problem_and_behavior():
    card = _card(
        record_id="r5",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.HELP_REQUEST,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.PROBLEM,
                text="动作是否标准",
                evidence_quote="不知道是不是我动作不标准",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
            ),
            EvidenceItem(
                type=EvidenceItemType.BEHAVIOR,
                text="已尝试训练",
                evidence_quote="我试了一下",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
                subtype="attempted",
            ),
        ],
    )
    projected = outreach_analysis_from_card(card)
    assert "form_uncertainty" in projected["signals"]
    assert "started_training" in projected["signals"]


def test_derive_new_signals_uses_valid_enum_types():
    card = _card(
        record_id="r6",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.HELP_REQUEST,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.PROBLEM,
                text="膝盖疼",
                evidence_quote="练完膝盖疼",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
            ),
            EvidenceItem(
                type=EvidenceItemType.CONTEXT,
                text="产后恢复",
                evidence_quote="产后三个月",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.MEDIUM,
            ),
            EvidenceItem(
                type=EvidenceItemType.SOLUTION,
                text="自己搜教程",
                evidence_quote="我自己去搜了别的教程",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.MEDIUM,
            ),
        ],
    )
    payload = derive_new_signals_from_card(card)
    analysis = CommentAnalysisResult.model_validate(
        {
            "record_id": "r6",
            "primary_intent": "question",
            "new_signals": payload,
        }
    )
    types = {signal.type.value for signal in analysis.new_signals}
    assert types == {"new_problem", "new_user_segment", "new_current_solution"}
