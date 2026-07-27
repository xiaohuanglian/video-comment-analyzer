# -*- coding: utf-8 -*-
"""Schemas for open-theme clustering (checkpoint C)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

PROMPT_VERSION = "theme_clustering_v1"

ThemeRelation = Literal[
    "supports_existing",
    "extends_existing",
    "weakens_existing",
    "unrelated_notable",
]

THEME_RELATION_LABELS = {
    "supports_existing": "与已有主题一致",
    "extends_existing": "新发现",
    "weakens_existing": "与常见判断不一致",
    "unrelated_notable": "独立值得关注",
}

_THEME_TYPE_ALIASES = {
    "type": "theme_type",
    "themeType": "theme_type",
    "name": "theme_name",
    "themeName": "theme_name",
    "def": "definition",
    "desc": "definition",
    "description": "definition",
    "signal_ids": "included_signal_ids",
    "signals": "included_signal_ids",
    "relation": "relation_to_existing_hypotheses",
}


def _coerce_signal_id_list(value: Any) -> List[str]:
    """LLM often returns bare ints (3401) instead of id strings ('s3401')."""
    if value is None:
        return []
    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if item is None:
            continue
        if isinstance(item, bool):
            continue
        if isinstance(item, float) and item.is_integer():
            item = int(item)
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _normalize_theme_payload(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    normalized = dict(data)
    for alias, canonical in _THEME_TYPE_ALIASES.items():
        if canonical not in normalized and alias in normalized:
            normalized[canonical] = normalized[alias]
    if "included_signal_ids" in normalized:
        normalized["included_signal_ids"] = _coerce_signal_id_list(
            normalized.get("included_signal_ids")
        )
    if not str(normalized.get("theme_type") or "").strip():
        normalized["theme_type"] = "other"
    if not str(normalized.get("definition") or "").strip():
        normalized["definition"] = str(normalized.get("theme_name") or "开放主题")
    if not str(normalized.get("theme_name") or "").strip():
        normalized["theme_name"] = "未命名主题"
    relation = normalized.get("relation_to_existing_hypotheses")
    if relation not in THEME_RELATION_LABELS:
        normalized["relation_to_existing_hypotheses"] = "extends_existing"
    return normalized


class RawSignalItem(BaseModel):
    signal_id: str
    record_id: str
    signal_type: str
    text: str
    evidence_quote: str
    username: str = ""
    user_key: Optional[str] = None
    platform: str = ""
    creator_type: str = ""
    creator_name: str = ""
    video_title: str = ""
    source_file: str = ""
    frequency: int = 1
    sample_quotes: List[str] = Field(default_factory=list)


class CandidateThemeLLM(BaseModel):
    theme_name: str = "未命名主题"
    theme_type: str = "other"
    definition: str = ""
    included_signal_ids: List[str] = Field(default_factory=list)
    relation_to_existing_hypotheses: ThemeRelation = "extends_existing"
    implication: str = ""
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def coerce_missing_fields(cls, data: Any) -> Any:
        return _normalize_theme_payload(data)

    @field_validator("included_signal_ids", mode="before")
    @classmethod
    def coerce_signal_ids(cls, value: Any) -> List[str]:
        return _coerce_signal_id_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


class Round1ResponseLLM(BaseModel):
    candidate_themes: List[CandidateThemeLLM] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_list_root(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"candidate_themes": data}
        if isinstance(data, dict) and "candidate_themes" not in data:
            for key in ("themes", "candidates", "items"):
                if isinstance(data.get(key), list):
                    return {"candidate_themes": data[key]}
        return data


class Round2ThemeLLM(BaseModel):
    theme_name: str = "未命名主题"
    theme_type: str = "other"
    definition: str = ""
    included_signal_ids: List[str] = Field(default_factory=list)
    relation_to_existing_hypotheses: ThemeRelation = "extends_existing"
    implication: str = ""
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def coerce_missing_fields(cls, data: Any) -> Any:
        return _normalize_theme_payload(data)

    @field_validator("included_signal_ids", mode="before")
    @classmethod
    def coerce_signal_ids(cls, value: Any) -> List[str]:
        return _coerce_signal_id_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def coerce_confidence(cls, value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0


class Round2ResponseLLM(BaseModel):
    themes: List[Round2ThemeLLM] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def coerce_list_root(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"themes": data}
        if isinstance(data, dict) and "themes" not in data:
            for key in ("candidate_themes", "candidates", "items"):
                if isinstance(data.get(key), list):
                    return {"themes": data[key]}
        return data


class ThemeStats(BaseModel):
    comment_count: int = 0
    unique_user_count: int = 0
    source_file_count: int = 0
    video_count: int = 0
    creator_count: int = 0
    platform_counts: Dict[str, int] = Field(default_factory=dict)
    creator_type_counts: Dict[str, int] = Field(default_factory=dict)


class ThemeRecord(BaseModel):
    theme_id: str
    theme_name: str
    theme_type: str
    definition: str
    included_signal_ids: List[str] = Field(default_factory=list)
    record_ids: List[str] = Field(default_factory=list)
    relation_to_existing_hypotheses: ThemeRelation = "extends_existing"
    implication: str = ""
    confidence: float = 0.0
    stats: ThemeStats = Field(default_factory=ThemeStats)
    representative_quotes: List[str] = Field(default_factory=list)


class ThemesDocument(BaseModel):
    prompt_version: str = PROMPT_VERSION
    engine: str = "legacy_llm_v1"
    model_name: str = ""
    created_at: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    raw_signal_count: int = 0
    themes: List[ThemeRecord] = Field(default_factory=list)
    cluster_metadata: Dict[str, Any] = Field(default_factory=dict)
    quality_metrics: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
