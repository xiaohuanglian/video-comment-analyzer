# -*- coding: utf-8 -*-
"""Prompts for personalized outreach message drafts (token-lean)."""

from __future__ import annotations

import json

from .candidate_schemas import CandidateRecord

# 与 docs/产品验证计划.md、docs/虚拟教练 B2B2C 商业访谈与验证计划.md 对齐
INTERVIEW_PURPOSE = (
    "我们在做「居家训练/康复动作反馈」的用户研究（B2B2C 验证阶段），"
    "想了解用户在家真实练习时的场景、顾虑与替代做法，用于改进产品方向。"
    "这是 Mom Test 式访谈：只聊过去实际怎么做的，不问「你觉得这个功能好不好」。"
)

# 内测权益表述：用户明确为「待定」，话术里可提但不承诺具体形式/时间
BETA_INCENTIVE_PHRASE = (
    "参与简短交流的用户，会优先获得内测体验资格（具体形式与时间待定，以实际通知为准）"
)

DEFAULT_BASE_TEMPLATE = (
    "你好，我们在做居家训练与动作反馈相关的用户研究。"
    "看到你在评论区分享了真实经历，想邀请你花 15 分钟聊聊："
    "最近一次在家练习/康复时，具体是怎么做的、当时最没底或最麻烦的是什么。"
    "纯访谈交流，不推销；"
    f"{BETA_INCENTIVE_PHRASE}。"
)

SEGMENT_INTERVIEW_ANGLES: dict[str, str] = {
    "运动损伤": "居家康复动作对错判断、二次受伤顾虑、替代办法",
    "初老群体": "跟练质量困扰、因无人纠正而停练/改方式",
    "产后康复": "碎片时间/隐私、腹直肌盆底恢复、难坚持原因",
    "中考体育家长": "孩子在家练体能的安排监督、指导困难、枯燥感",
}

OUTREACH_SYSTEM_PROMPT = f"""写一条 B 站等平台的访谈邀请私信（只输出正文）。
背景：{INTERVIEW_PURPOSE}
利他：必须包含「{BETA_INCENTIVE_PHRASE}」；禁止空洞「对我们很有价值」；禁止未承诺的资料包/避坑清单。
Mom Test：聊过去真实经历；禁止问功能好不好/会否付费；禁止推销链接与疗效承诺。
只用评论明确内容；勿贴标签；80–220 中文字；语气真诚具体。"""


def _segment_hints(matches: list[str]) -> str:
    if not matches:
        return ""
    parts = [SEGMENT_INTERVIEW_ANGLES[m] for m in matches if m in SEGMENT_INTERVIEW_ANGLES]
    if not parts and matches:
        parts = [f"了解「{matches[0]}」在家练习真实困扰"]
    return "；".join(parts)


def build_outreach_user_message(candidate: CandidateRecord, base_template: str) -> str:
    matches = candidate.research_target_matches or []
    quotes = (candidate.representative_quotes or [])[:2]
    problems = (candidate.specific_problems or [])[:2]
    payload = {
        "user": candidate.username or "用户",
        "quotes": quotes,
        "problems": problems,
        "segment": matches[:2],
        "angle": _segment_hints(matches),
        "template_hint": (base_template or "")[:120],
    }
    return "生成访谈邀请：\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
