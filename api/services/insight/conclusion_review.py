# -*- coding: utf-8 -*-
"""Lightweight conclusion review — does not re-analyze all comments."""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Sequence, Set

from .evidence_prompts import REVIEW_SYSTEM_PROMPT, build_review_user_message
from .evidence_schemas import (
    ConclusionReview,
    ResearchAnalysis,
    ReviewIssue,
    ReviewIssueType,
)
from .llm_analyzer import LlmUsage, build_openai_client, parse_usage
from .schemas import RunConfig, SourceRecord
from .validation import quote_exists


def _source_index(records: Sequence[SourceRecord]) -> Dict[str, str]:
    return {r.internal_record_id: (r.comment_text or "") for r in records}


def review_research_code(
    analysis: ResearchAnalysis,
    records: Sequence[SourceRecord],
    *,
    card_rows: Optional[Sequence[dict]] = None,
) -> ConclusionReview:
    """Deterministic checks (always run; mock/LLM review is optional enrichment)."""
    known: Set[str] = {r.internal_record_id for r in records}
    index = _source_index(records)
    issues: List[ReviewIssue] = []

    # Count consistency: dataset_summary must match code recompute if card_rows given
    if card_rows is not None:
        from .research_agent import compute_dataset_summary

        expected = compute_dataset_summary(records, list(card_rows))
        got = analysis.dataset_summary
        if (
            got.total_comments != expected.total_comments
            or got.unique_users != expected.unique_users
            or got.valid_comments != expected.valid_comments
        ):
            issues.append(
                ReviewIssue(
                    type=ReviewIssueType.COUNT_MISMATCH,
                    description=(
                        f"统计不一致: got total={got.total_comments}/users={got.unique_users}/valid={got.valid_comments}, "
                        f"expected total={expected.total_comments}/users={expected.unique_users}/valid={expected.valid_comments}"
                    ),
                )
            )
        # unique_users > valid_comments is allowed (one user multiple comments); do not flag.

    for theme in analysis.themes:
        bad = [rid for rid in theme.comment_record_ids if rid not in known]
        if bad:
            issues.append(
                ReviewIssue(
                    type=ReviewIssueType.UNSUPPORTED_CLAIM,
                    description=f"主题 {theme.theme_id} 引用不存在的 record_id",
                    related_record_ids=bad[:10],
                )
            )
        # Prefer evidence_item_id refs; representative_quotes are display-only leftovers.
        # Paraphrased quote text must NOT fail structural review — report backfills from cards.
        for quote in theme.representative_quotes:
            if not quote:
                continue
            if any(quote_exists(quote, text) for text in index.values() if text):
                continue
            issues.append(
                ReviewIssue(
                    type=ReviewIssueType.OTHER,
                    description=(
                        f"主题 {theme.theme_id} 仍含非原文 representative_quotes（已忽略，"
                        f"报告按 evidence_item_id 回填）：{quote[:40]}"
                    ),
                    related_record_ids=theme.comment_record_ids[:5],
                )
            )

    dropped = (analysis.model_draft or {}).get("dropped_evidence_refs") or []
    if dropped:
        issues.append(
            ReviewIssue(
                type=ReviewIssueType.OTHER,
                description=f"跳过无效证据引用 {len(dropped)} 条（不补写原话）",
            )
        )

    for hyp in analysis.hypothesis_assessment:
        for rid in hyp.supporting_record_ids + hyp.weakening_record_ids:
            if rid not in known:
                issues.append(
                    ReviewIssue(
                        type=ReviewIssueType.UNSUPPORTED_CLAIM,
                        description=f"{hyp.hypothesis_id} 引用不存在的 record_id={rid}",
                        related_record_ids=[rid],
                    )
                )
        if (
            hyp.conclusion.value == "supported"
            and not hyp.supporting_record_ids
        ):
            issues.append(
                ReviewIssue(
                    type=ReviewIssueType.UNSUPPORTED_CLAIM,
                    description=f"{hyp.hypothesis_id} 标为 supported 但无 supporting_record_ids",
                )
            )
        if hyp.supporting_record_ids and not hyp.weakening_record_ids:
            # Soft warning: missing counter-evidence consideration
            if hyp.conclusion.value == "supported" and len(hyp.supporting_record_ids) <= 2:
                issues.append(
                    ReviewIssue(
                        type=ReviewIssueType.MISSING_COUNTER_EVIDENCE,
                        description=f"{hyp.hypothesis_id} 仅少量支持证据且未列削弱证据，可能夸大",
                        related_record_ids=hyp.supporting_record_ids[:5],
                    )
                )

    for opp in analysis.opportunity_hypotheses:
        if (
            not opp.supporting_evidence
            and not opp.supporting_record_ids
            and not opp.supporting_evidence_refs
        ):
            issues.append(
                ReviewIssue(
                    type=ReviewIssueType.UNSUPPORTED_CLAIM,
                    description=f"机会「{opp.opportunity_name}」缺少支持证据",
                )
            )
        if len(opp.supporting_record_ids) == 1 and "普遍" in (opp.opportunity_name + "".join(opp.supporting_evidence)):
            issues.append(
                ReviewIssue(
                    type=ReviewIssueType.OVERGENERALIZATION,
                    description=f"机会「{opp.opportunity_name}」疑似把单条个案写成普遍结论",
                    related_record_ids=opp.supporting_record_ids,
                )
            )

    # Detect comment/user confusion phrases in conclusions
    for text in analysis.research_conclusions:
        if "用户" in text and "评论" in text and any(ch.isdigit() for ch in text):
            # Heuristic only when summary numbers mismatched already handled
            pass

    passed = not any(
        i.type
        in {
            ReviewIssueType.UNSUPPORTED_CLAIM,
            ReviewIssueType.COUNT_MISMATCH,
        }
        for i in issues
    )
    return ConclusionReview(structural_review_passed=passed, issues=issues, corrected_sections={})


