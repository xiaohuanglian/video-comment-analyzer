# -*- coding: utf-8 -*-
"""Tests for validity / secondary_expressions / performance / blind pack."""

from __future__ import annotations

from api.services.insight.ab_blind_pack import select_blind_sample_ids
from api.services.insight.evidence_extractor import extract_evidence_card_mock, extract_batch_with_split
from api.services.insight.evidence_schemas import (
    EvidenceCard,
    PrimaryExpression,
    RecordStatus,
    Validity,
    normalize_validity,
    is_participating_validity,
    is_spam_validity,
)
from api.services.insight.performance_metrics import PerformanceMetrics
from api.services.insight.schemas import SourceRecord


def _rec(rid: str, text: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="t.csv",
        source_row_number=1,
        comment_text=text,
    )


def test_normalize_validity_legacy_aliases():
    assert normalize_validity("valid") == Validity.MEANINGFUL_EVIDENCE
    assert normalize_validity("invalid") == Validity.SPAM_OR_GARBLED
    assert normalize_validity("low_information_but_valid") == Validity.LOW_INFORMATION_BUT_VALID
    assert is_participating_validity("low_information_but_valid")
    assert is_spam_validity("invalid")
    assert not is_participating_validity("spam_or_garbled")


def test_thanks_checkin_bookmark_are_low_info_valid():
    thanks = extract_evidence_card_mock(_rec("t1", "谢谢教练"))
    checkin = extract_evidence_card_mock(_rec("t2", "今日打卡"))
    bookmark = extract_evidence_card_mock(_rec("t3", "收藏了"))
    assert thanks.record_status == RecordStatus.USABLE
    assert checkin.record_status == RecordStatus.USABLE
    assert bookmark.record_status == RecordStatus.USABLE


def test_ad_and_garbled_are_spam():
    ad = extract_evidence_card_mock(_rec("s1", "加微信免费领取课程 http://x.y"))
    garbled = extract_evidence_card_mock(_rec("s2", "@@@###$$$"))
    empty = extract_evidence_card_mock(_rec("s3", "  "))
    assert ad.record_status == RecordStatus.SPAM
    assert garbled.record_status == RecordStatus.GARBLED
    assert empty.record_status == RecordStatus.GARBLED


def test_secondary_expressions_compound():
    card = extract_evidence_card_mock(_rec("c1", "谢谢教练，臀桥酸正常吗？"))
    assert card.primary_expression == PrimaryExpression.QUESTION
    assert card.record_status == RecordStatus.USABLE


def test_secondary_does_not_affect_primary_percent_logic():
    """Secondary is multi; primary remains single — percent should only use primary."""
    cards = [
        extract_evidence_card_mock(_rec("a", "谢谢教练，这正常吗？")),
        extract_evidence_card_mock(_rec("b", "已打卡")),
        extract_evidence_card_mock(_rec("c", "帮我看动作")),
    ]
    primary_counts = {}
    for c in cards:
        primary_counts[c.primary_expression.value] = primary_counts.get(c.primary_expression.value, 0) + 1
        assert isinstance(c.secondary_expressions, list)
        assert c.primary_expression not in c.secondary_expressions
    assert sum(primary_counts.values()) == len(cards)


def test_evidence_card_accepts_legacy_valid_invalid_strings():
    card = EvidenceCard(record_id="x", validity="invalid")
    assert card.record_status == RecordStatus.SPAM
    card2 = EvidenceCard(record_id="y", validity="valid")
    assert card2.record_status == RecordStatus.USABLE
    assert card2.validity == Validity.MEANINGFUL_EVIDENCE


def test_performance_metrics_elapsed_p50_p95_and_null_cost():
    perf = PerformanceMetrics()
    perf.mark_start()
    perf.add_batch_latency(0.2)
    perf.add_batch_latency(0.4)
    perf.add_batch_latency(1.0)
    out = perf.finalize(
        processed=30,
        failed=0,
        cache_hits=1,
        format_failures=0,
        splits=0,
        retry_count=2,
        requests_count=3,
        prompt_tokens=1000,
        completion_tokens=500,
        cache_hit_tokens=100,
        batch_size=20,
        concurrency=5,
        model_name="mock",
        input_price=None,
        output_price=None,
    )
    assert out["batch_count"] == 3
    assert out["requests_count"] == 3
    assert out["retry_count"] == 2
    assert out["p50_batch_latency"] > 0
    assert out["p95_batch_latency"] >= out["p50_batch_latency"]
    assert out["actual_cost"] is None
    assert out["comments_per_minute"] >= 0
    assert "batch_latencies" not in out


