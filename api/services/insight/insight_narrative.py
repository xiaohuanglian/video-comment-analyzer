# -*- coding: utf-8 -*-
"""On-demand plain-language readout of an insight run.

Turns the mechanical statistics (intent counts, signal coverage, top themes)
into a short, natural paragraph a product/content team can read at a glance.
Uses the configured model; falls back to a deterministic template when no API
key is available (or a mock run is requested).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .analyzer import build_summary
from .llm_analyzer import build_openai_client, estimate_cost, parse_usage
from .pricing import resolve_pricing
from .storage import load_config, load_themes

NARRATIVE_SYSTEM = (
    "你是评论数据分析师，负责把统计结果写成给产品/内容团队看的中文解读。"
    "要求：3-6 句，口语自然、结论先行；只依据给定数据，不虚构数字；"
    "不要使用「信息信号覆盖率」「一次回复能否解决」这类术语；"
    "不要做疗效、收益或付费意愿的承诺。直接输出正文，不要标题、不要列表、不要 Markdown。"
)


def _int(label: str, value: Any) -> str:
    return f"{label} {value}"


def _top_signal(summary: Dict[str, Any]) -> Optional[str]:
    coverage = summary.get("signal_coverage") or {}
    if not coverage:
        return None
    key, info = max(coverage.items(), key=lambda kv: (kv[1] or {}).get("count", 0))
    from .labels import label_signal

    return f"{label_signal(key, summary.get('signal_labels') or None)}（{ (info or {}).get('count', 0) } 条）"


def _top_intent(summary: Dict[str, Any]) -> Optional[str]:
    counts = summary.get("primary_intent_counts") or {}
    if not counts:
        return None
    key, count = max(counts.items(), key=lambda kv: kv[1])
    from .labels import label_intent

    return f"{label_intent(key, summary.get('intent_labels') or None)}（{count} 条）"


def _theme_names(run_id: str, limit: int = 5) -> List[str]:
    try:
        doc = load_themes(run_id)
    except Exception:
        return []
    themes = getattr(doc, "themes", None) or []
    names: List[str] = []
    for theme in themes[:limit]:
        name = getattr(theme, "theme_name", "") or ""
        if name:
            names.append(name)
    return names


def _template_text(summary: Dict[str, Any], themes: List[str]) -> str:
    total = summary.get("total_analyzed") or 0
    if not total:
        return "这批评论还没有可用的分析结果，先完成评论分析再来看解读。"
    parts: List[str] = [f"共分析了 {total} 条评论，其中有效评论 {summary.get('valid_comments', 0)} 条。"]

    problem = summary.get("difficulty_count") or 0
    question = summary.get("question_count") or 0
    if problem or question:
        parts.append(f"大家在评论区里最常做的是提问和求助（提问 {question} 条、具体困难 {problem} 条）。")

    top_signal = _top_signal(summary)
    if top_signal:
        parts.append(f"出现最多的信号是「{top_signal}」。")

    trained = summary.get("trained_users") or 0
    if trained:
        parts.append(f"有 {trained} 位用户留下了实际使用/行动过的痕迹，值得优先回访。")

    matched = summary.get("research_matched_user_count") or summary.get("high_priority_user_count") or 0
    if matched:
        parts.append(f"其中 {matched} 位符合你设定的目标人群。")

    if themes:
        parts.append("目前最集中的话题有：" + "、".join(themes) + "。")

    parts.append("整体看起来，评论里的核心诉求集中在少数几个反复出现的问题上，适合先针对它们产出内容或回复。")
    return "".join(parts)


def _build_payload(run_id: str) -> Dict[str, Any]:
    summary = build_summary(run_id) or {}
    return {
        "total_analyzed": summary.get("total_analyzed", 0),
        "valid_comments": summary.get("valid_comments", 0),
        "unique_users": summary.get("unique_users", 0),
        "trained_users": summary.get("trained_users", 0),
        "top_intent": _top_intent(summary),
        "question_count": summary.get("question_count", 0),
        "difficulty_count": summary.get("difficulty_count", 0),
        "result_feedback_count": summary.get("result_feedback_count", 0),
        "top_signal": _top_signal(summary),
        "product_fit_high_count": summary.get("product_fit_high_count", 0),
        "research_matched_user_count": summary.get("research_matched_user_count", 0),
        "themes": _theme_names(run_id),
        "_summary": summary,
    }


def build_insight_narrative(
    run_id: str,
    *,
    api_key: str = "",
    use_mock: bool = False,
) -> Dict[str, Any]:
    payload = _build_payload(run_id)
    summary = payload.pop("_summary")
    config = load_config(run_id)

    if use_mock or not (api_key or "").strip():
        return {
            "text": _template_text(summary, payload.get("themes") or []),
            "model_name": "template",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cost": 0.0,
            "currency": config.currency,
        }

    import json

    pricing = resolve_pricing(config.base_url, config.model_name)
    client = build_openai_client(config.base_url, api_key)
    completion = client.chat.completions.create(
        model=config.model_name,
        messages=[
            {"role": "system", "content": NARRATIVE_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.4,
    )
    usage = parse_usage(getattr(completion, "usage", None))
    text = (completion.choices[0].message.content or "").strip()
    cost = estimate_cost(
        usage.prompt_tokens,
        usage.completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
        prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
        input_price_cache_hit=float(pricing["input_price_cache_hit"]),
    )
    return {
        "text": text or _template_text(summary, payload.get("themes") or []),
        "model_name": config.model_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cost": cost,
        "currency": config.currency,
    }