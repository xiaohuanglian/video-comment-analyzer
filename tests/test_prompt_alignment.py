# -*- coding: utf-8 -*-
"""Ensure analysis prompts match product spec."""

from api.services.insight.prompts import HYPOTHESES, PROMPT_VERSION, SYSTEM_PROMPT


def test_prompt_version_bumped_for_hypothesis_fix():
    assert PROMPT_VERSION == "comment_analysis_v4"


def test_hypotheses_match_product_spec():
    assert "训练动力" in HYPOTHESES["H1"]
    assert "单向视频无法" in HYPOTHESES["H2"]
    assert "Agent" in HYPOTHESES["H3"] or "规划" in HYPOTHESES["H3"]
    assert "伤病" not in HYPOTHESES["H1"]
    assert "轻量" not in HYPOTHESES["H3"]


def test_system_prompt_includes_guardrails():
    assert "不得迎合预设" in SYSTEM_PROMPT or "迎合" in SYSTEM_PROMPT
    assert "one_reply_sufficient" in SYSTEM_PROMPT
    assert "weakens" in SYSTEM_PROMPT
    assert "signals" in SYSTEM_PROMPT


def test_system_prompt_is_token_lean():
    # v4 adds stricter hypothesis rules but should stay compact
    assert len(SYSTEM_PROMPT) < 2800
