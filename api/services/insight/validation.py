# -*- coding: utf-8 -*-
"""Validate analysis output against source text."""

from __future__ import annotations

from typing import List

from .schemas import (
    CommentAnalysisResult,
    HypothesisRelation,
    HypothesisRelationType,
    NewSignal,
    SourceRecord,
)


def source_text_pool(record: SourceRecord) -> str:
    parts = [record.comment_text, record.parent_comment, record.creator_reply]
    return "\n".join(part for part in parts if part)


def quote_exists(quote: str, pool: str) -> bool:
    if not quote:
        return True
    normalized_quote = quote.strip()
    if normalized_quote in pool:
        return True
    # Allow matching when whitespace differs slightly.
    compact_quote = normalized_quote.replace(" ", "")
    compact_pool = pool.replace(" ", "")
    return compact_quote in compact_pool


def _best_evidence_quote(text: str, pool: str, *, limit: int = 48) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if quote_exists(text, pool):
        return text[:limit]
    # Try longest substring of text that appears in pool.
    for length in range(min(len(text), limit), 3, -1):
        for start in range(0, len(text) - length + 1):
            fragment = text[start : start + length]
            if quote_exists(fragment, pool):
                return fragment
    return ""


def sanitize_new_signals(record: SourceRecord, analysis: CommentAnalysisResult) -> CommentAnalysisResult:
    """Drop or repair new_signals with invalid evidence instead of failing the whole record."""
    pool = source_text_pool(record)
    cleaned: List[NewSignal] = []
    for signal in analysis.new_signals:
        quote = (signal.evidence_quote or "").strip()
        if quote and quote_exists(quote, pool):
            cleaned.append(signal)
            continue
        repaired = _best_evidence_quote(signal.text, pool) or _best_evidence_quote(quote, pool)
        if repaired:
            cleaned.append(
                NewSignal(
                    type=signal.type,
                    text=signal.text,
                    evidence_quote=repaired,
                )
            )
            continue
        # Paraphrased summary with no verbatim anchor — drop silently.
    analysis.new_signals = cleaned
    return analysis


def sanitize_specific_problems(record: SourceRecord, analysis: CommentAnalysisResult) -> CommentAnalysisResult:
    """Keep problems that appear in source text; repair paraphrases to best verbatim fragment."""
    pool = source_text_pool(record)
    cleaned: List[str] = []
    for problem in analysis.specific_problems or []:
        text = str(problem or "").strip()
        if not text:
            continue
        if quote_exists(text, pool):
            cleaned.append(text)
            continue
        repaired = _best_evidence_quote(text, pool, limit=64)
        if repaired:
            cleaned.append(repaired)
    analysis.specific_problems = cleaned
    return analysis


def sanitize_evidence_quotes(record: SourceRecord, analysis: CommentAnalysisResult) -> CommentAnalysisResult:
    """Drop invalid top-level evidence quotes; never fail the whole record for them."""
    pool = source_text_pool(record)
    cleaned: List[str] = []
    for quote in analysis.evidence_quotes or []:
        text = str(quote or "").strip()
        if not text:
            continue
        if quote_exists(text, pool):
            cleaned.append(text)
            continue
        repaired = _best_evidence_quote(text, pool)
        if repaired:
            cleaned.append(repaired)
    analysis.evidence_quotes = cleaned
    return analysis


def sanitize_hypothesis_relations(record: SourceRecord, analysis: CommentAnalysisResult) -> CommentAnalysisResult:
    """Repair bad supports/weakens evidence; demote to insufficient instead of failing."""
    pool = source_text_pool(record)
    cleaned: List[HypothesisRelation] = []
    for relation in analysis.hypothesis_relations or []:
        rel = relation.relation
        quote = (relation.evidence_quote or "").strip()
        if rel in {HypothesisRelationType.SUPPORTS, HypothesisRelationType.WEAKENS}:
            if quote and quote_exists(quote, pool):
                cleaned.append(relation)
                continue
            repaired = _best_evidence_quote(quote, pool)
            if repaired:
                cleaned.append(
                    HypothesisRelation(
                        hypothesis_id=relation.hypothesis_id,
                        relation=rel,
                        evidence_quote=repaired,
                    )
                )
                continue
            # Paid tokens already — keep signal as insufficient rather than discard whole analysis
            cleaned.append(
                HypothesisRelation(
                    hypothesis_id=relation.hypothesis_id,
                    relation=HypothesisRelationType.INSUFFICIENT,
                    evidence_quote="",
                )
            )
            continue
        cleaned.append(relation)
    analysis.hypothesis_relations = cleaned
    return analysis


def validate_analysis(record: SourceRecord, analysis: CommentAnalysisResult) -> None:
    analysis = sanitize_new_signals(record, analysis)
    analysis = sanitize_specific_problems(record, analysis)
    analysis = sanitize_evidence_quotes(record, analysis)
    analysis = sanitize_hypothesis_relations(record, analysis)
    if len(analysis.product_fit_reason) > 40:
        raise ValueError("product_fit_reason 超过 40 字")
    if len(analysis.single_video_limitation_summary) > 40:
        raise ValueError("single_video_limitation_summary 超过 40 字")
