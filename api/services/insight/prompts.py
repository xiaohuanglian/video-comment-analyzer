# -*- coding: utf-8 -*-
"""Shared hypothesis and signal definitions for comment insight.

These are domain-neutral defaults. Projects override the hypotheses (and the
research context/rules) via a project profile; see ``project_profiles.py``.
"""

from __future__ import annotations

HYPOTHESES = {
    "H1": "用户存在明确、反复出现的未满足需求（而非一次性好奇）。",
    "H2": "现有替代方案（竞品/自建方案/人工服务）无法很好地满足该需求。",
    "H3": "部分用户愿意为更好的解决方案付出成本（时间、学习或金钱）。",
}

# Short labels for prompts (full text kept in HYPOTHESES for reports/UI)
HYPOTHESIS_SHORT = {
    "H1": "存在反复出现的未满足需求",
    "H2": "现有替代方案不够好",
    "H3": "存在付费/投入意愿",
}

# Domain-neutral signal vocabulary (behavioral + intent), consumed by
# statistics, filters, reports and exports.
SIGNAL_ENUM = [
    "gratitude",
    "saved_or_plan_to_try",
    "started_using",
    "continued_using",
    "positive_result",
    "no_change",
    "negative_result",
    "applicability_question",
    "howto_uncertainty",
    "cannot_complete",
    "expected_effect_missing",
    "physical_discomfort",
    "special_condition",
    "needs_alternative",
    "needs_simpler",
    "needs_advanced",
    "needs_plan",
    "pace_problem",
    "instruction_unclear",
    "resource_constraint",
    "privacy_concern",
    "motivation_or_accountability",
    "asks_creator_reply",
    "searched_other_content",
    "recorded_self_for_review",
    "paid_professional_help",
    "skipped_step",
    "stopped_using",
    "changed_plan",
    "other_new_signal",
]

# Default keyword pools for the "一次回复能否解决" rule-based projection.
# Projects can override them in their profile (realtime_tokens /
# personalized_tokens / positive_result_tokens).
REALTIME_VIDEO_KEYWORDS = (
    "帮我看",
    "看看我",
    "不标准",
    "做得不对",
    "哪里不对",
    "标准吗",
    "做得对吗",
    "帮我检查",
    "找不到感觉",
    "感觉不到",
)
PERSONALIZED_VIDEO_KEYWORDS = (
    "判断",
    "分不清",
    "方向",
    "怎么测",
    "怎么看",
    "适合我",
    "因人而异",
    "受伤",
    "疼痛",
)
POSITIVE_RESULT_KEYWORDS = (
    "立竿见影",
    "有效果",
    "改善了",
    "舒服",
    "回正",
    "成功了",
    "矫正成功",
    "明显",
    "没以前",
    "好转",
)