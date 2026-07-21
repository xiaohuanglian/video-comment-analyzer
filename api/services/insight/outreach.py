# -*- coding: utf-8 -*-
"""Generate and persist outreach message drafts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from .candidate_schemas import CandidateRecord, OutreachDocument, OutreachEntry
from .llm_analyzer import build_openai_client, estimate_cost, parse_usage
from .outreach_prompts import DEFAULT_BASE_TEMPLATE, OUTREACH_SYSTEM_PROMPT, build_outreach_user_message
from .pricing import resolve_pricing
from .schemas import RunConfig


def _mock_draft(candidate: CandidateRecord, base_template: str) -> str:
    name = candidate.username or "你好"
    quote = candidate.representative_quotes[0] if candidate.representative_quotes else ""
    if quote:
        body = (
            f"{name}，你好！我们在做居家训练动作反馈的用户研究。"
            f"看到你在评论里提到「{quote[:36]}」，"
            f"想邀请你花 15 分钟聊聊：最近一次在家练习时具体怎么做的、"
            f"当时最没底或最麻烦的是什么。"
            f"纯访谈不推销；参与交流会优先获得内测体验资格（形式待定）。方便的话欢迎回复～"
        )
    else:
        body = base_template.replace("你好", f"{name}，你好", 1)
    return body[:220]


def _generate_one(
    candidate: CandidateRecord,
    config: RunConfig,
    base_template: str,
    *,
    api_key: str = "",
    use_mock: bool = False,
    client=None,
) -> OutreachEntry:
    if use_mock:
        draft = _mock_draft(candidate, base_template)
        return OutreachEntry(
            user_key=candidate.user_key,
            username=candidate.username,
            base_template=base_template,
            generated_draft=draft,
            edited_content=draft,
            model_name="mock",
            generated_at=datetime.now(timezone.utc).isoformat(),
            contact_status="preparing",
        )

    llm_client = client or build_openai_client(config.base_url, api_key)
    completion = llm_client.chat.completions.create(
        model=config.model_name,
        messages=[
            {"role": "system", "content": OUTREACH_SYSTEM_PROMPT},
            {"role": "user", "content": build_outreach_user_message(candidate, base_template)},
        ],
        temperature=0.7,
    )
    usage = parse_usage(getattr(completion, "usage", None))
    draft = (completion.choices[0].message.content or "").strip()
    pricing = resolve_pricing(config.base_url, config.model_name)
    cost = estimate_cost(
        usage.prompt_tokens,
        usage.completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
        prompt_cache_hit_tokens=usage.prompt_cache_hit_tokens,
        input_price_cache_hit=float(pricing["input_price_cache_hit"]),
    )
    return OutreachEntry(
        user_key=candidate.user_key,
        username=candidate.username,
        base_template=base_template,
        generated_draft=draft,
        edited_content=draft,
        model_name=config.model_name,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cost=cost,
        currency=config.currency,
        generated_at=datetime.now(timezone.utc).isoformat(),
        contact_status="preparing",
    )


def generate_outreach_drafts(
    candidates: List[CandidateRecord],
    config: RunConfig,
    *,
    user_keys: List[str],
    base_template: str = "",
    api_key: Optional[str] = None,
    use_mock: bool = False,
    existing: Optional[OutreachDocument] = None,
    force: bool = False,
) -> OutreachDocument:
    template = (base_template or DEFAULT_BASE_TEMPLATE).strip()
    if not use_mock and not (api_key or "").strip():
        raise ValueError("生成私信草稿需要 API Key")

    selected = {c.user_key: c for c in candidates if c.user_key in set(user_keys)}
    missing = [key for key in user_keys if key not in selected]
    if missing:
        raise ValueError(f"未找到候选用户：{', '.join(missing[:3])}")

    client = None if use_mock else build_openai_client(config.base_url, api_key or "")
    entries_map: Dict[str, OutreachEntry] = {}
    if existing:
        for entry in existing.entries:
            entries_map[entry.user_key] = entry

    for key in user_keys:
        prior = entries_map.get(key)
        # Default: skip users who already have a draft (save tokens)
        if not force and prior and (prior.generated_draft or prior.edited_content):
            continue
        entry = _generate_one(selected[key], config, template, api_key=api_key or "", use_mock=use_mock, client=client)
        if prior and prior.product_manager_note:
            entry.product_manager_note = prior.product_manager_note
        entries_map[key] = entry

    doc = OutreachDocument(
        updated_at=datetime.now(timezone.utc).isoformat(),
        entries=sorted(entries_map.values(), key=lambda e: e.user_key),
    )
    return doc


def merge_outreach_update(
    doc: OutreachDocument,
    user_key: str,
    *,
    edited_content: Optional[str] = None,
    contact_status: Optional[str] = None,
    product_manager_note: Optional[str] = None,
) -> Optional[OutreachEntry]:
    for entry in doc.entries:
        if entry.user_key != user_key:
            continue
        if edited_content is not None:
            entry.edited_content = edited_content
        if contact_status is not None:
            entry.contact_status = contact_status  # type: ignore[assignment]
        if product_manager_note is not None:
            entry.product_manager_note = product_manager_note
        doc.updated_at = datetime.now(timezone.utc).isoformat()
        return entry
    return None
