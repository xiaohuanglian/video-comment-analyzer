from types import SimpleNamespace

from api.services.insight.evidence_schemas import (
    DatasetSummaryCounts,
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    EvidenceRef,
    ItemCertainty,
    ResearchAnalysis,
    ResearchTheme,
    SpeakerScope,
)
from api.services.insight.schemas import SourceRecord
from api.services.insight.semantic_validator import (
    SemanticVerdict,
    build_claim_ledger,
    build_manual_audit_samples,
    review_open_themes,
    run_semantic_review,
    sanitize_item_semantics,
)
from api.services.insight.theme_schemas import ThemeRecord, ThemeStats, ThemesDocument


def _record(rid: str, text: str, source_file: str = "a.csv") -> SourceRecord:
    return SourceRecord(
        internal_record_id=rid,
        source_file=source_file,
        source_row_number=1,
        comment_text=text,
        username=rid,
        video_title=source_file,
    )


def _row(
    record: SourceRecord,
    *,
    item_type: EvidenceItemType,
    subtype: str = "",
    scope: SpeakerScope = SpeakerScope.SELF,
) -> dict:
    item = EvidenceItem(
        type=item_type,
        subtype=subtype,
        text=record.comment_text,
        evidence_quote=record.comment_text,
        evidence_item_id=f"{record.internal_record_id}::e1",
        speaker_scope=scope,
        certainty=ItemCertainty.HIGH,
    )
    card = EvidenceCard(record_id=record.internal_record_id, evidence_items=[item])
    return {
        "record_id": record.internal_record_id,
        "source": record.model_dump(),
        "card": card.model_dump(),
    }


def _analysis(record: SourceRecord, text: str, *, total: int = 1) -> ResearchAnalysis:
    return ResearchAnalysis(
        dataset_summary=DatasetSummaryCounts(
            total_comments=total,
            usable_comments=total,
        ),
        themes=[
            ResearchTheme(
                theme_id="T1",
                theme_name=text,
                theme_definition=text,
                comment_record_ids=[record.internal_record_id],
                comment_count=1,
                representative_evidence_refs=[
                    EvidenceRef(
                        record_id=record.internal_record_id,
                        evidence_item_id=f"{record.internal_record_id}::e1",
                    )
                ],
            )
        ],
    )


def _config():
    return SimpleNamespace(
        model_name="test",
        base_url="https://example.com",
        input_price=0.001,
        output_price=0.002,
    )


def test_open_theme_review_keeps_more_than_twenty_themes():
    records = [_record("r1", "肩颈不适")]
    themes = [
        ThemeRecord(
            theme_id=f"t{i}",
            theme_name=f"主题{i}",
            theme_type="new_problem",
            definition="用户反馈不适",
            record_ids=["r1"],
            representative_quotes=["肩颈不适"],
            stats=ThemeStats(comment_count=1),
        )
        for i in range(25)
    ]
    filtered, review = review_open_themes(
        ThemesDocument(themes=themes),
        records,
        config=_config(),
        api_key="",
        use_mock=True,
    )
    assert len(review.claims) == 25
    assert len(filtered.themes) == 25


def test_paid_failure_claim_rejects_cost_saving_quote():
    record = _record("r1", "做这个操让我省钱了")
    analysis = _analysis(record, "用户付费但无结果")
    rows = [_row(record, item_type=EvidenceItemType.RESULT, subtype="saved_cost")]

    claims = build_claim_ledger(analysis, [record], rows)

    assert claims[0].hard_verdict == SemanticVerdict.CONTRADICTED
    filtered, review = run_semantic_review(
        analysis,
        [record],
        rows,
        config=_config(),
        api_key="",
        use_mock=True,
    )
    assert filtered.themes == []
    assert review.removed_claim_ids == ["theme:T1"]


def test_plan_is_not_accepted_as_completed_action():
    record = _record("r1", "我计划明天开始练")
    analysis = _analysis(record, "用户已经行动")
    rows = [_row(record, item_type=EvidenceItemType.BEHAVIOR, subtype="planned")]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.CONTRADICTED
    assert any("计划" in reason for reason in claim.hard_reasons)


def test_sales_pitch_is_not_accepted_as_purchase():
    record = _record("r1", "教练一直向我推销付费课程")
    analysis = _analysis(record, "用户已经付费购买课程")
    rows = [_row(record, item_type=EvidenceItemType.OPINION)]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.CONTRADICTED


def test_other_person_experience_is_not_attributed_to_commenter():
    record = _record("r1", "我朋友练了以后舒服多了")
    analysis = _analysis(record, "用户本人已经获得结果")
    rows = [
        _row(
            record,
            item_type=EvidenceItemType.RESULT,
            scope=SpeakerScope.OTHER_USER,
        )
    ]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.CONTRADICTED


