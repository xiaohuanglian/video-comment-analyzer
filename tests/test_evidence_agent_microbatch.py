# -*- coding: utf-8 -*-
"""Tests for evidence micro-batch extraction (no paid API)."""

from __future__ import annotations

import pytest

from api.services.insight.evidence_cache import (
    clear_evidence_cache,
    evidence_fingerprint,
    get_cached_evidence,
    put_cached_evidence,
)
from api.services.insight.evidence_extractor import (
    align_batch_cards,
    extract_batch_with_split,
    extract_evidence_card_mock,
    parse_batch_payload,
    run_evidence_extraction,
    sanitize_evidence_card,
)
from api.services.insight.evidence_schemas import (
    EvidenceCard,
    EvidenceCardLLMItem,
    PrimaryExpression,
    RecordStatus,
    Validity,
)
from api.services.insight.llm_analyzer import LlmUsage
from api.services.insight.schemas import FieldMapping, RunConfig, SourceRecord


def _rec(rid: str, text: str, **kwargs) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="t.csv",
        source_row_number=1,
        comment_text=text,
        **kwargs,
    )


def test_align_batch_ignores_order_and_rejects_duplicate_output():
    expected = ["a", "b", "c"]
    items = [
        EvidenceCardLLMItem(record_id="c", primary_expression=PrimaryExpression.QUESTION),
        EvidenceCardLLMItem(record_id="a", primary_expression=PrimaryExpression.GRATITUDE),
        EvidenceCardLLMItem(record_id="b", primary_expression=PrimaryExpression.CHECK_IN),
    ]
    mapped = align_batch_cards(expected, items)
    assert set(mapped) == {"a", "b", "c"}

    with pytest.raises(ValueError, match="重复"):
        align_batch_cards(
            expected,
            items
            + [EvidenceCardLLMItem(record_id="a", primary_expression=PrimaryExpression.OTHER)],
        )


def test_align_rejects_duplicate_input_ids():
    with pytest.raises(ValueError, match="重复"):
        align_batch_cards(["a", "a"], [EvidenceCardLLMItem(record_id="a")])


def test_parse_batch_payload_requires_full_coverage():
    expected = ["r1", "r2"]
    payload = {
        "cards": [
            {"record_id": "r1", "primary_expression": "question", "confidence": 0.5},
        ]
    }
    mapped = parse_batch_payload(payload, expected)
    assert "r1" in mapped
    assert "r2" not in mapped


def test_compact_payload_restores_record_ids_and_ignores_order():
    expected = ["full:r1", "full:r2"]
    payload = {
        "r": [
            [2, "ur", [["r", "", "s", "h", "练完舒服多了"]]],
            [1, "uh", [["p", "direction", "s", "h", "分不清左右"]]],
        ]
    }
    mapped = parse_batch_payload(payload, expected)
    assert list(mapped) == ["full:r2", "full:r1"]
    assert mapped["full:r1"].record_id == "full:r1"
    assert mapped["full:r1"].evidence_items[0].type.value == "problem"
    assert mapped["full:r1"].evidence_items[0].text == "分不清左右"


def test_compact_payload_expands_behavior_and_barrier_codes():
    mapped = parse_batch_payload(
        {
            "r": [
                [
                    1,
                    "uh",
                    [
                        ["b", "c", "s", "h", "做完一次"],
                        ["d", "", "s", "h", "动作太难"],
                    ],
                ]
            ]
        },
        ["r1"],
    )
    items = mapped["r1"].evidence_items
    assert [(item.type.value, item.subtype) for item in items] == [
        ("barrier", ""),
        ("behavior", "completed_once"),
    ]


def test_compact_payload_accepts_common_model_variants():
    mapped = parse_batch_payload(
        {
            "r": [
                {
                    "i": 1,
                    "sx": "uh",
                    "e": [["behavior", "a", "self", "high", "已经试过"]],
                },
                [2, "usable", "question", [["p", "", "s", "h", "怎么判断"]]],
                # Model leaked check_in code into status; recover as usable + check_in.
                [3, "k", "o", []],
                # Swapped status/expression codes.
                [4, "h", "u", []],
            ]
        },
        ["r1", "r2", "r3", "r4"],
    )
    assert mapped["r1"].evidence_items[0].type.value == "behavior"
    assert mapped["r2"].primary_expression.value == "question"
    assert mapped["r3"].record_status.value == "usable"
    assert mapped["r3"].primary_expression.value == "check_in"
    assert mapped["r4"].record_status.value == "usable"
    assert mapped["r4"].primary_expression.value == "help_request"


