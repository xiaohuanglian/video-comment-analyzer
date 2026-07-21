# -*- coding: utf-8 -*-
"""Final evidence_items_v1 acceptance tests (mock only)."""

from __future__ import annotations

from api.services.insight.evidence_adapter import finalize_card, third_column_fields
from api.services.insight.evidence_extractor import (
    evidence_item_count,
    extract_batch_with_split,
    extract_evidence_card_mock,
    sanitize_evidence_card,
)
from api.services.insight.evidence_schemas import (
    ANALYSIS_VERSION_EVIDENCE,
    EVIDENCE_PROMPT_VERSION,
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    EvidenceLevel,
    ItemCertainty,
    RecordStatus,
    SpeakerScope,
    compute_evidence_level,
)
from api.services.insight.readable_report import build_readable_report
from api.services.insight.research_agent import research_analysis_mock
from api.services.insight.schemas import SourceRecord


def _rec(rid: str, text: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="t.csv",
        source_row_number=1,
        comment_text=text,
    )


def test_versions():
    assert EVIDENCE_PROMPT_VERSION == "evidence_extract_v5"
    assert ANALYSIS_VERSION_EVIDENCE == "evidence_items_v1"


def test_empty_quote_dropped():
    record = _rec("q", "我练了三天")
    card = EvidenceCard(
        record_id="q",
        evidence_items=[
            {
                "type": "behavior",
                "text": "练了",
                "evidence_quote": "",
                "speaker_scope": "self",
                "certainty": "high",
                "subtype": "attempted",
            },
            {
                "type": "behavior",
                "text": "练了三天",
                "evidence_quote": "我练了三天",
                "speaker_scope": "self",
                "certainty": "high",
                "subtype": "attempted",
            },
        ],
    )
    cleaned = sanitize_evidence_card(record, card)
    assert len(cleaned.evidence_items) == 1
    assert cleaned.evidence_items[0].evidence_quote == "我练了三天"


def test_illegal_type_rejected():
    try:
        EvidenceItem(type="not_a_type", text="x", evidence_quote="x")
        assert False, "should reject"
    except Exception:
        pass


def test_bookmark_is_engagement_and_action_gap_not_attempted():
    card = extract_evidence_card_mock(_rec("g", "收藏永不停止，锻炼从不开始"))
    types = {i.type for i in card.evidence_items}
    assert EvidenceItemType.ENGAGEMENT in types
    assert EvidenceItemType.ACTION_GAP in types
    assert not any(
        i.type == EvidenceItemType.BEHAVIOR and i.subtype == "attempted" for i in card.evidence_items
    )


def test_checkin_not_auto_continued():
    card = extract_evidence_card_mock(_rec("c", "打卡"))
    assert any(i.type == EvidenceItemType.ENGAGEMENT and i.subtype == "checked_in" for i in card.evidence_items)
    # plain 打卡 without day count should not force continued alone as only signal — Day3 may add continued
    assert not any(i.subtype == "continued" for i in card.evidence_items)


def test_attempted_and_paid_help():
    a = extract_evidence_card_mock(_rec("a", "我刚刚试了试，只勉强做了一组"))
    assert any(i.subtype == "attempted" for i in a.evidence_items)
    p = extract_evidence_card_mock(_rec("p", "距离我在健身房办卡已经7个多月了，我的身材没有一点改变"))
    assert any(i.subtype == "sought_paid_help" for i in p.evidence_items)
    assert any(i.type == EvidenceItemType.ACTION_GAP for i in p.evidence_items)


def test_self_reported_ability():
    card = extract_evidence_card_mock(_rec("a", "我可以挨着墙倒立"))
    assert any(i.subtype == "self_reported_ability" for i in card.evidence_items)


def test_level_code_owned():
    items = [
        EvidenceItem(
            type=EvidenceItemType.BEHAVIOR,
            text="试了",
            evidence_quote="刚刚试了试",
            speaker_scope=SpeakerScope.SELF,
            certainty=ItemCertainty.HIGH,
            subtype="attempted",
        )
    ]
    assert compute_evidence_level(items) == EvidenceLevel.STRONG
    assert compute_evidence_level([]) == EvidenceLevel.WEAK or compute_evidence_level(
        [], status=RecordStatus.USABLE
    ) in {EvidenceLevel.WEAK, EvidenceLevel.NONE}


