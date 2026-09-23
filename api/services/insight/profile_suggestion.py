# -*- coding: utf-8 -*-
"""Let the model propose a project profile from real comments.

This removes the need to hand-edit code to fit a new business: the user runs
this once, reviews the generated profile in the JSON editor, and saves it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .llm_analyzer import build_openai_client
from .project_profiles import ProjectProfile, builtin_profiles

SUGGEST_SYSTEM = (
    "你是评论洞察系统的配置助手。根据用户提供的真实评论文本，推断这个产品/内容所面向的业务场景，"
    "并输出一份项目档案 JSON。只输出 JSON，不要解释。字段：\n"
    "name, domain, research_goal, target_audience, forbidden_claims,\n"
    "context_compact, context_full,\n"
    "hypotheses(H1-H3 完整描述), hypothesis_short(H1-H3 短语),\n"
    "hypothesis_rules, decision_keywords(数组), noise_markers(数组),\n"
    "theme_risk_tokens(数组), theme_difficulty_tokens(数组), theme_question_tokens(数组),\n"
    "content_persona, content_platforms(数组)。\n"
    "要求：全部使用简体中文；只依据评论内容推断，不要编造市场规模/付费意愿；"
    "hypotheses 要针对该场景的具体需求与卡点；词汇要具体，避免空话。"
)

_LIST_FIELDS = (
    "decision_keywords",
    "noise_markers",
    "theme_risk_tokens",
    "theme_difficulty_tokens",
    "theme_question_tokens",
    "content_platforms",
)
_STR_FIELDS = (
    "name",
    "domain",
    "research_goal",
    "target_audience",
    "forbidden_claims",
    "context_compact",
    "context_full",
    "hypothesis_rules",
    "content_persona",
)


def _as_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
    return []


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    base = builtin_profiles()["default"]
    out: Dict[str, Any] = {}
    for field in _STR_FIELDS:
        value = raw.get(field)
        out[field] = str(value).strip() if value not in (None, "") else getattr(base, field)
    for field in _LIST_FIELDS:
        items = _as_str_list(raw.get(field))
        out[field] = items or list(getattr(base, field))

    hypotheses = raw.get("hypotheses") if isinstance(raw.get("hypotheses"), dict) else {}
    short = raw.get("hypothesis_short") if isinstance(raw.get("hypothesis_short"), dict) else {}
    out["hypotheses"] = {
        f"H{i}": str(hypotheses.get(f"H{i}") or base.hypotheses.get(f"H{i}") or "")
        for i in (1, 2, 3)
    }
    out["hypothesis_short"] = {
        f"H{i}": str(short.get(f"H{i}") or base.hypothesis_short.get(f"H{i}") or "")
        for i in (1, 2, 3)
    }
    out["profile_id"] = ""
    out["is_builtin"] = False
    out["opportunity_templates"] = []
    return out


def _template(comments: List[str]) -> Dict[str, Any]:
    base = builtin_profiles()["default"]
    return _normalize(
        {
            "name": f"{base.name}（自动生成·模板）",
            "domain": base.domain,
            "research_goal": base.research_goal,
            "target_audience": base.target_audience,
            "content_persona": base.content_persona,
            "content_platforms": base.content_platforms,
        }
    )


def suggest_profile(
    comments: List[str],
    *,
    model_name: str,
    base_url: str,
    api_key: str = "",
    use_mock: bool = False,
) -> Dict[str, Any]:
    sample = [c.strip() for c in comments if c and c.strip()][:200]
    if use_mock or not (api_key or "").strip():
        return _template(sample)

    client = build_openai_client(base_url, api_key)
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SUGGEST_SYSTEM},
            {
                "role": "user",
                "content": "以下是评论样本：\n" + "\n".join(f"- {c}" for c in sample),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=2000,
    )
    raw_text = completion.choices[0].message.content or "{}"
    try:
        raw = json.loads(raw_text)
    except ValueError:
        raw = {}
    return _normalize(raw if isinstance(raw, dict) else {})


def validate_suggested_profile(payload: Dict[str, Any]) -> ProjectProfile:
    """Coerce a suggested payload into a valid (unsaved) ProjectProfile."""
    return ProjectProfile.model_validate(payload)