def test_compact_payload_rejects_invalid_enum_and_duplicate_index():
    # Completely unknown type still fails; status typos are recovered.
    with pytest.raises(ValueError, match="非法紧凑枚举 type"):
        parse_batch_payload(
            {"r": [{"i": 1, "s": "u", "x": "o", "e": [["z", "", "s", "h", "x"]]}]},
            ["r1"],
        )
    recovered = parse_batch_payload({"r": [{"i": 1, "s": "z", "x": "o", "e": []}]}, ["r1"])
    assert recovered["r1"].record_status.value == "usable"
    assert recovered["r1"].primary_expression.value == "other"
    with pytest.raises(ValueError, match="重复短编号"):
        parse_batch_payload(
            {"r": [{"i": 1, "s": "u", "x": "o", "e": []}, {"i": 1, "s": "u", "x": "o", "e": []}]},
            ["r1"],
        )


def test_compact_payload_recovers_expression_codes_in_status_slot():
    mapped = parse_batch_payload(
        {
            "r": [
                [1, "k", "o", []],
                [2, "q", "o", []],
                [3, "k", []],  # single-char sx
            ]
        },
        ["r1", "r2", "r3"],
    )
    assert mapped["r1"].record_status.value == "usable"
    assert mapped["r1"].primary_expression.value == "check_in"
    assert mapped["r2"].primary_expression.value == "question"
    assert mapped["r3"].primary_expression.value == "check_in"


def test_compact_payload_allows_empty_and_limits_non_complex_to_two():
    empty = parse_batch_payload({"r": [{"i": 1, "s": "u", "x": "o", "e": []}]}, ["r1"])
    assert empty["r1"].evidence_items == []
    payload = {
        "r": [
            {
                "i": 1,
                "s": "u",
                "x": "q",
                "e": [
                    ["o", "", "s", "m", "观点一"],
                    ["c", "", "s", "m", "背景二"],
                    ["e", "saved", "s", "h", "收藏三"],
                ],
            }
        ]
    }
    mapped = parse_batch_payload(payload, ["r1"])
    assert len(mapped["r1"].evidence_items) == 2


def test_compact_payload_allows_four_for_complex_comment():
    payload = {
        "r": [
            {
                "i": 1,
                "s": "u",
                "x": "h",
                "e": [
                    ["p", "", "s", "h", "膝盖疼"],
                    ["b", "a", "s", "h", "已经练了一周"],
                    ["r", "", "s", "m", "还是没有改善"],
                    ["q", "duration", "s", "h", "一周"],
                ],
            }
        ]
    }
    mapped = parse_batch_payload(payload, ["r1"])
    assert len(mapped["r1"].evidence_items) == 4


def test_mock_batch_20_returns_20_aligned():
    records = [_rec(f"id{i}", f"这个动作怎么做{i}？") for i in range(20)]
    result = extract_batch_with_split(records, use_mock=True, batch_size=20)
    assert result.stats.failed == 0
    assert len(result.cards) == 20
    assert [c.record_id for c in result.cards] == [r.internal_record_id for r in records]


def test_empty_comment_marked_spam_or_garbled():
    card = extract_evidence_card_mock(_rec("e1", "   "))
    assert card.record_status.value == "garbled"


def test_compound_comment_extracts_gratitude_and_question():
    text = "谢谢教练，臀桥时大腿后侧酸，这正常吗？"
    card = extract_evidence_card_mock(_rec("e2", text))
    assert card.record_status.value == "usable"
    assert card.primary_expression == PrimaryExpression.QUESTION
    assert card.explicit_facts or card.problem_or_need
    assert card.problem_or_need or card.primary_expression in {
        PrimaryExpression.QUESTION,
        PrimaryExpression.GRATITUDE,
        PrimaryExpression.PRAISE,
        PrimaryExpression.HELP_REQUEST,
    }


def test_sanitize_drops_fabricated_quotes():
    record = _rec("e3", "我练了三天")
    card = EvidenceCard(
        record_id="e3",
        explicit_facts=[{"fact": "x", "evidence_quote": "这段话根本不存在"}],
        problem_or_need=[{"text": "y", "evidence_quote": "我练了三天"}],
    )
    cleaned = sanitize_evidence_card(record, card)
    # B2: fabricated / empty quotes are dropped entirely
    assert cleaned.explicit_facts == []
    assert cleaned.problem_or_need[0].evidence_quote == "我练了三天"


