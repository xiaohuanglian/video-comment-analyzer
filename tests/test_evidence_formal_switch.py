# -*- coding: utf-8 -*-
"""Formal switch tests: quote ID backfill, default version, third column, mock 500."""

from __future__ import annotations

from api.services.insight.conclusion_review import review_research_code
from api.services.insight.evidence_adapter import (
    assign_evidence_item_ids,
    outreach_analysis_from_card,
)
from api.services.insight.evidence_extractor import (
    AdaptiveGate,
    extract_evidence_card_mock,
    run_evidence_extraction,
)
from api.services.insight.evidence_schemas import (
    ANALYSIS_VERSION_EVIDENCE,
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    ItemCertainty,
    PrimaryExpression,
    RecordStatus,
    SpeakerScope,
)
from api.services.insight.readable_report import (
    _finding_has_required_evidence,
    build_readable_report,
)
from api.services.insight.research_agent import research_analysis_mock
from api.services.insight.schemas import RunConfig, SourceRecord
from api.services.insight.candidates import build_candidates
from api.services.insight.evidence_adapter import analysis_dict_from_result_row


def _rec(rid: str, text: str, user_id: str = "") -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file="a.csv",
        source_row_number=1,
        comment_text=text,
        user_id=user_id or rid,
        username=f"u-{rid}",
        video_title="v1",
        creator_name="c1",
        user_homepage_url=f"https://space.bilibili.com/{rid}",
    )


def test_assign_evidence_item_ids_stable():
    card = EvidenceCard(
        record_id="r1",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.QUESTION,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.PROBLEM,
                text="动作疑问",
                evidence_quote="深蹲膝盖怎么摆？",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
            )
        ],
    )
    out = assign_evidence_item_ids(card)
    assert out.evidence_items[0].evidence_item_id == "r1::e0"
    # second call keeps id
    out2 = assign_evidence_item_ids(out)
    assert out2.evidence_items[0].evidence_item_id == "r1::e0"


def test_report_backfills_quote_from_evidence_item_id_only():
    text = "收藏了，但一直没开始练😅\n下周再说"
    records = [_rec("r1", text)]
    card = extract_evidence_card_mock(records[0])
    card = assign_evidence_item_ids(card)
    # Ensure at least one item with exact quote fragment from source
    if not card.evidence_items:
        card.evidence_items = [
            EvidenceItem(
                type=EvidenceItemType.ACTION_GAP,
                text="收藏未开始",
                evidence_quote="收藏了，但一直没开始练😅",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
                subtype="saved_but_not_started",
                evidence_item_id="r1::e0",
            )
        ]
    else:
        card.evidence_items[0].evidence_quote = "收藏了，但一直没开始练😅"
        card.evidence_items[0].evidence_item_id = "r1::e0"
    eid = card.evidence_items[0].evidence_item_id
    quote = card.evidence_items[0].evidence_quote
    rows = [{"record_id": "r1", "source": records[0].model_dump(), "card": card.model_dump()}]
    research = {
        "dataset_summary": {"total_comments": 1, "unique_users": 1, "usable_comments": 1},
        "research_conclusions": ["测试结论"],
        "unexpected_findings": [
            {
                "finding": "收藏未开始",
                "conclusion": "存在行动差距",
                "why_it_matters": "可能适合访谈",
                "record_ids": ["r1"],
                "supporting_evidence_refs": [{"record_id": "r1", "evidence_item_id": eid}],
                "limitations": "单条",
                "next_step": "访谈",
            }
        ],
        "themes": [],
        "hypothesis_assessment": [],
        "opportunity_hypotheses": [],
        "recommended_interviews": [],
        "recommended_experiments": [],
        "model_draft": {"dropped_evidence_refs": [{"record_id": "ghost", "evidence_item_id": "x"}]},
    }
    md = build_readable_report(research=research, records=records, card_rows=rows, run_id="t")
    assert quote in md
    assert "模型改写原话" not in md
    assert "执行摘要" in md
    assert "值得验证的机会" in md or "产品机会" in md
    assert "无效证据引用" in md or "跳过无效" in md
    # invalid id must not invent a fake quote
    assert "ghost-quote" not in md