def run_conclusion_review(
    analysis: ResearchAnalysis,
    records: Sequence[SourceRecord],
    *,
    card_rows: Optional[Sequence[dict]] = None,
    use_mock: bool = True,
    config: Optional[RunConfig] = None,
    api_key: str = "",
    client=None,
    use_llm_review: Optional[bool] = None,
) -> tuple[ConclusionReview, LlmUsage]:
    """Default: code-only checks. LLM review only when explicitly enabled."""
    base = review_research_code(analysis, records, card_rows=card_rows)
    enabled = use_llm_review
    if enabled is None:
        enabled = bool(getattr(config, "use_llm_review", False)) if config else False
    if use_mock or not api_key or not enabled:
        return base, LlmUsage()

    assert config is not None
    llm = client or build_openai_client(config.base_url, api_key)
    index = {rid: text[:120] for rid, text in _source_index(records).items() if text}
    messages = [
        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_review_user_message(
                research=analysis.model_dump(exclude={"model_draft"}),
                dataset_summary=analysis.dataset_summary.model_dump(),
                source_quote_index=index,
            ),
        },
    ]
    completion = llm.chat.completions.create(
        model=config.model_name,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    usage = parse_usage(getattr(completion, "usage", None))
    raw = completion.choices[0].message.content or ""
    try:
        payload = json.loads(raw)
        if "passed" in payload and "structural_review_passed" not in payload:
            payload["structural_review_passed"] = payload.pop("passed")
        llm_review = ConclusionReview.model_validate(payload)
    except (json.JSONDecodeError, Exception):
        return base, usage

    merged_issues = list(base.issues)
    seen = {(i.type, i.description) for i in merged_issues}
    for issue in llm_review.issues:
        key = (issue.type, issue.description)
        if key not in seen:
            merged_issues.append(issue)
            seen.add(key)
    structural_ok = base.structural_review_passed and llm_review.structural_review_passed and not any(
        i.type in {ReviewIssueType.UNSUPPORTED_CLAIM, ReviewIssueType.COUNT_MISMATCH} for i in merged_issues
    )
    return (
        ConclusionReview(
            structural_review_passed=structural_ok,
            issues=merged_issues,
            corrected_sections=llm_review.corrected_sections or {},
        ),
        usage,
    )
