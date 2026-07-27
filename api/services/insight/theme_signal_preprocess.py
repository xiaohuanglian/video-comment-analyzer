"""Deterministic preparation for the hybrid open-theme pipeline."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List

from .statistics import user_key
from .theme_clustering import collect_raw_signals


def normalize_theme_signal(text: str) -> str:
    """Normalize format noise without deleting semantics such as negation/direction."""
    value = unicodedata.normalize("NFKC", text or "").strip().lower()
    value = re.sub(r"[\U00010000-\U0010ffff]+", " [表情] ", value)
    value = re.sub(r"([!?！？。，、；;])\1{1,}", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class PreparedThemeSignal:
    prepared_id: str
    source_file: str
    normalized_text: str
    original_text: str
    signal_type: str
    frequency: int = 0
    user_keys: set[str] = field(default_factory=set)
    signal_ids: List[str] = field(default_factory=list)
    record_ids: List[str] = field(default_factory=list)
    sample_quotes: List[str] = field(default_factory=list)

    @property
    def user_count(self) -> int:
        return len(self.user_keys)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "prepared_id": self.prepared_id,
            "source_file": self.source_file,
            "normalized_text": self.normalized_text,
            "original_text": self.original_text,
            "signal_type": self.signal_type,
            "frequency": self.frequency,
            "user_count": self.user_count,
            "signal_ids": self.signal_ids,
            "record_ids": self.record_ids,
            "sample_quotes": self.sample_quotes,
        }


def prepare_theme_signals(results: List[Dict[str, Any]]) -> List[PreparedThemeSignal]:
    """Merge exact duplicates per video while retaining all evidence references."""
    raw = collect_raw_signals(results)
    grouped: Dict[tuple[str, str, str], PreparedThemeSignal] = {}
    for item in raw:
        normalized = normalize_theme_signal(item.text or item.evidence_quote)
        key = (item.source_file, item.signal_type, normalized)
        prepared = grouped.get(key)
        if prepared is None:
            digest = hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:12]
            prepared = PreparedThemeSignal(
                prepared_id=f"p_{digest}",
                source_file=item.source_file,
                normalized_text=normalized,
                original_text=item.text or item.evidence_quote,
                signal_type=item.signal_type,
            )
            grouped[key] = prepared
        prepared.frequency += max(1, item.frequency)
        if item.signal_id not in prepared.signal_ids:
            prepared.signal_ids.append(item.signal_id)
        if item.record_id not in prepared.record_ids:
            prepared.record_ids.append(item.record_id)
        if item.user_key:
            prepared.user_keys.add(item.user_key)
        for quote in item.sample_quotes or [item.evidence_quote]:
            if quote and quote not in prepared.sample_quotes and len(prepared.sample_quotes) < 3:
                prepared.sample_quotes.append(quote)
    return sorted(grouped.values(), key=lambda item: (-item.frequency, item.prepared_id))


def group_prepared_by_source(items: Iterable[PreparedThemeSignal]) -> Dict[str, List[PreparedThemeSignal]]:
    grouped: Dict[str, List[PreparedThemeSignal]] = defaultdict(list)
    for item in items:
        grouped[item.source_file].append(item)
    return dict(grouped)