def test_decision_report_has_single_action_layers_and_no_raw_subtypes():
    records = [_rec("r1", "我记不住这么多，不知道下一步练什么")]
    card = EvidenceCard(
        record_id="r1",
        record_status=RecordStatus.USABLE,
        primary_expression=PrimaryExpression.HELP_REQUEST,
        evidence_items=[
            EvidenceItem(
                type=EvidenceItemType.BEHAVIOR,
                text="正在持续训练",
                evidence_quote="我记不住这么多",
                speaker_scope=SpeakerScope.SELF,
                certainty=ItemCertainty.HIGH,
                subtype="completed_repeatedly",
                evidence_item_id="r1::e0",
            )
        ],
    )
    rows = [{"record_id": "r1", "source": records[0].model_dump(), "card": card.model_dump()}]
    research = {
        "dataset_summary": {
            "total_comments": 1,
            "unique_users": 1,
            "usable_comments": 1,
            "behavior_comments": 1,
        },
        "themes": [
            {
                "theme_id": "T1",
                "theme_name": "训练安排与下一步疑问",
                "theme_definition": "用户不知道下一步如何安排。",
                "comment_record_ids": ["r1"],
                "comment_count": 1,
                "unique_user_count": 1,
                "representative_evidence_refs": [
                    {"record_id": "r1", "evidence_item_id": "r1::e0"}
                ],
            }
        ],
        "unexpected_findings": [
            {
                "finding": "不知道下一步",
                "record_ids": ["r1"],
                "supporting_evidence_refs": [
                    {"record_id": "r1", "evidence_item_id": "r1::e0"}
                ],
                "conclusion": "可能需要规划辅助",
                "limitations": "仅一名用户",
                "next_step": "访谈",
            }
        ],
        "hypothesis_assessment": [
            {
                "hypothesis_id": "H3",
                "conclusion": "supported",
                "supporting_evidence_refs": [
                    {
                        "record_id": "r1",
                        "evidence_item_id": "r1::e0",
                        "strength": "weak_context",
                    }
                ],
            }
        ],
        "opportunity_hypotheses": [],
        "model_draft": {},
    }
    md = build_readable_report(research=research, records=records, card_rows=rows)
    assert md.count("## 当前优先行动") == 1
    assert "访谈与实验" not in md
    assert "访谈结果按首页" not in md
    assert "【事实】" in md
    assert "【推断】" in md
    assert "【限制】" in md
    assert "【建议】" in md
    assert "H1" not in md and "H2" not in md and "H3" not in md
    assert "值得验证的机会" in md
    assert "completed_repeatedly" not in md
    assert "正在持续训练" in md
    assert md.count("### 发现 ") == 1


def test_paid_finding_requires_paid_behavior_evidence():
    finding = {
        "finding": "付费但无结果",
        "supporting_evidence_refs": [{"evidence_item_id": "r1::e0"}],
    }
    assert not _finding_has_required_evidence(
        finding,
        {"r1::e0": {"type": "result", "subtype": "", "evidence_quote": "省钱了"}},
    )
    assert _finding_has_required_evidence(
        finding,
        {
            "r1::e0": {
                "type": "action_gap",
                "subtype": "paid_but_no_result",
                "text": "我花了钱但没效果",
                "evidence_quote": "我花了钱但没效果",
            }
        },
    )


def test_report_skips_missing_evidence_item_id():
    records = [_rec("r1", "怎么练深蹲？")]
    card = extract_evidence_card_mock(records[0])
    card = assign_evidence_item_ids(card)
    rows = [{"record_id": "r1", "source": records[0].model_dump(), "card": card.model_dump()}]
    research = {
        "dataset_summary": {},
        "research_conclusions": [],
        "unexpected_findings": [
            {
                "finding": "x",
                "record_ids": ["r1"],
                "supporting_evidence_refs": [
                    {"record_id": "r1", "evidence_item_id": "r1::missing"}
                ],
                "conclusion": "x",
            }
        ],
        "themes": [],
        "hypothesis_assessment": [],
        "opportunity_hypotheses": [],
        "recommended_interviews": [],
        "recommended_experiments": [],
        "model_draft": {},
    }
    md = build_readable_report(research=research, records=records, card_rows=rows)
    assert "无有效 evidence_item_id" in md


def test_research_mock_emits_refs_not_quotes():
    records = [_rec("a", "帮我看动作哪里不对"), _rec("b", "谢谢教练")]
    rows = [
        {
            "record_id": r.internal_record_id,
            "source": r.model_dump(),
            "card": assign_evidence_item_ids(extract_evidence_card_mock(r)).model_dump(),
        }
        for r in records
    ]
    analysis = research_analysis_mock(records, rows)
    for theme in analysis.themes:
        assert theme.representative_quotes == []
        if theme.representative_evidence_refs:
            ref = theme.representative_evidence_refs[0]
            assert ref.evidence_item_id
            assert "::e" in ref.evidence_item_id
    md = build_readable_report(
        research=analysis.model_dump(),
        records=records,
        card_rows=rows,
    )
    # backfilled quotes come from cards
    assert "「" in md or "代表原话" in md