def test_pain_after_action_is_not_positive_effect():
    record = _record("r1", "我做完以后更疼了")
    analysis = _analysis(record, "用户已经获得结果并明显改善")
    rows = [_row(record, item_type=EvidenceItemType.RESULT)]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.CONTRADICTED


def test_minor_sample_cannot_be_called_prevalent():
    record = _record("r1", "我练了三天")
    analysis = _analysis(record, "大部分用户都有这个问题", total=10)
    rows = [_row(record, item_type=EvidenceItemType.BEHAVIOR, subtype="attempted")]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.CONTRADICTED


def test_comment_correlation_cannot_be_reported_as_causality():
    record = _record("r1", "我练了三天，感觉舒服一点")
    analysis = _analysis(record, "这证明该动作必然提升训练效果")
    rows = [_row(record, item_type=EvidenceItemType.RESULT)]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.INSUFFICIENT


def test_short_self_report_cannot_be_reported_as_medical_proof():
    record = _record("r1", "我练了三天，感觉舒服一点")
    analysis = _analysis(record, "医学证明该动作治疗有效")
    rows = [_row(record, item_type=EvidenceItemType.RESULT)]

    claim = build_claim_ledger(analysis, [record], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.INSUFFICIENT


def test_cross_video_reference_is_rejected():
    allowed = _record("a1", "视频A评论", "a.csv")
    foreign = _record("b1", "我练了三天", "b.csv")
    analysis = _analysis(foreign, "用户尝试了训练")
    rows = [_row(foreign, item_type=EvidenceItemType.BEHAVIOR, subtype="attempted")]

    claim = build_claim_ledger(analysis, [allowed], rows)[0]

    assert claim.hard_verdict == SemanticVerdict.CONTRADICTED
    assert any("当前影片" in reason for reason in claim.hard_reasons)


def test_agent_insufficient_verdict_removes_claim():
    record = _record("r1", "我练了三天")
    analysis = _analysis(record, "用户尝试训练")
    rows = [_row(record, item_type=EvidenceItemType.BEHAVIOR, subtype="attempted")]

    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"r":[{"i":"theme:T1","v":"insufficient","x":"不足"}]}'
                )
            )
        ],
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_kwargs: response)
        )
    )

    filtered, review = run_semantic_review(
        analysis,
        [record],
        rows,
        config=_config(),
        api_key="x",
        use_mock=False,
        client=client,
    )

    assert filtered.themes == []
    assert review.completion_tokens == 8


def test_item_text_is_rebound_to_quote_and_unsupported_self_scope_is_lowered():
    record = _record("r1", "朋友练完舒服了")
    item = EvidenceItem(
        type=EvidenceItemType.RESULT,
        text="用户本人训练后改善",
        evidence_quote="朋友练完舒服了",
        speaker_scope=SpeakerScope.SELF,
        certainty=ItemCertainty.HIGH,
    )

    sanitized = sanitize_item_semantics(record, [item])[0]

    assert sanitized.text == sanitized.evidence_quote
    assert sanitized.speaker_scope == SpeakerScope.UNCLEAR
    assert sanitized.certainty == ItemCertainty.LOW


def test_open_theme_paid_failure_is_removed_before_export():
    record = _record("r1", "做这个操让我省钱了")
    doc = ThemesDocument(
        themes=[
            ThemeRecord(
                theme_id="OT1",
                theme_name="付费失败",
                theme_type="result",
                definition="用户付费但无结果",
                implication="付费失败机会",
                record_ids=["r1"],
                representative_quotes=["做这个操让我省钱了"],
                stats=ThemeStats(comment_count=1),
            )
        ]
    )

    filtered, review = review_open_themes(
        doc,
        [record],
        config=_config(),
        api_key="",
        use_mock=True,
    )

    assert filtered.themes == []
    assert review.removed_claim_ids == ["open_theme:OT1"]


def test_open_theme_with_fabricated_quote_is_removed():
    record = _record("r1", "原评论只说动作很难")
    doc = ThemesDocument(
        themes=[
            ThemeRecord(
                theme_id="OT1",
                theme_name="改善反馈",
                theme_type="result",
                definition="用户明显改善",
                record_ids=["r1"],
                representative_quotes=["用户已经完全康复"],
                stats=ThemeStats(comment_count=1),
            )
        ]
    )

    filtered, _review = review_open_themes(
        doc,
        [record],
        config=_config(),
        api_key="",
        use_mock=True,
    )

    assert filtered.themes == []


def test_manual_audit_sample_is_stable_and_capped_per_video():
    records = [
        _record(f"a{i}", f"A{i}", "a.csv") for i in range(35)
    ] + [
        _record(f"b{i}", f"B{i}", "b.csv") for i in range(5)
    ]

    first = build_manual_audit_samples(records, [], per_source=30)
    second = build_manual_audit_samples(list(reversed(records)), [], per_source=30)

    assert first == second
    assert first["a.csv"]["sample_size"] == 30
    assert first["b.csv"]["sample_size"] == 5
    assert first["a.csv"]["precision"] is None
