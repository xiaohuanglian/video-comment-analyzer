# -*- coding: utf-8 -*-
"""B3 acceptance tests after round-2 blind-review P0 fixes."""

from __future__ import annotations

from api.services.insight.evidence_extractor import (
    align_evidence_level,
    evidence_item_count,
    extract_evidence_card_mock,
    sanitize_evidence_card,
)
from api.services.insight.evidence_schemas import (
    EvidenceCard,
    EvidenceLevel,
    RecordStatus,
    TrainingBehaviorType,
    EVIDENCE_PROMPT_VERSION,
)
from api.services.insight.schemas import SourceRecord


def _rec(rid: str, text: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="t.csv",
        source_row_number=1,
        comment_text=text,
    )


def test_prompt_version_b3():
    assert EVIDENCE_PROMPT_VERSION == "evidence_extract_v9_compact"


def test_meaningful_empty_downgrades():
    record = _rec("m1", "引体差两个左右，倒立做不来，其他的已经超标了")
    card = EvidenceCard(
        record_id="m1",
        record_status=RecordStatus.USABLE,
        evidence_level=EvidenceLevel.STRONG,
        evidence_items=[],
        explicit_facts=[],
        problem_or_need=[],
        training_behavior=[],
    )
    cleaned = sanitize_evidence_card(record, card)
    assert evidence_item_count(cleaned) == 0
    assert cleaned.evidence_level in {EvidenceLevel.WEAK, EvidenceLevel.NONE}


def test_level_aligns_up_when_problem_present():
    record = _rec("m2", "请问跳跃引体和跳跃离心引体有什么区别")
    card = EvidenceCard(
        record_id="m2",
        record_status=RecordStatus.USABLE,
        evidence_level=EvidenceLevel.WEAK,
        problem_or_need=[{"text": "问动作区别", "evidence_quote": "有什么区别"}],
    )
    cleaned = sanitize_evidence_card(record, card)
    assert cleaned.evidence_level in {EvidenceLevel.MEDIUM, EvidenceLevel.STRONG}


def test_completed_once_behavior_recall():
    card = extract_evidence_card_mock(_rec("b1", "刚做完一百个俯卧撑，又是不咸鱼的一天"))
    assert any(t.type == TrainingBehaviorType.COMPLETED_ONCE for t in card.training_behavior)
    assert evidence_item_count(card) > 0
    assert card.evidence_level in {EvidenceLevel.MEDIUM, EvidenceLevel.STRONG}


def test_action_gap_field():
    card = extract_evidence_card_mock(_rec("g1", "收藏永不停止，锻炼从不开始"))
    assert card.action_gap
    assert all(g.evidence_quote for g in card.action_gap)
    assert card.content_engagement


def test_day3_checkin_and_continued():
    card = extract_evidence_card_mock(_rec("d1", "Day3"))
    assert card.content_engagement or card.training_behavior
    assert evidence_item_count(card) > 0


def test_machine_generated_status():
    text = "一、初学者……\n--本内容由AI视频小助理生成，关注解锁AI助理"
    card = extract_evidence_card_mock(_rec("ai1", text))
    assert card.record_status == RecordStatus.MACHINE_GENERATED
    assert card.evidence_level == EvidenceLevel.NONE


def test_off_topic_not_spam():
    card = extract_evidence_card_mock(_rec("o1", "脖子这样的纹身显得修长，女的腿部纹了一定修长美腿了。"))
    assert card.record_status == RecordStatus.OFF_TOPIC
    assert card.record_status != RecordStatus.SPAM


def test_paid_help_and_quant():
    card = extract_evidence_card_mock(
        _rec("p1", "距离我在健身房办卡已经7个多月了，我的身材没有一点改变")
    )
    assert any(t.type == TrainingBehaviorType.SOUGHT_PAID_HELP for t in card.training_behavior)
    assert card.quantitative_evidence or card.problem_or_need


def test_align_strong_when_quant_and_behavior():
    record = _rec("q1", "我刚刚试了试，一组20个")
    card = EvidenceCard(
        record_id="q1",
        record_status=RecordStatus.USABLE,
        evidence_level=EvidenceLevel.WEAK,
        training_behavior=[
            {
                "type": "attempted",
                "text": "刚试",
                "evidence_quote": "我刚刚试了试",
                "certainty": "explicit",
            }
        ],
        quantitative_evidence=[
            {"metric": "次数", "value_text": "20个", "evidence_quote": "一组20个"}
        ],
    )
    cleaned = align_evidence_level(sanitize_evidence_card(record, card))
    assert cleaned.evidence_level == EvidenceLevel.STRONG
