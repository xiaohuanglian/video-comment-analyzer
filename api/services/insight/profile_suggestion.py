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
    "realtime_tokens(数组，表示需要实时观察/示范的词), personalized_tokens(数组，表示需结合个人情况判断的词),\n"
    "positive_result_tokens(数组，表示取得正向结果的词),\n"
    "intents(数组，每项 {key,label,description})，signals(数组，每项 {key,label,description})，\n"
    "theme_risk_tokens(数组), theme_difficulty_tokens(数组), theme_question_tokens(数组),\n"
    "content_persona, content_platforms(数组)。\n"
    "要求：全部使用简体中文；只依据评论内容推断，不要编造市场规模/付费意愿；"
    "hypotheses 要针对该场景的具体需求与卡点；词汇要具体，避免空话。\n"
    "intents/signals：先看用户给出的默认清单，能用的沿用 key、只把 label 改得贴合业务；"
    "不适用就删掉，再按本业务补充 0-3 个新维度（key 用简短英文小写下划线，label 用中文）。"
    "intents 表示评论的主要沟通目的（3-8 项），signals 表示值得关注的用户表达信号（8-20 项）。"
)

_LIST_FIELDS = (
    "decision_keywords",
    "noise_markers",
    "realtime_tokens",
    "personalized_tokens",
    "positive_result_tokens",
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


def _taxonomy_items(raw: Any, default_items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "").strip()
            if not key:
                continue
            items.append(
                {
                    "key": key,
                    "label": str(entry.get("label") or key).strip(),
                    "description": str(entry.get("description") or "").strip(),
                }
            )
    return items or default_items


def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
    from .project_profiles import default_intents, default_signals

    base = builtin_profiles()["default"]
    out: Dict[str, Any] = {}
    for field in _STR_FIELDS:
        value = raw.get(field)
        out[field] = str(value).strip() if value not in (None, "") else getattr(base, field)
    for field in _LIST_FIELDS:
        items = _as_str_list(raw.get(field))
        out[field] = items or list(getattr(base, field))

    out["intents"] = _taxonomy_items(
        raw.get("intents"), [i.model_dump() for i in default_intents()]
    )
    out["signals"] = _taxonomy_items(
        raw.get("signals"), [i.model_dump() for i in default_signals()]
    )

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
    from .project_profiles import default_intents, default_signals

    defaults = {
        "intents": [i.model_dump() for i in default_intents()],
        "signals": [i.model_dump() for i in default_signals()],
    }
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SUGGEST_SYSTEM},
            {
                "role": "user",
                "content": (
                    "当前系统默认的 intents/signals 清单（供沿用或裁剪）：\n"
                    + json.dumps(defaults, ensure_ascii=False)
                    + "\n\n以下是评论样本：\n"
                    + "\n".join(f"- {c}" for c in sample)
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
        max_tokens=2500,
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