def test_default_run_config_is_evidence_items_v1():
    from api.services.insight.schemas import FieldMapping

    cfg = RunConfig(run_id="x", name="n", file_paths=["a.csv"], field_mapping=FieldMapping(comment_text="c"))
    assert cfg.analysis_version == ANALYSIS_VERSION_EVIDENCE
    normalized = RunConfig(
        run_id="y",
        name="n",
        file_paths=["a.csv"],
        field_mapping=FieldMapping(comment_text="c"),
        analysis_version="removed_engine",
    )
    assert normalized.analysis_version == ANALYSIS_VERSION_EVIDENCE


def test_create_run_request_default_version():
    from api.routers.analysis import CreateRunRequest

    body = CreateRunRequest(file_paths=["data/demo/comments.csv"])
    assert "analysis_version" not in body.model_dump()


def test_mock_500_concurrency_no_id_collision_and_report():
    records = [_rec(f"id{i}", f"这个动作怎么做{i}？膝盖疼吗") for i in range(500)]
    result = run_evidence_extraction(records, use_mock=True, batch_size=20, concurrency=8)
    assert result.stats.failed == 0
    assert len(result.cards) == 500
    ids = [c.record_id for c in result.cards]
    assert len(ids) == len(set(ids)) == 500

    rows = []
    for rec, card in zip(records, result.cards):
        rows.append(
            {
                "record_id": rec.internal_record_id,
                "source": rec.model_dump(),
                "card": assign_evidence_item_ids(card).model_dump(),
            }
        )
    analysis = research_analysis_mock(records, rows)
    md = build_readable_report(research=analysis.model_dump(), records=records, card_rows=rows)
    assert "执行摘要" in md
    assert "核心数字" in md

    import asyncio

    async def _gate():
        gate = AdaptiveGate(8, maximum=16)
        assert gate.limit == 8
        await gate.set_limit(4)
        assert gate.limit == 4
        await gate.set_limit(12)
        assert gate.limit == 12

    asyncio.run(_gate())


def test_product_fit_source_and_candidates_from_evidence():
    text = "办了卡还是没效果，想找人带练"
    rec = _rec("c1", text)
    card = extract_evidence_card_mock(rec)
    card = assign_evidence_item_ids(card)
    projected = outreach_analysis_from_card(card)
    assert projected["product_fit_source"] == "rule_based_projection"
    assert "product_fit" in projected

    row = {
        "record_id": "c1",
        "source": rec.model_dump(),
        "card": card.model_dump(),
        "analysis": analysis_dict_from_result_row(
            {"record_id": "c1", "source": rec.model_dump(), "card": card.model_dump()}
        ),
    }
    doc = build_candidates([row])
    assert doc.candidates
    top = doc.candidates[0]
    assert top.user_key
    blob = str(top.model_dump())
    assert top.candidate_score >= 0
    assert "product_fit" in blob or "问题" in (top.contact_reason or "") or top.score_breakdown
def test_review_soft_warns_dropped_refs_not_fail_on_paraphrase():
    records = [_rec("r1", "怎么练？")]
    rows = [
        {
            "record_id": "r1",
            "source": records[0].model_dump(),
            "card": assign_evidence_item_ids(extract_evidence_card_mock(records[0])).model_dump(),
        }
    ]
    from api.services.insight.research_agent import compute_dataset_summary
    from api.services.insight.evidence_schemas import ResearchAnalysis, ResearchTheme

    analysis = ResearchAnalysis(
        dataset_summary=compute_dataset_summary(records, rows),
        themes=[
            ResearchTheme(
                theme_id="T1",
                theme_name="x",
                comment_record_ids=["r1"],
                representative_quotes=["这段是改写的原话zzz"],
            )
        ],
        model_draft={"dropped_evidence_refs": [{"record_id": "x", "evidence_item_id": "bad"}]},
    )
    review = review_research_code(analysis, records, card_rows=rows)
    assert review.passed is True
    descs = " ".join(i.description for i in review.issues)
    assert "跳过无效证据引用" in descs or "representative_quotes" in descs