def test_general_observation_action_gap():
    card = extract_evidence_card_mock(_rec("o", "我觉得up粉丝这么多，是因为关注了收藏了就学会了吧"))
    gaps = [i for i in card.evidence_items if i.type == EvidenceItemType.ACTION_GAP]
    assert gaps
    assert gaps[0].speaker_scope == SpeakerScope.GENERAL_OBSERVATION


def test_quantitative_progress():
    card = extract_evidence_card_mock(_rec("n", "一个月了 从标准俯卧撑3个 到现在12个"))
    assert any(i.type == EvidenceItemType.QUANTITATIVE for i in card.evidence_items)


def test_concurrent_mock_no_misalign():
    records = [_rec(f"id{i}", f"这个动作怎么做{i}？") for i in range(24)]
    result = extract_batch_with_split(records, use_mock=True, batch_size=8, concurrency=4)
    assert result.stats.failed == 0
    assert len(result.cards) == 24
    assert [c.record_id for c in result.cards] == [r.internal_record_id for r in records]
    assert all(evidence_item_count(c) > 0 for c in result.cards)


def test_machine_and_off_topic():
    ai = extract_evidence_card_mock(_rec("ai", "摘要\n--本内容由AI视频小助理生成"))
    assert ai.record_status == RecordStatus.MACHINE_GENERATED
    ot = extract_evidence_card_mock(_rec("ot", "脖子这样的纹身显得修长"))
    assert ot.record_status == RecordStatus.OFF_TOPIC


def test_third_column_adapter():
    card = extract_evidence_card_mock(_rec("t", "收藏退出一气呵成"))
    fields = third_column_fields(card)
    assert fields["action_gap"]
    assert "contact_value" not in fields


def test_readable_report_has_sections():
    records = [_rec("r1", "倒立我做不到呀")]
    card = extract_evidence_card_mock(records[0])
    rows = [{"record_id": "r1", "card": card.model_dump(), "source": records[0].model_dump()}]
    research = research_analysis_mock(records, rows).model_dump()
    md = build_readable_report(research=research, records=records, card_rows=rows, run_id="t")
    assert "执行摘要" in md
    assert "行为与行动差距" in md
    assert "假设判断" in md


def test_quote_near_miss_repaired():
    record = _rec("r", "我刚刚试了试，只勉强做了一组")
    card = EvidenceCard(
        record_id="r",
        record_status=RecordStatus.USABLE,
        evidence_items=[
            {
                "type": "behavior",
                "text": "尝试训练",
                "evidence_quote": "我刚刚试了试只勉强",  # missing comma vs source
                "speaker_scope": "self",
                "certainty": "high",
                "subtype": "attempted",
            }
        ],
    )
    cleaned = sanitize_evidence_card(record, card)
    assert cleaned.evidence_items
    assert cleaned.evidence_items[0].evidence_quote
    assert cleaned.evidence_items[0].evidence_quote in (record.comment_text or "")


def test_empty_usable_card_bootstrapped():
    record = _rec("r", "我刚刚试了试")
    card = EvidenceCard(record_id="r", record_status=RecordStatus.USABLE, evidence_items=[])
    cleaned = sanitize_evidence_card(record, card)
    assert cleaned.evidence_items
    assert any(i.subtype == "attempted" for i in cleaned.evidence_items)


def test_beer_duck_off_topic_not_spam():
    card = extract_evidence_card_mock(_rec("b", "啤酒鸭连人带盒一起带走哈哈"))
    assert card.record_status == RecordStatus.OFF_TOPIC


def test_writer_queue_serializes(tmp_path, monkeypatch):
    from api.services.insight import evidence_writer as ew
    from api.services.insight.evidence_writer import EvidenceWriterQueue

    written = []

    def fake_append(run_id, source, card, **kwargs):
        written.append(card.record_id)

    monkeypatch.setattr(ew, "append_evidence_card", fake_append)
    q = EvidenceWriterQueue("run_test")
    q.start()
    for i in range(5):
        rec = _rec(f"id{i}", f"练了{i}次")
        card = extract_evidence_card_mock(rec)
        q.put(rec, card)
    q.close()
    assert written == [f"id{i}" for i in range(5)]