def test_performance_metrics_cost_when_prices_set():
    perf = PerformanceMetrics()
    perf.mark_start()
    perf.add_batch_latency(0.1)
    out = perf.finalize(
        processed=10,
        failed=0,
        cache_hits=0,
        format_failures=0,
        splits=0,
        retry_count=0,
        requests_count=1,
        prompt_tokens=1000,
        completion_tokens=1000,
        cache_hit_tokens=0,
        input_price=0.001,
        output_price=0.002,
    )
    assert out["actual_cost"] is not None
    assert out["actual_cost"] > 0


def test_extract_batch_writes_performance_block():
    records = [_rec(f"p{i}", f"这个怎么做{i}？") for i in range(5)]
    result = extract_batch_with_split(records, use_mock=True, batch_size=5)
    assert result.stats.performance
    assert result.stats.performance.get("processed") == 5
    assert "elapsed_seconds" in result.stats.performance
    assert "comments_per_minute" in result.stats.performance


def test_blind_pack_composition_rules():
    legacy = {}
    evidence = {}
    # 15 invalid
    for i in range(15):
        rid = f"inv{i}"
        legacy[rid] = {"record_id": rid, "source": {"comment_text": f"spam{i}"}, "analysis": {"specific_problems": []}}
        evidence[rid] = {
            "record_id": rid,
            "source": {"comment_text": f"spam{i}"},
            "card": {"validity": "invalid", "primary_expression": "other", "problem_or_need": []},
        }
    # 20 other (non-invalid)
    for i in range(20):
        rid = f"oth{i}"
        legacy[rid] = {"record_id": rid, "source": {"comment_text": f"view{i}"}, "analysis": {"specific_problems": []}}
        evidence[rid] = {
            "record_id": rid,
            "source": {"comment_text": f"view{i}"},
            "card": {"validity": "valid", "primary_expression": "other", "problem_or_need": []},
        }
    # 12 B-new problems
    for i in range(12):
        rid = f"new{i}"
        legacy[rid] = {"record_id": rid, "source": {"comment_text": f"q{i}"}, "analysis": {"specific_problems": []}}
        evidence[rid] = {
            "record_id": rid,
            "source": {"comment_text": f"q{i}"},
            "card": {
                "validity": "valid",
                "primary_expression": "question",
                "problem_or_need": [{"text": "痛", "evidence_quote": "痛"}],
            },
        }
    # hypothesis conflict via research + A relations
    for i in range(12):
        rid = f"hyp{i}"
        legacy[rid] = {
            "record_id": rid,
            "source": {"comment_text": f"h{i}"},
            "analysis": {
                "specific_problems": ["x"],
                "hypothesis_relations": [{"hypothesis_id": "H1", "relation": "supports"}],
            },
        }
        evidence[rid] = {
            "record_id": rid,
            "source": {"comment_text": f"h{i}"},
            "card": {"validity": "valid", "primary_expression": "complaint", "problem_or_need": [{"text": "x"}]},
        }
    research = {
        "hypothesis_assessment": [
            {
                "hypothesis_id": "H1",
                "supporting_record_ids": [f"hyp{i}" for i in range(6)],
                "weakening_record_ids": [f"hyp{i}" for i in range(6, 12)],
            }
        ],
        "themes": [{"comment_record_ids": ["hyp0", "hyp1"]}],
    }
    samples, notes = select_blind_sample_ids(legacy, evidence, research, seed=42, target_total=50)
    assert notes["total"] == 50
    by_group = {}
    for s in samples:
        by_group.setdefault(s["sample_group"], []).append(s["record_id"])
    assert len(by_group.get("invalid_all", [])) == 15
    assert len(by_group.get("other_random", [])) == 15
    assert len(by_group.get("b_new_problem", [])) == 10
    assert len(by_group.get("hypothesis_conflict", [])) == 10
    # all invalid included
    assert set(by_group["invalid_all"]) == {f"inv{i}" for i in range(15)}
    # sources not exposed in sample descriptors
    assert all("legacy" not in s["sample_group"] and "evidence" not in s["sample_group"] for s in samples)
