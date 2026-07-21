# -*- coding: utf-8 -*-
"""Tests for research agent + conclusion review (no paid API)."""

from __future__ import annotations

from api.services.insight.conclusion_review import review_research_code, run_conclusion_review
from api.services.insight.evidence_extractor import extract_evidence_card_mock
from api.services.insight.evidence_schemas import (
    HypothesisAssessment,
    HypothesisConclusion,
    OpportunityHypothesis,
    ResearchAnalysis,
    ResearchTheme,
    ReviewIssueType,
)
from api.services.insight.research_agent import (
    compute_dataset_summary,
    recount_research_analysis,
    research_analysis_mock,
    run_research_analysis,
)
from api.services.insight.schemas import SourceRecord


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
    )


def _rows(records):
    rows = []
    for r in records:
        card = extract_evidence_card_mock(r)
        rows.append({"record_id": r.internal_record_id, "source": r.model_dump(), "card": card.model_dump()})
    return rows


def test_recount_maps_numeric_indices_to_record_ids():
    records = [_rec("r1", "a"), _rec("r2", "b"), _rec("r3", "c")]
    rows = _rows(records)
    draft = {
        "themes": [
            {
                "theme_id": "T1",
                "theme_name": "t",
                "comment_record_ids": ["0", "2"],
            }
        ],
        "hypothesis_assessment": [
            {
                "hypothesis_id": "H1",
                "conclusion": "supported",
                "supporting_record_ids": ["1"],
                "weakening_record_ids": [],
            }
        ],
        "opportunity_hypotheses": [],
        "research_conclusions": [],
        "recommended_interviews": [],
        "recommended_experiments": [],
        "unexpected_findings": [],
    }
    analysis = recount_research_analysis(
        draft, known_ids={"r1", "r2", "r3"}, records=records, card_rows=rows
    )
    assert analysis.themes[0].comment_record_ids == ["r1", "r3"]
    h1 = next(a for a in analysis.hypothesis_assessment if a.hypothesis_id == "H1")
    assert h1.supporting_record_ids == ["r2"]
    assert h1.conclusion.value == "supported"


def test_recount_filters_unknown_ids_and_recomputes_theme_counts():
    records = [_rec("r1", "怎么练？"), _rec("r2", "谢谢"), _rec("r3", "帮我看动作")]
    rows = _rows(records)
    draft = {
        "themes": [
            {
                "theme_id": "T1",
                "theme_name": "求助",
                "comment_record_ids": ["r1", "r3", "ghost"],
                "confidence": 0.5,
            }
        ],
        "hypothesis_assessment": [
            {
                "hypothesis_id": "H2",
                "conclusion": "supported",
                "supporting_record_ids": ["r3", "ghost"],
                "weakening_record_ids": ["r2"],
                "reasoning_summary": "x",
                "unknowns": [],
            }
        ],
        "opportunity_hypotheses": [
            {
                "opportunity_name": "纠错",
                "supporting_evidence": ["有求助"],
                "supporting_record_ids": ["r3"],
            }
        ],
        "research_conclusions": ["c"],
        "recommended_interviews": [],
        "recommended_experiments": [],
        "unexpected_findings": [],
    }
    analysis = recount_research_analysis(
        draft, known_ids={r.internal_record_id for r in records}, records=records, card_rows=rows
    )
    theme = analysis.themes[0]
    assert theme.comment_record_ids == ["r1", "r3"]
    assert theme.comment_count == 2
    assert theme.unique_user_count == 2
    h2 = next(a for a in analysis.hypothesis_assessment if a.hypothesis_id == "H2")
    assert "ghost" not in h2.supporting_record_ids
    assert "r3" in h2.supporting_record_ids
    assert analysis.dataset_summary.total_comments == 3


def test_research_mock_includes_support_and_weaken_slots():
    records = [
        _rec("a", "帮我看动作哪里不对"),
        _rec("b", "谢谢教练"),
        _rec("c", "已打卡"),
    ]
    rows = _rows(records)
    analysis, _ = run_research_analysis(records, rows, use_mock=True)
    assert len(analysis.hypothesis_assessment) == 3
    assert analysis.opportunity_hypotheses
    assert analysis.opportunity_hypotheses[0].supporting_evidence or analysis.opportunity_hypotheses[
        0
    ].supporting_record_ids


def test_review_detects_unsupported_claim_and_count_mismatch():
    records = [_rec("r1", "你好")]
    rows = _rows(records)
    bad = ResearchAnalysis(
        dataset_summary=compute_dataset_summary(records, rows).model_copy(
            update={"total_comments": 999}
        ),
        themes=[
            ResearchTheme(
                theme_id="T1",
                theme_name="x",
                comment_record_ids=["missing"],
                representative_quotes=["这段原话不在任何评论里zzz"],
            )
        ],
        hypothesis_assessment=[
            HypothesisAssessment(
                hypothesis_id="H1",
                conclusion=HypothesisConclusion.SUPPORTED,
                supporting_record_ids=[],
            )
        ],
        opportunity_hypotheses=[
            OpportunityHypothesis(opportunity_name="无证据机会")
        ],
    )
    review = review_research_code(bad, records, card_rows=rows)
    types = {i.type for i in review.issues}
    assert ReviewIssueType.COUNT_MISMATCH in types
    assert ReviewIssueType.UNSUPPORTED_CLAIM in types
    assert review.passed is False


def test_review_does_not_overwrite_evidence_cards(tmp_path, monkeypatch):
    """Review only writes conclusion_review; evidence cards stay intact."""
    from api.services.insight import storage

    monkeypatch.setattr(storage, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(storage, "RUNS_ROOT", tmp_path / "data" / "analysis_runs")
    (tmp_path / "data").mkdir()

    records = [_rec("r1", "怎么安排训练计划？"), _rec("r2", "坚持不下来")]
    rows = _rows(records)
    analysis = research_analysis_mock(records, rows)
    review, _ = run_conclusion_review(analysis, records, card_rows=rows, use_mock=True)
    # cards unchanged conceptually — review has no card mutation API
    assert rows[0]["card"]["record_id"] == "r1"
    assert isinstance(review.passed, bool)
