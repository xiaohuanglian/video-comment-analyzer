# -*- coding: utf-8 -*-
"""Prompts for personalized public comment-reply drafts (token-lean).

The tool only ever produces *drafts* for a human to review and post manually.
It never auto-posts and never messages anyone on the user's behalf.
"""

from __future__ import annotations

import json

from .candidate_schemas import CandidateRecord

# Domain-neutral purpose: write a genuinely helpful public reply under someone
# else's content, aimed at one specific commenter.
REPLY_PURPOSE = (
    "在他人内容的评论区，针对一位具体用户写一条公开回复。"
    "目标是真正帮到对方、建立信任，而不是推销或导流。"
    "只谈他评论里明确说到的内容。"
)

# Hard guardrails for public replies (also applied by the reviewer).
REPLY_GUARDRAILS = (
    "禁止推销、导流、留联系方式或做疗效/收益承诺；"
    "禁止编造对方经历；信息不足时可以先提一个澄清问题。"
)

DEFAULT_BASE_TEMPLATE = (
    "你好，看到你提到的情况，说说我的经验/做法：……"
    "如果方便，可以再补充一下你的具体场景，我看看还能怎么帮到你。"
)

# Optional per-segment reply angles; projects can extend this map.
SEGMENT_REPLY_ANGLES: dict[str, str] = {}

OUTREACH_SYSTEM_PROMPT = f"""为一位具体用户写一条公开的评论区回复（只输出正文）。
背景：{REPLY_PURPOSE}
要求：
- 针对该用户评论里明确的问题/需求给出具体、可执行的信息，不要泛泛而谈、不要复制模板。
- {REPLY_GUARDRAILS}
- 像一个真实的人：真诚、具体，40–160 中文字。
- 只用评论里已有的信息；不要贴标签、不要下诊断。"""


def _segment_hints(matches: list[str]) -> str:
    if not matches:
        return ""
    parts = [SEGMENT_REPLY_ANGLES[m] for m in matches if m in SEGMENT_REPLY_ANGLES]
    if not parts:
        parts = [f"围绕「{matches[0]}」给出具体帮助"]
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
    return "生成评论区回复：\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))