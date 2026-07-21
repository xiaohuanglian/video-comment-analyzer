# -*- coding: utf-8 -*-
"""Schemas for potential user candidates and outreach drafts."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ContactStatus = Literal[
    "not_contacted",
    "preparing",
    "contacted",
    "replied",
    "interview_agreed",
    "declined",
    "no_reply",
    "interview_completed",
]

CONTACT_STATUS_LABELS = {
    "not_contacted": "未联系",
    "preparing": "准备中",
    "contacted": "已联系",
    "replied": "已回复",
    "interview_agreed": "同意访谈",
    "declined": "已拒绝",
    "no_reply": "无回复",
    "interview_completed": "访谈完成",
}

Priority = Literal["high", "medium", "low"]
ContactabilityLevel = Literal["high", "medium", "low"]


class CandidateComment(BaseModel):
    record_id: str
    comment_text: str
    video_title: str = ""
    creator_name: str = ""
    comment_url: str = ""
    analyzed_at: str = ""


class CandidateRecord(BaseModel):
    user_key: str
    username: str = ""
    platform: str = ""
    creator_type: str = ""
    homepage_url: str = ""
    comment_urls: List[str] = Field(default_factory=list)
    record_ids: List[str] = Field(default_factory=list)
    comments: List[CandidateComment] = Field(default_factory=list)
    candidate_score: int = 0
    priority: Priority = "low"
    contactability: ContactabilityLevel = "low"
    specific_problems: List[str] = Field(default_factory=list)
    single_video_relations: List[str] = Field(default_factory=list)
    product_fit: str = "unclear"
    actual_training_evidence: str = "none"
    help_seeking: bool = False
    representative_quotes: List[str] = Field(default_factory=list)
    contact_reason: str = ""
    score_breakdown: List[str] = Field(default_factory=list)
    research_target_matches: List[str] = Field(default_factory=list)
    research_relevance_score: int = 0
    contact_status: ContactStatus = "not_contacted"
    product_manager_note: str = ""


class CandidatesDocument(BaseModel):
    generated_at: str = ""
    total_candidates: int = 0
    candidates: List[CandidateRecord] = Field(default_factory=list)


class OutreachEntry(BaseModel):
    user_key: str
    username: str = ""
    base_template: str = ""
    generated_draft: str = ""
    edited_content: str = ""
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    generated_at: str = ""
    contact_status: ContactStatus = "preparing"
    product_manager_note: str = ""


class OutreachDocument(BaseModel):
    updated_at: str = ""
    entries: List[OutreachEntry] = Field(default_factory=list)
