# -*- coding: utf-8 -*-
"""Prompts for personalized public comment-reply drafts (token-lean).

The tool only ever produces *drafts* for a human to review and post manually.
It never auto-posts and never messages anyone on the user's behalf.
"""

from __future__ import annotations

import json

from ..insight.candidate_schemas import CandidateRecord

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

写法（活人感短回复）：
- 材料先行：只用对方评论里明确说过的内容。他没有说过的经历、场景、情绪，一个字都不能替他编。
- 开头尽快碰到他问的事。不要“你好呀”加客套开场白堆砌，称呼可以有一个，随后直接进正题。
- 判断正面下：直接说你的看法和做法，给依据。你的经验里哪个瞬间、哪个数字、哪次失败最相关，就写哪个。
- 白话打底。用一个真实的人打字回复的口气，可以有正常的补充、自我修正，但每一处都来自眼前内容。
- 写完事情就停。不追加强问句以外的“希望对你有帮助”之类尾巴，不升华。

硬禁令（命中即废稿重写）：
- 禁「不是……而是……」及一切翻案句式（并非/不在于/与其说/表面实际/你以为其实/说到底）。
- 不用破折号（— —— –）。
- 冒号只能用来引直接原话，不做“核心是：”这类提示。
- 禁三项以上同构排比，两项为限。
- 禁黑话和模型腔（赋能/抓手/闭环/底层逻辑/码住/建议收藏/值得关注/说白了/先说结论等）。
- 禁动词名词化（“完成了对X的优化”改成把话说直）。

其他：
- {REPLY_GUARDRAILS}
- 真诚、具体，40–160 中文字。
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