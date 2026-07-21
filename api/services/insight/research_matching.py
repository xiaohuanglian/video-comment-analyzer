# -*- coding: utf-8 -*-
"""Match analyzed comments to user-defined research target segments."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

# Built-in keyword hints for common segments (user can add custom targets freely).
SEGMENT_HINTS: Dict[str, List[str]] = {
    "运动损伤": ["损伤", "受伤", "术后", "康复", "半月板", "韧带", "撕裂", "骨折", "旧伤", "疼痛", "理疗"],
    "初老群体": ["初老", "中年", "40岁", "50岁", "代谢", "年纪", "年龄大", "关节退化"],
    "产后康复": ["产后", "腹直肌", "盆底", "漏尿", "哺乳", "月子", "剖腹产", "顺产", "骨盆"],
    "中考体育家长": ["中考", "体育中考", "孩子练", "儿子", "女儿", "家长", "升学", "考试"],
}


def parse_research_targets(raw: str | Sequence[str] | None) -> List[str]:
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return items
    text = str(raw).replace("，", ",").replace("、", ",")
    return [part.strip() for part in re.split(r"[,;\n]+", text) if part.strip()]


def _analysis_text_pool(source: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    # Prefer verbatim comment text; analysis fields are secondary (may be paraphrased).
    gap_texts = []
    for g in analysis.get("action_gap") or []:
        if isinstance(g, dict):
            gap_texts.append(str(g.get("text") or ""))
        else:
            gap_texts.append(str(g))
    parts = [
        str(source.get("comment_text") or ""),
        str(source.get("video_title") or ""),
        " ".join(str(p) for p in (analysis.get("specific_problems") or [])),
        " ".join(str(s) for s in (analysis.get("signals") or [])),
        " ".join(str(c) for c in (analysis.get("explicit_user_context") or [])),
        " ".join(gap_texts),
    ]
    return "\n".join(parts).lower()


def match_research_targets(
    source: Dict[str, Any],
    analysis: Dict[str, Any],
    targets: Sequence[str],
) -> List[str]:
    if not targets:
        return []
    comment = str(source.get("comment_text") or "").lower()
    pool = _analysis_text_pool(source, analysis)
    matched: List[str] = []
    for target in targets:
        keywords = SEGMENT_HINTS.get(target, []) + [target]
        # Prefer hit in raw comment; fall back to analysis pool for custom targets.
        hit_comment = any(kw.lower() in comment for kw in keywords if kw and len(kw) >= 2)
        hit_pool = any(kw.lower() in pool for kw in keywords if kw and len(kw) >= 2)
        if hit_comment or hit_pool:
            matched.append(target)
    return matched


def research_relevance_score(matches: List[str], analysis: Dict[str, Any]) -> int:
    score = len(matches) * 3
    if analysis.get("help_seeking"):
        score += 2
    if analysis.get("specific_problems"):
        score += 1
    evidence = analysis.get("actual_training_evidence") or "none"
    if evidence in {"tried", "continued"}:
        score += 1
    return score