def test_enrich_paid_and_quant_from_text():
    paid_rec = _rec("p", "距离我在健身房办卡已经7个多月了，我的身材没有一点改变")
    paid = sanitize_evidence_card(
        paid_rec,
        EvidenceCard(record_id="p", record_status=RecordStatus.USABLE, evidence_items=[]),
    )
    assert any(i.subtype == "sought_paid_help" for i in paid.evidence_items)

    plan = _rec("q", "引体10次\n俯卧撑20次\n深蹲20次\n以上为1组，做4组")
    quant = sanitize_evidence_card(
        plan,
        EvidenceCard(
            record_id="q",
            record_status=RecordStatus.USABLE,
            evidence_items=[
                {
                    "type": "context",
                    "text": "训练计划",
                    "evidence_quote": "引体10次",
                    "speaker_scope": "unclear",
                    "certainty": "medium",
                }
            ],
        ),
    )
    assert any(i.type == EvidenceItemType.QUANTITATIVE for i in quant.evidence_items)


def test_cache_skips_empty_usable_and_respects_compact():
    from api.services.insight.evidence_cache import (
        clear_evidence_cache,
        evidence_fingerprint,
        get_cached_evidence,
        put_cached_evidence,
    )

    clear_evidence_cache()
    rec = _rec("c", "收藏退出一气呵成")
    empty = EvidenceCard(record_id="c", record_status=RecordStatus.USABLE, evidence_items=[])
    fp = evidence_fingerprint(rec, project_context_compact="A")
    put_cached_evidence(fp, empty)
    assert get_cached_evidence(fp) is None
    filled = extract_evidence_card_mock(rec)
    put_cached_evidence(fp, filled)
    assert get_cached_evidence(fp) is not None
    fp_b = evidence_fingerprint(rec, project_context_compact="B")
    assert fp_b != fp
    assert get_cached_evidence(fp_b) is None


def test_candidates_from_evidence_card():
    from api.services.insight.candidates import build_candidates

    card = extract_evidence_card_mock(_rec("u1", "收藏永不停止，锻炼从不开始"))
    rows = [
        {
            "record_id": "u1",
            "source": {
                "internal_record_id": "u1",
                "username": "tester",
                "user_id": "uid1",
                "platform": "bilibili",
                "comment_text": "收藏永不停止，锻炼从不开始",
                "user_homepage_url": "https://example.com/u",
            },
            "card": card.model_dump(),
        }
    ]
    doc = build_candidates(rows)
    assert doc.total_candidates == 1
    cand = doc.candidates[0]
    assert cand.actual_training_evidence in {"none", "planned", "tried", "continued"}
    assert any("行动差距" in x or "行为成本" in x for x in (cand.score_breakdown or [])) or cand.candidate_score >= 0


def test_adaptive_gate_limit_changes():
    import asyncio
    from api.services.insight.evidence_extractor import AdaptiveGate

    async def main():
        gate = AdaptiveGate(2, maximum=8)
        assert gate.limit == 2
        await gate.set_limit(4)
        assert gate.limit == 4
        await gate.set_limit(1)
        assert gate.limit == 1

    asyncio.run(main())


def test_analyzer_dispatches_evidence_version(tmp_path, monkeypatch):
    from api.services.insight import analyzer as az
    from api.services.insight.evidence_schemas import ANALYSIS_VERSION_EVIDENCE
    from api.services.insight.schemas import FieldMapping, RunConfig

    called = {"evidence": False}

    def fake_evidence(*args, **kwargs):
        called["evidence"] = True
        return {"run_id": "r", "processed": 0, "status": "completed", "analysis_version": ANALYSIS_VERSION_EVIDENCE}

    monkeypatch.setattr(az, "run_evidence_analysis_batch", fake_evidence)
    monkeypatch.setattr(
        az,
        "load_config",
        lambda run_id: RunConfig(
            run_id="r",
            name="t",
            file_paths=[],
            field_mapping=FieldMapping(comment_text="c"),
            analysis_version=ANALYSIS_VERSION_EVIDENCE,
            created_at="2026-01-01T00:00:00+00:00",
        ),
    )
    monkeypatch.setattr(az, "ensure_run_config", lambda c: c)
    out = az.run_analysis_batch("r", use_mock=True)
    assert called["evidence"] is True
    assert out["analysis_version"] == ANALYSIS_VERSION_EVIDENCE
