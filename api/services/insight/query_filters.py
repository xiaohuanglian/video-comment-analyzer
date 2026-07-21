# -*- coding: utf-8 -*-
"""Server-side filtering and pagination for insight results and candidates."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .candidate_schemas import CandidateRecord
from .statistics import VALID_INTENTS


def _row_analysis(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("analysis") or {}


def _row_source(row: Dict[str, Any]) -> Dict[str, Any]:
    return row.get("source") or {}


def match_result_row(
    row: Dict[str, Any],
    *,
    keyword: str = "",
    primary_intent: str = "",
    intent_valid: bool = False,
    signal: str = "",
    single_video_relation: str = "",
    product_fit: str = "",
    hypothesis_id: str = "",
    hypothesis_relation: str = "",
    has_new_signal: Optional[bool] = None,
    theme_record_ids: Optional[set[str]] = None,
    record_ids: Optional[set[str]] = None,
) -> bool:
    analysis = _row_analysis(row)
    source = _row_source(row)
    record_id = str(row.get("record_id") or analysis.get("record_id") or "")

    allowed_ids = theme_record_ids or record_ids
    if allowed_ids is not None and record_id not in allowed_ids:
        return False

    if intent_valid:
        intent = analysis.get("primary_intent") or ""
        if intent not in VALID_INTENTS:
            return False

    if primary_intent and (analysis.get("primary_intent") or "") != primary_intent:
        return False

    if signal and signal not in (analysis.get("signals") or []):
        return False

    if single_video_relation and (analysis.get("single_video_relation") or "") != single_video_relation:
        return False

    if product_fit and (analysis.get("product_fit") or "") != product_fit:
        return False

    if hypothesis_id:
        relations = analysis.get("hypothesis_relations") or []
        matched = False
        for item in relations:
            if not isinstance(item, dict):
                continue
            if item.get("hypothesis_id") != hypothesis_id:
                continue
            if hypothesis_relation and item.get("relation") != hypothesis_relation:
                continue
            matched = True
            break
        if not matched:
            return False

    if has_new_signal is True and not (analysis.get("new_signals") or []):
        return False
    if has_new_signal is False and (analysis.get("new_signals") or []):
        return False

    if keyword:
        haystack = " ".join(
            [
                str(source.get("comment_text") or ""),
                str(source.get("username") or ""),
                str(source.get("video_title") or ""),
            ]
        ).lower()
        if keyword.lower() not in haystack:
            return False

    return True


def paginate_results(
    rows: List[Dict[str, Any]],
    *,
    page: int = 1,
    page_size: int = 100,
    **filters: Any,
) -> Dict[str, Any]:
    theme_ids = filters.pop("theme_record_ids", None)
    record_ids = filters.pop("record_ids", None)
    theme_set = set(theme_ids) if theme_ids else None
    id_set = set(record_ids) if record_ids else theme_set
    filtered = [row for row in rows if match_result_row(row, record_ids=id_set, **filters)]
    total = len(filtered)
    page = max(1, page)
    page_size = max(1, min(page_size, 500))
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": filtered[start:end],
    }


def match_candidate(
    candidate: CandidateRecord,
    *,
    priority: str = "",
    contactability: str = "",
    platform: str = "",
    product_fit: str = "",
    contact_status: str = "",
    research_matched: str = "",
) -> bool:
    if priority and candidate.priority != priority:
        return False
    if contactability and candidate.contactability != contactability:
        return False
    if platform and candidate.platform != platform:
        return False
    if product_fit and candidate.product_fit != product_fit:
        return False
    if contact_status and candidate.contact_status != contact_status:
        return False
    if research_matched == "yes" and not candidate.research_target_matches:
        return False
    if research_matched == "no" and candidate.research_target_matches:
        return False
    return True


def paginate_candidates(
    candidates: List[CandidateRecord],
    *,
    page: int = 1,
    page_size: int = 50,
    **filters: Any,
) -> Dict[str, Any]:
    filtered = [item for item in candidates if match_candidate(item, **filters)]
    total = len(filtered)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [item.model_dump() for item in filtered[start:end]],
    }
