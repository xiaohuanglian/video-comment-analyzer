# -*- coding: utf-8 -*-
"""Shared hypothesis and signal definitions for comment insight."""

from __future__ import annotations

HYPOTHESES = {
    "H1": (
        "用户本身已经具有一定训练动力，不需要产品解决「是否开始训练」，"
        "而是需要解决训练过程和训练质量问题。"
    ),
    "H2": (
        "部分用户仅靠单向视频无法解决问题，需要动作质量即时反馈、"
        "个性化判断或交互式指导。"
    ),
    "H3": (
        "部分用户不希望自己反复判断训练安排和调整方式，"
        "希望把规划、进阶、降阶和调整交给 Agent。"
    ),
}

# Short labels for prompts (full text kept in HYPOTHESES for reports/UI)
HYPOTHESIS_SHORT = {
    "H1": "已有动力，需过程/质量支持",
    "H2": "单向视频不够，需即时反馈/个性化",
    "H3": "希望 Agent 规划/进阶/调整",
}

SIGNAL_ENUM = [
    "gratitude",
    "saved_or_plan_to_try",
    "started_training",
    "continued_training",
    "positive_result",
    "no_change",
    "negative_result",
    "applicability_question",
    "form_uncertainty",
    "cannot_complete",
    "no_target_muscle_sensation",
    "physical_discomfort",
    "injury_or_special_condition",
    "needs_substitution",
    "needs_regression",
    "needs_progression",
    "needs_training_plan",
    "pace_or_counting_problem",
    "instruction_unclear",
    "equipment_or_space_constraint",
    "privacy_concern",
    "motivation_or_accountability",
    "asks_coach_reply",
    "searched_other_content",
    "recorded_self_for_review",
    "paid_professional_help",
    "skipped_exercise",
    "stopped_training",
    "changed_training_plan",
    "other_new_signal",
]

