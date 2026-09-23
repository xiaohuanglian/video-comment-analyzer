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
    "interview_agreed": "已深度互动",
    "declined": "已拒绝",
    "no_reply": "无回复",
    "interview_completed": "已跟进",
}

Priority = Literal["high", "medium", "low"]
ContactabilityLevel = Literal["high", "medium", "low"]

# Human gate on the generated draft: only `approved` entries may be sent.
ReviewStatus = Literal["draft", "approved", "rejected"]
# Execution state of a reply once the user starts the controlled reply run.
SendStatus = Literal["pending", "queued", "sending", "sent", "failed", "skipped"]
ReplyRunStatus = Literal["idle", "running", "stopping", "stopped", "completed", "failed"]


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
    # --- human gate + controlled send -------------------------------------
    review_status: ReviewStatus = "draft"
    reviewed_at: str = ""
    platform: str = ""
    # Target identifiers resolved from the candidate's source records so a
    # sender can post the reply without guessing.
    target_content_id: str = ""  # e.g. bilibili video id / note id
    target_comment_id: str = ""  # the comment being replied to
    send_status: SendStatus = "pending"
    sent_at: str = ""
    send_error: str = ""
    attempts: int = 0

    @property
    def final_content(self) -> str:
        """The exact text that will be posted (edited draft wins)."""
        return (self.edited_content or self.generated_draft or "").strip()


class ReplyControl(BaseModel):
    """Frequency / timing guardrails for the controlled reply run."""

    interval_seconds: int = Field(default=90, ge=10, le=86400, description="两条回复之间的最小间隔秒数")
    jitter_seconds: int = Field(default=20, ge=0, le=3600, description="随机抖动秒数，避免固定节奏")
    daily_limit: int = Field(default=30, ge=1, le=500, description="单个自然日内最多发送条数")
    time_window_start: str = Field(default="09:00", description="允许发送的起始时间 HH:MM")
    time_window_end: str = Field(default="22:00", description="允许发送的结束时间 HH:MM")

    @property
    def window_minutes(self) -> tuple[int, int]:
        def _parse(value: str) -> int:
            try:
                hh, mm = str(value).split(":", 1)
                return max(0, min(23, int(hh))) * 60 + max(0, min(59, int(mm)))
            except (ValueError, AttributeError):
                return 0

        return _parse(self.time_window_start), _parse(self.time_window_end)


class OutreachDocument(BaseModel):
    updated_at: str = ""
    entries: List[OutreachEntry] = Field(default_factory=list)
    # --- controlled reply run state ---------------------------------------
    reply_control: ReplyControl = Field(default_factory=ReplyControl)
    reply_status: ReplyRunStatus = "idle"
    reply_started_at: str = ""
    reply_finished_at: str = ""
    last_reply_at: str = ""
    reply_message: str = ""
    replies_sent_today: int = 0
    replies_today_date: str = ""
