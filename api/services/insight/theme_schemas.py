# -*- coding: utf-8 -*-
"""Schemas for open-theme clustering (checkpoint C)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

PROMPT_VERSION = "theme_clustering_v1"

ThemeRelation = Literal[
    "supports_existing",
    "extends_existing",
    "weakens_existing",
    "unrelated_notable",
]

THEME_RELATION_LABELS = {
    "supports_existing": "支持已有假设的新证据",
    "extends_existing": "扩展已有假设的新发现",
    "weakens_existing": "削弱已有假设的新发现",
    "unrelated_notable": "与已有假设无关但值得注意",
}


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
    theme_name: str
    theme_type: str
    definition: str
    included_signal_ids: List[str] = Field(default_factory=list)
    relation_to_existing_hypotheses: ThemeRelation = "extends_existing"
    implication: str = ""
    confidence: float = 0.0


class Round1ResponseLLM(BaseModel):
    candidate_themes: List[CandidateThemeLLM] = Field(default_factory=list)


class Round2ThemeLLM(BaseModel):
    theme_name: str
    theme_type: str
    definition: str
    included_signal_ids: List[str] = Field(default_factory=list)
    relation_to_existing_hypotheses: ThemeRelation = "extends_existing"
    implication: str = ""
    confidence: float = 0.0


class Round2ResponseLLM(BaseModel):
    themes: List[Round2ThemeLLM] = Field(default_factory=list)


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
    model_name: str = ""
    created_at: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    raw_signal_count: int = 0
    themes: List[ThemeRecord] = Field(default_factory=list)
