# -*- coding: utf-8 -*-
"""Display labels for insight enums (shared by UI export and reports)."""

from __future__ import annotations

INTENT_LABELS = {
    "gratitude_recognition": "感谢与认可",
    "check_in": "签到",
    "result_feedback": "结果反馈",
    "question": "提问",
    "difficulty_help_request": "困难求助",
    "complaint": "不满",
    "other_valid": "其他有效",
    "invalid_or_unclear": "无效/不明",
}

SIGNAL_LABELS = {
    "gratitude": "表达感谢",
    "saved_or_plan_to_try": "收藏或准备尝试",
    "started_using": "已开始使用",
    "continued_using": "持续使用",
    "positive_result": "正向结果反馈",
    "no_change": "无变化",
    "negative_result": "负向结果反馈",
    "applicability_question": "适用性提问",
    "howto_uncertainty": "执行方式不确定",
    "cannot_complete": "无法完成",
    "expected_effect_missing": "未达到预期效果",
    "physical_discomfort": "身体不适",
    "special_condition": "特殊身体状况",
    "needs_alternative": "需要替代方案",
    "needs_simpler": "需要降低难度/简化",
    "needs_advanced": "需要进阶",
    "needs_plan": "需要规划",
    "pace_problem": "节奏或操作问题",
    "instruction_unclear": "讲解不清楚",
    "resource_constraint": "设备/空间等条件限制",
    "privacy_concern": "隐私顾虑",
    "motivation_or_accountability": "需要督促或陪伴",
    "asks_creator_reply": "希望作者回复",
    "searched_other_content": "搜索其他内容",
    "recorded_self_for_review": "录像自我回看",
    "paid_professional_help": "付费专业帮助",
    "skipped_step": "跳过步骤",
    "stopped_using": "停止使用",
    "changed_plan": "调整方案",
    "other_new_signal": "其他新信号",
}

SINGLE_VIDEO_LABELS = {
    "video_sufficient": "视频本身足够",
    "one_reply_sufficient": "一次回复即可",
    "personalized_judgment_needed": "需个性化判断",
    "realtime_observation_needed": "需实时观察",
    "unclear": "证据不足，无法判断",
}

PRODUCT_FIT_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "unclear": "不明",
}

HYPOTHESIS_RELATION_LABELS = {
    "supports": "支持",
    "weakens": "削弱",
    "insufficient": "证据不足，无法判断",
    "irrelevant": "无关",
}

TRAINING_EVIDENCE_LABELS = {
    "none": "无行为证据",
    "planned": "计划尝试",
    "tried": "已尝试",
    "continued": "持续进行",
}


def label_intent(key: str) -> str:
    return INTENT_LABELS.get(key, key)


def label_signal(key: str) -> str:
    return SIGNAL_LABELS.get(key, key)


def label_single_video(key: str) -> str:
    return SINGLE_VIDEO_LABELS.get(key, key)


def label_product_fit(key: str) -> str:
    return PRODUCT_FIT_LABELS.get(key, key)


def label_hypothesis_relation(key: str) -> str:
    return HYPOTHESIS_RELATION_LABELS.get(key, key)
