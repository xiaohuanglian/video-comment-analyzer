# -*- coding: utf-8 -*-
"""In-process cache: identical comment text reuses LLM analysis (zero extra tokens)."""

from __future__ import annotations

import hashlib
from typing import Dict, Optional

from .prompts import PROMPT_VERSION
from .schemas import CommentAnalysisResult, SourceRecord

_cache: Dict[str, CommentAnalysisResult] = {}


def content_fingerprint(record: SourceRecord) -> str:
    raw = "\n".join(
        [
            PROMPT_VERSION,
            (record.comment_text or "").strip(),
            (record.parent_comment or "").strip(),
            (record.creator_reply or "").strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_cached_analysis(fingerprint: str) -> Optional[CommentAnalysisResult]:
    hit = _cache.get(fingerprint)
    if hit is None:
        return None
    return hit.model_copy(deep=True)


def put_cached_analysis(fingerprint: str, analysis: CommentAnalysisResult) -> None:
    # Store without binding to a specific record_id
    stored = analysis.model_copy(deep=True)
    _cache[fingerprint] = stored


def clear_result_cache() -> None:
    _cache.clear()
