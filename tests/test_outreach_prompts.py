# -*- coding: utf-8 -*-
"""Comment-reply prompt alignment (public replies, never auto-sent)."""

from __future__ import annotations

from api.services.insight.candidate_schemas import CandidateRecord
from api.services.insight.outreach_prompts import (
    DEFAULT_BASE_TEMPLATE,
    OUTREACH_SYSTEM_PROMPT,
    build_outreach_user_message,
)


def test_default_template_is_a_reply_not_a_pitch() -> None:
    assert "回复" not in DEFAULT_BASE_TEMPLATE  # template itself is plain prose
    assert "你好" in DEFAULT_BASE_TEMPLATE
    assert "推销" in OUTREACH_SYSTEM_PROMPT


def test_system_prompt_requires_reply_and_forbids_pitch() -> None:
    assert "评论区回复" in OUTREACH_SYSTEM_PROMPT
    assert "禁止" in OUTREACH_SYSTEM_PROMPT and "推销" in OUTREACH_SYSTEM_PROMPT
    assert "导流" in OUTREACH_SYSTEM_PROMPT


def test_user_message_includes_reply_context() -> None:
    candidate = CandidateRecord(
        user_key="u1",
        username="测试用户",
        research_target_matches=["新手入门"],
        representative_quotes=["第一次用完全不知道从哪开始"],
        contact_reason="符合目标人群：新手入门",
    )
    msg = build_outreach_user_message(candidate, DEFAULT_BASE_TEMPLATE)
    assert "新手入门" in msg
    assert "第一次用完全不知道从哪开始" in msg
    assert "生成评论区回复" in msg