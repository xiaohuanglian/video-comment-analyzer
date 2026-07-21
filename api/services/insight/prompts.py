# -*- coding: utf-8 -*-
"""Prompt templates for comment insight LLM analysis (token-lean)."""

from __future__ import annotations

from .schemas import SourceRecord

PROMPT_VERSION = "comment_analysis_v4"

# Max chars for parent / creator reply attached to user message
_CONTEXT_CHAR_LIMIT = 240

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

KNOWN_SCENES = {
    "S1": "运动损伤恢复中后期、重返运动和居家维持",
    "S2": "青少年篮球的家庭陪练和基本功训练",
    "S3": "产后恢复、隐私空间和碎片化训练",
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

# Compact system prompt: ~一半体积，保留硬约束与枚举
SYSTEM_PROMPT = """你是居家运动虚拟教练产品的评论分析师。输出唯一 JSON（勿 Markdown）。

## 假设（每条须给 relation；irrelevant 可无空 evidence_quote）
- H1：{h1}
- H2：{h2}
- H3：{h3}

## 场景（仅明确相关时写入 known_scene_matches）
S1 伤后居家维持 | S2 青少年家庭陪练 | S3 产后碎片化/隐私

## 硬规则
- supports/weakens 必须有逐字 evidence_quote；不确定→insufficient/irrelevant，不得迎合预设。
- H1 supports：已有动力，且谈到过程/质量/计划/动作问题；纯动作细节提问、纯感谢、玩笑≠supports。
- H1 weakens：核心是没动力/坚持不了/懒得练；练得很累但在坚持≠weakens。
- H2 supports：明确要看动作纠错/实时观察/个性化判断；普通问答「一周几次」→one_reply_sufficient，勿 H2 supports。
- H2 weakens：看视频/跟练已够，或一次文字回复可解决。
- H3 supports：明确希望代安排计划/进阶/调整；不会安排练什么才更可能 supports。
- 感谢、自嘲、热血打卡默认 irrelevant/insufficient。
- 勿医学诊断；勿臆测年龄/性别/付费；收藏≠真实训练。
- product_fit_reason、single_video_limitation_summary ≤40 中文字；confidence 0~1。
- new_signals 仅在固定标签无法覆盖时输出。

## 枚举
primary_intent(单选): gratitude_recognition|check_in|result_feedback|question|difficulty_help_request|complaint|other_valid|invalid_or_unclear
（有感谢也提问→question/difficulty_help_request）
signals(多选): {signals}
actual_training_evidence: none|planned|tried|continued
training_impact: none|unclear|skipped|stopped|changed_plan|paid_help
single_video_relation: video_sufficient|one_reply_sufficient|personalized_judgment_needed|realtime_observation_needed|unclear
product_fit: high|medium|low|unclear
hypothesis.relation: supports|weakens|insufficient|irrelevant
new_signal.type: new_user_segment|new_problem|new_scene|new_barrier|new_motivation|new_current_solution|new_product_expectation|other

## JSON 字段
primary_intent, signals[], explicit_user_context[], exercise_mentions[], specific_problems[],
actual_training_evidence, current_workarounds[], help_seeking(true|false 勿填字符串/数组), behavior_costs[], training_impact,
single_video_relation, single_video_limitation_summary,
hypothesis_relations[{{hypothesis_id, relation, evidence_quote}}],
known_scene_matches[], new_signals[{{type, text, evidence_quote}}], potential_needs[],
product_fit, product_fit_reason, evidence_quotes[], confidence
无内容用 [] 或 ""。
""".format(
    h1=HYPOTHESIS_SHORT["H1"],
    h2=HYPOTHESIS_SHORT["H2"],
    h3=HYPOTHESIS_SHORT["H3"],
    signals=",".join(SIGNAL_ENUM),
)

# Kept for backward-compatible imports; content folded into SYSTEM_PROMPT.
JSON_OUTPUT_INSTRUCTION = ""


def _clip(text: str, limit: int = _CONTEXT_CHAR_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_user_message(record: SourceRecord, research_targets: list[str] | None = None) -> str:
    """Comment + truncated context. research_targets intentionally unused (offline matching)."""
    del research_targets  # keep signature; do not inject into every LLM call
    parts = [record.comment_text.strip()]
    parent = _clip(record.parent_comment)
    if parent:
        parts.extend(["", "【父评论】", parent])
    reply = _clip(record.creator_reply)
    if reply:
        parts.extend(["", "【博主回复】", reply])
    return "\n".join(parts)
