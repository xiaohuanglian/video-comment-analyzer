# -*- coding: utf-8 -*-
"""B2 acceptance tests after blind-review fixes."""

from __future__ import annotations

from api.services.insight.evidence_extractor import (
    extract_evidence_card_mock,
    extract_batch_with_split,
    sanitize_evidence_card,
)
from api.services.insight.evidence_schemas import (
    ContentEngagementType,
    EvidenceCard,
    EvidenceLevel,
    PrimaryExpression,
    RecordStatus,
    TrainingBehaviorType,
    normalize_record_status,
)
from api.services.insight.schemas import SourceRecord


def _rec(rid: str, text: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="t.csv",
        source_row_number=1,
        comment_text=text,
    )


def test_record_status_not_invalid_for_thanks_and_save():
    thanks = extract_evidence_card_mock(_rec("t1", "谢谢教练"))
    save = extract_evidence_card_mock(_rec("t2", "收藏退出一气呵成"))
    assert thanks.record_status == RecordStatus.USABLE
    assert save.record_status == RecordStatus.USABLE
    assert thanks.evidence_level in {EvidenceLevel.WEAK, EvidenceLevel.MEDIUM, EvidenceLevel.STRONG}


def test_spam_and_empty_excluded():
    empty = extract_evidence_card_mock(_rec("e", "  "))
    spam = extract_evidence_card_mock(_rec("s", "加微信免费领取 http://x.y"))
    assert empty.record_status == RecordStatus.GARBLED
    assert spam.record_status == RecordStatus.SPAM


def test_checkin_is_content_engagement_not_continued_training():
    card = extract_evidence_card_mock(_rec("c", "打卡"))
    assert any(e.type == ContentEngagementType.CHECKED_IN for e in card.content_engagement)
    assert not any(t.type == TrainingBehaviorType.CONTINUED for t in card.training_behavior)


def test_self_reported_ability_not_planned():
    card = extract_evidence_card_mock(_rec("a", "我可以挨着墙倒立"))
    assert any(t.type == TrainingBehaviorType.SELF_REPORTED_ABILITY for t in card.training_behavior)
    assert not any(t.type == TrainingBehaviorType.PLANNED for t in card.training_behavior)


def test_sanitize_drops_empty_quotes():
    record = _rec("q", "我练了三天")
    card = EvidenceCard(
        record_id="q",
        record_status=RecordStatus.USABLE,
        explicit_facts=[{"fact": "练了", "evidence_quote": ""}],
        training_behavior=[
            {
                "type": "attempted",
                "text": "已练",
                "evidence_quote": "我练了三天",
                "certainty": "explicit",
            }
        ],
        problem_or_need=[{"text": "x", "evidence_quote": "不存在的话"}],
    )
    cleaned = sanitize_evidence_card(record, card)
    assert cleaned.explicit_facts == []
    assert cleaned.problem_or_need == []
    assert len(cleaned.training_behavior) == 1
    assert cleaned.training_behavior[0].evidence_quote == "我练了三天"


def test_compound_question_and_praise():
    card = extract_evidence_card_mock(_rec("c1", "谢谢教练，臀桥酸正常吗？"))
    assert card.primary_expression == PrimaryExpression.QUESTION
    assert card.record_status == RecordStatus.USABLE
    assert card.explicit_facts or card.problem_or_need


def test_legacy_card_bridge_from_validity():
    card = EvidenceCard(record_id="x", validity="invalid")
    assert card.record_status == RecordStatus.SPAM
    assert normalize_record_status("low_information_but_valid") == RecordStatus.USABLE


def test_quantitative_evidence_when_numbers_present():
    card = extract_evidence_card_mock(_rec("n", "两个就不行了，现在25个没什么问题"))
    assert card.quantitative_evidence
    assert all(q.evidence_quote for q in card.quantitative_evidence)


def test_batch_still_aligns():
    records = [_rec(f"id{i}", f"这个动作怎么做{i}？") for i in range(10)]
    result = extract_batch_with_split(records, use_mock=True, batch_size=10)
    assert result.stats.failed == 0
    assert len(result.cards) == 10
    assert all(c.record_status == RecordStatus.USABLE for c in result.cards)
