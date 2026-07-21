# -*- coding: utf-8 -*-
"""Evidence-card cache with context-aware fingerprint (no cross-context reuse)."""

from __future__ import annotations

import hashlib
from typing import Dict, Optional

from .evidence_schemas import EVIDENCE_PROMPT_VERSION, EvidenceCard, RecordStatus
from .schemas import SourceRecord

_cache: Dict[str, EvidenceCard] = {}


def evidence_fingerprint(
    record: SourceRecord,
    *,
    prompt_version: str = EVIDENCE_PROMPT_VERSION,
    project_version: str = "1",
    model_name: str = "",
    project_context_compact: str = "",
) -> str:
    raw = "\n".join(
        [
            prompt_version,
            project_version,
            (model_name or "").strip(),
            hashlib.sha1((project_context_compact or "").encode("utf-8")).hexdigest()[:16],
            (record.comment_text or "").strip(),
            (record.parent_comment or "").strip(),
            (record.creator_reply or "").strip(),
            (record.video_title or "").strip(),
            (record.creator_type or "").strip(),
            (record.platform or "").strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get_cached_evidence(fingerprint: str) -> Optional[EvidenceCard]:
    hit = _cache.get(fingerprint)
    if hit is None:
        return None
    return hit.model_copy(deep=True)


def put_cached_evidence(fingerprint: str, card: EvidenceCard) -> None:
    """Cache only non-empty usable cards or excluded statuses (avoid poisoning with holes)."""
    if card.record_status == RecordStatus.USABLE and not (card.evidence_items or []):
        return
    stored = card.model_copy(deep=True)
    stored.reused_from_record_id = ""
    _cache[fingerprint] = stored


def clear_evidence_cache() -> None:
    _cache.clear()
