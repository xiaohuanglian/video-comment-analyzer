# -*- coding: utf-8 -*-
"""Tests for new_signal evidence sanitization."""

from __future__ import annotations

import pytest

from api.services.insight.schemas import (
    CommentAnalysisResult,
    NewSignal,
    NewSignalType,
    PrimaryIntent,
    SourceRecord,
)
from api.services.insight.validation import sanitize_new_signals, validate_analysis


def _record(text: str) -> SourceRecord:
    return SourceRecord(
        internal_record_id="r1",
        source_file="test.csv",
        source_row_number=1,
        comment_text=text,
    )


def test_sanitize_drops_signal_without_verbatim_evidence() -> None:
    record = _record("我膝盖术后在练康复动作")
    analysis = CommentAnalysisResult(
        record_id="r1",
        primary_intent=PrimaryIntent.QUESTION,
        new_signals=[
            NewSignal(
                type=NewSignalType.NEW_USER_SEGMENT,
                text="残疾人（肢体不对称）",
                evidence_quote="残疾人（肢体不对称）",
            )
        ],
    )
    cleaned = sanitize_new_signals(record, analysis)
    assert cleaned.new_signals == []


def test_sanitize_repairs_evidence_from_signal_text() -> None:
    record = _record("产后腹直肌分离，正在找恢复方法")
    analysis = CommentAnalysisResult(
        record_id="r1",
        primary_intent=PrimaryIntent.QUESTION,
        new_signals=[
            NewSignal(
                type=NewSignalType.NEW_USER_SEGMENT,
                text="腹直肌分离问题",
                evidence_quote="腹直肌分离用户",
            )
        ],
    )
    cleaned = sanitize_new_signals(record, analysis)
    assert len(cleaned.new_signals) == 1
    assert cleaned.new_signals[0].evidence_quote == "腹直肌分离"


def test_validate_analysis_no_longer_fails_on_bad_new_signal() -> None:
    record = _record("中考体育训练，孩子跑步总喘")
    analysis = CommentAnalysisResult(
        record_id="r1",
        primary_intent=PrimaryIntent.QUESTION,
        new_signals=[
            NewSignal(
                type=NewSignalType.NEW_USER_SEGMENT,
                text="中考体育家长",
                evidence_quote="中考体育家长群体",
            )
        ],
    )
    validate_analysis(record, analysis)
    assert len(analysis.new_signals) <= 1
    if analysis.new_signals:
        assert analysis.new_signals[0].evidence_quote in record.comment_text


def test_sanitize_specific_problems_drops_paraphrase() -> None:
    from api.services.insight.validation import sanitize_specific_problems

    record = _record("膝盖术后在练康复")
    analysis = CommentAnalysisResult(
        record_id="r1",
        primary_intent=PrimaryIntent.QUESTION,
        specific_problems=["半月板严重损伤需要手术"],
    )
    cleaned = sanitize_specific_problems(record, analysis)
    assert cleaned.specific_problems == []


def test_sanitize_specific_problems_keeps_verbatim() -> None:
    from api.services.insight.validation import sanitize_specific_problems

    record = _record("膝盖术后在练康复")
    analysis = CommentAnalysisResult(
        record_id="r1",
        primary_intent=PrimaryIntent.QUESTION,
        specific_problems=["膝盖术后"],
    )
    cleaned = sanitize_specific_problems(record, analysis)
    assert cleaned.specific_problems == ["膝盖术后"]


def test_legacy_runs_root_is_under_data() -> None:
    from api.services.insight import storage
    from api.services.insight.run_locations import _legacy_runs_root

    assert _legacy_runs_root() == storage.RUNS_ROOT
    assert _legacy_runs_root().parent == storage.DATA_DIR


def test_resolve_under_data_rejects_traversal() -> None:
    from api.services.insight.run_locations import resolve_under_data

    with pytest.raises(ValueError):
        resolve_under_data("../../etc/passwd")