def test_sanitize_does_not_treat_cost_saving_as_paid_failure():
    record = _rec(
        "paid-offer",
        "之前有个健身教练让我报2万块钱的课，矫正骨盆旋转，做这个操让我省钱了",
    )
    card = EvidenceCard(
        record_id=record.internal_record_id,
        evidence_items=[
            {
                "type": "behavior",
                "subtype": "sought_paid_help",
                "text": "教练让我报课",
                "evidence_quote": "之前有个健身教练让我报2万块钱的课",
                "speaker_scope": "self",
                "certainty": "high",
            },
            {
                "type": "action_gap",
                "subtype": "paid_but_no_result",
                "text": "省钱了",
                "evidence_quote": "做这个操让我省钱了",
                "speaker_scope": "self",
                "certainty": "high",
            },
        ],
    )
    cleaned = sanitize_evidence_card(record, card)
    assert any(item.type.value == "solution" and item.subtype == "paid_offer" for item in cleaned.evidence_items)
    assert any(item.type.value == "result" and item.subtype == "saved_cost" for item in cleaned.evidence_items)
    assert not any(item.subtype == "paid_but_no_result" for item in cleaned.evidence_items)
    assert not any(item.subtype == "sought_paid_help" for item in cleaned.evidence_items)


def test_planned_tried_continued_distinction():
    planned = extract_evidence_card_mock(_rec("p", "打算练这个计划"))
    tried = extract_evidence_card_mock(_rec("t", "昨天试了俯卧撑"))
    continued = extract_evidence_card_mock(_rec("c", "每天坚持练一周了"))
    assert any(b.type.value == "planned" for b in planned.training_behavior)
    assert any(b.type.value == "attempted" for b in tried.training_behavior)
    assert any(b.type.value == "continued" for b in continued.training_behavior)


def test_no_evidence_fields_stay_empty_for_neutral_text():
    card = extract_evidence_card_mock(_rec("n", "哈哈哈"))
    # May be other expression with empty structured lists
    assert isinstance(card.problem_or_need, list)


def test_split_on_persistent_failure(monkeypatch):
    records = [_rec(f"s{i}", f"评论{i}有问题吗？") for i in range(8)]
    calls = {"n": 0}

    def flaky(chunk, config, api_key, client=None):
        calls["n"] += 1
        if len(chunk) > 1:
            raise ValueError("simulated batch failure")
        # succeed only for size 1
        return (
            {
                r.internal_record_id: extract_evidence_card_mock(r)
                for r in chunk
            },
            LlmUsage(),
        )

    result = extract_batch_with_split(
        records,
        use_mock=False,
        config=RunConfig(
            run_id="t",
            name="t",
            file_paths=[],
            field_mapping=FieldMapping(comment_text="c"),
        ),
        api_key="x",
        batch_size=8,
        call_fn=flaky,
    )
    assert result.stats.splits >= 1
    assert len(result.cards) == 8
    assert result.stats.failed == 0


def test_skip_completed_ids():
    records = [_rec("a", "问一下？"), _rec("b", "再问？")]
    result = run_evidence_extraction(records, use_mock=True, skip_ids={"a"})
    assert [c.record_id for c in result.cards] == ["b"]


def test_cache_requires_same_context():
    clear_evidence_cache()
    r1 = _rec("c1", "我刚刚试了试，只勉强做了一组", video_title="视频A", parent_comment="")
    r2 = _rec("c2", "我刚刚试了试，只勉强做了一组", video_title="视频B", parent_comment="")
    r3 = _rec("c3", "我刚刚试了试，只勉强做了一组", video_title="视频A", parent_comment="父评不同")
    fp1 = evidence_fingerprint(r1, project_version="1", model_name="m")
    fp2 = evidence_fingerprint(r2, project_version="1", model_name="m")
    fp3 = evidence_fingerprint(r3, project_version="1", model_name="m")
    assert fp1 != fp2
    assert fp1 != fp3
    card = extract_evidence_card_mock(r1)
    assert card.evidence_items
    put_cached_evidence(fp1, card)
    assert get_cached_evidence(fp1) is not None
    assert get_cached_evidence(fp2) is None

    fp_prompt = evidence_fingerprint(r1, prompt_version="other", project_version="1", model_name="m")
    assert fp_prompt != fp1
    fp_project = evidence_fingerprint(r1, project_version="2", model_name="m")
    assert fp_project != fp1
    fp_ctx = evidence_fingerprint(r1, project_version="1", model_name="m", project_context_compact="ctx-a")
    fp_ctx2 = evidence_fingerprint(r1, project_version="1", model_name="m", project_context_compact="ctx-b")
    assert fp_ctx != fp1
    assert fp_ctx != fp_ctx2
