# -*- coding: utf-8 -*-
"""Outreach prompt alignment with validation interview plan."""

from __future__ import annotations

from api.services.insight.candidate_schemas import CandidateRecord
from api.services.insight.outreach_prompts import (
    BETA_INCENTIVE_PHRASE,
    DEFAULT_BASE_TEMPLATE,
    OUTREACH_SYSTEM_PROMPT,
    build_outreach_user_message,
)


def test_default_template_mentions_mom_test_and_beta() -> None:
    assert "在家" in DEFAULT_BASE_TEMPLATE
    assert "内测" in DEFAULT_BASE_TEMPLATE
    assert "推销" in DEFAULT_BASE_TEMPLATE


def test_system_prompt_forbids_product_pitch_and_requires_beta_incentive() -> None:
    assert "Mom Test" in OUTREACH_SYSTEM_PROMPT
    assert BETA_INCENTIVE_PHRASE in OUTREACH_SYSTEM_PROMPT
    assert "禁止" in OUTREACH_SYSTEM_PROMPT and "推销" in OUTREACH_SYSTEM_PROMPT


def test_user_message_includes_segment_angle() -> None:
    candidate = CandidateRecord(
        user_key="u1",
        username="测试用户",
        research_target_matches=["运动损伤"],
        representative_quotes=["膝盖术后在家练深蹲"],
        contact_reason="符合调研对象：运动损伤",
    )
    msg = build_outreach_user_message(candidate, DEFAULT_BASE_TEMPLATE)
    assert "运动损伤" in msg
    assert "二次受伤" in msg or "康复" in msg
    # 内测话术放在 system prompt，user 侧不再重复注入
