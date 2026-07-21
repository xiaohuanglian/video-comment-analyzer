# -*- coding: utf-8 -*-
"""Collect, cluster, and stats open themes from new_signals."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from .llm_analyzer import build_openai_client, estimate_cost, parse_usage
from .pricing import resolve_pricing
from .schemas import RunConfig
from .statistics import user_key
from .storage import load_config, load_results, save_themes
from .theme_prompts import ROUND1_SYSTEM, ROUND2_SYSTEM, build_round1_user_message, build_round2_user_message
from .theme_schemas import (
    PROMPT_VERSION,
    CandidateThemeLLM,
    RawSignalItem,
    Round1ResponseLLM,
    Round2ResponseLLM,
    ThemeRecord,
    ThemeStats,
    ThemesDocument,
)

BATCH_SIZE = 40
MAX_SAMPLE_QUOTES = 2


def _normalize_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    return cleaned.lower()


def collect_raw_signals(results: List[Dict[str, Any]]) -> List[RawSignalItem]:
    """Extract and dedupe new_signals from analysis results."""
    return _aggregate_frequencies(results)


def _aggregate_frequencies(results: List[Dict[str, Any]]) -> List[RawSignalItem]:
    """Merge duplicate expressions and attach frequency + sample quotes."""
    freq: Dict[str, int] = defaultdict(int)
    quotes: Dict[str, List[str]] = defaultdict(list)
    meta: Dict[str, dict] = {}
    for row in results:
        record_id = str(row.get("record_id") or row.get("analysis", {}).get("record_id") or "")
        source = row.get("source") or {}
        analysis = row.get("analysis") or {}
        for signal in analysis.get("new_signals") or []:
            if not isinstance(signal, dict):
                continue
            text = str(signal.get("text") or "").strip()
            quote = str(signal.get("evidence_quote") or "").strip()
            if not text and not quote:
                continue
            signal_type = str(signal.get("type") or "other")
            norm_key = f"{signal_type}|{_normalize_text(text or quote)}"
            freq[norm_key] += 1
            q = quote or text[:80]
            if q and len(quotes[norm_key]) < MAX_SAMPLE_QUOTES and q not in quotes[norm_key]:
                quotes[norm_key].append(q)
            if norm_key not in meta:
                meta[norm_key] = {
                    "record_id": record_id,
                    "signal_type": signal_type,
                    "text": text or quote[:40],
                    "evidence_quote": quote or text[:80],
                    "username": str(source.get("username") or source.get("user_id") or ""),
                    "user_key": user_key(source),
                    "platform": str(source.get("platform") or ""),
                    "creator_type": str(source.get("creator_type") or ""),
                    "creator_name": str(source.get("creator_name") or ""),
                    "video_title": str(source.get("video_title") or ""),
                    "source_file": str(source.get("source_file") or ""),
                }

    aggregated: List[RawSignalItem] = []
    index = 0
    for norm_key in sorted(freq.keys(), key=lambda k: (-freq[k], k)):
        info = meta[norm_key]
        index += 1
        aggregated.append(
            RawSignalItem(
                signal_id=f"s{index:04d}",
                record_id=info["record_id"],
                signal_type=info["signal_type"],
                text=info["text"],
                evidence_quote=info["evidence_quote"],
                username=info["username"],
                user_key=info["user_key"],
                platform=info["platform"],
                creator_type=info["creator_type"],
                creator_name=info["creator_name"],
                video_title=info["video_title"],
                source_file=info["source_file"],
                frequency=freq[norm_key],
                sample_quotes=quotes[norm_key][:MAX_SAMPLE_QUOTES],
            )
        )
    return aggregated


def _signal_index(signals: List[RawSignalItem]) -> Dict[str, RawSignalItem]:
    return {item.signal_id: item for item in signals}


def compute_theme_stats(theme: ThemeRecord, signals: List[RawSignalItem]) -> ThemeStats:
    index = _signal_index(signals)
    record_ids: Set[str] = set()
    users: Set[str] = set()
    source_files: Set[str] = set()
    videos: Set[str] = set()
    creators: Set[str] = set()
    platform_counts: Dict[str, int] = defaultdict(int)
    creator_type_counts: Dict[str, int] = defaultdict(int)
    quotes: List[str] = []

    for sid in theme.included_signal_ids:
        item = index.get(sid)
        if item is None:
            continue
        if item.record_id:
            record_ids.add(item.record_id)
        if item.user_key:
            users.add(item.user_key)
        if item.source_file:
            source_files.add(item.source_file)
        video_key = item.video_title or item.source_file
        if video_key:
            videos.add(video_key)
        if item.creator_name:
            creators.add(item.creator_name)
        platform_counts[item.platform or "unknown"] += 1
        creator_type_counts[item.creator_type or "未知"] += 1
        for quote in item.sample_quotes:
            if quote and quote not in quotes and len(quotes) < MAX_SAMPLE_QUOTES:
                quotes.append(quote)

    theme.record_ids = sorted(record_ids)
    theme.representative_quotes = quotes
    return ThemeStats(
        comment_count=len(record_ids),
        unique_user_count=len(users),
        source_file_count=len(source_files),
        video_count=len(videos),
        creator_count=len(creators),
        platform_counts=dict(platform_counts),
        creator_type_counts=dict(creator_type_counts),
    )


def _mock_cluster_round1(signals: List[RawSignalItem]) -> List[CandidateThemeLLM]:
    groups: Dict[str, List[str]] = defaultdict(list)
    names: Dict[str, str] = {}
    types: Dict[str, str] = {}
    for item in signals:
        key = _normalize_text(item.text)[:24] or item.signal_id
        groups[key].append(item.signal_id)
        names[key] = item.text[:20] or "开放主题"
        types[key] = item.signal_type
    candidates: List[CandidateThemeLLM] = []
    for key, sids in groups.items():
        relation = "weakens_existing" if any(k in names[key] for k in ("镜像", "左右", "反侧", "同侧")) else "extends_existing"
        candidates.append(
            CandidateThemeLLM(
                theme_name=names[key],
                theme_type=types[key],
                definition=names[key],
                included_signal_ids=sids,
                relation_to_existing_hypotheses=relation,
                implication="需进一步人工确认产品含义",
                confidence=0.75,
            )
        )
    return candidates


def _mock_cluster_round2(candidates: List[CandidateThemeLLM]) -> List[ThemeRecord]:
    merged: Dict[str, ThemeRecord] = {}
    for cand in candidates:
        key = _normalize_text(cand.theme_name)[:16]
        if key not in merged:
            theme_id = f"t_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:8]}"
            merged[key] = ThemeRecord(
                theme_id=theme_id,
                theme_name=cand.theme_name,
                theme_type=cand.theme_type,
                definition=cand.definition,
                included_signal_ids=list(cand.included_signal_ids),
                relation_to_existing_hypotheses=cand.relation_to_existing_hypotheses,
                implication=cand.implication,
                confidence=cand.confidence,
            )
        else:
            existing = merged[key]
            for sid in cand.included_signal_ids:
                if sid not in existing.included_signal_ids:
                    existing.included_signal_ids.append(sid)
            existing.confidence = max(existing.confidence, cand.confidence)
    return list(merged.values())


def _llm_json_call(
    client,
    *,
    model: str,
    system: str,
    user: str,
    schema_model,
):
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    usage = parse_usage(getattr(completion, "usage", None))
    raw = completion.choices[0].message.content or "{}"
    payload = json.loads(raw)
    parsed = schema_model.model_validate(payload)
    return parsed, usage


def _cluster_round1_llm(
    client,
    config: RunConfig,
    signals: List[RawSignalItem],
) -> tuple[List[CandidateThemeLLM], int, int, int]:
    all_candidates: List[CandidateThemeLLM] = []
    prompt_tokens = 0
    completion_tokens = 0
    cache_hits = 0
    valid_ids = {s.signal_id for s in signals}
    for start in range(0, len(signals), BATCH_SIZE):
        batch = signals[start : start + BATCH_SIZE]
        parsed, usage = _llm_json_call(
            client,
            model=config.model_name,
            system=ROUND1_SYSTEM,
            user=build_round1_user_message(batch),
            schema_model=Round1ResponseLLM,
        )
        prompt_tokens += usage.prompt_tokens
        completion_tokens += usage.completion_tokens
        cache_hits += usage.prompt_cache_hit_tokens
        for cand in parsed.candidate_themes:
            cand.included_signal_ids = [sid for sid in cand.included_signal_ids if sid in valid_ids]
            if cand.included_signal_ids:
                all_candidates.append(cand)
    return all_candidates, prompt_tokens, completion_tokens, cache_hits


def _cluster_round2_llm(
    client,
    config: RunConfig,
    candidates: List[CandidateThemeLLM],
) -> tuple[List[ThemeRecord], int, int, int]:
    if not candidates:
        return [], 0, 0, 0
    payload = [c.model_dump() for c in candidates]
    parsed, usage = _llm_json_call(
        client,
        model=config.model_name,
        system=ROUND2_SYSTEM,
        user=build_round2_user_message(payload),
        schema_model=Round2ResponseLLM,
    )
    themes: List[ThemeRecord] = []
    for index, item in enumerate(parsed.themes, start=1):
        theme_id = f"t_{index:03d}_{uuid.uuid4().hex[:6]}"
        themes.append(
            ThemeRecord(
                theme_id=theme_id,
                theme_name=item.theme_name,
                theme_type=item.theme_type,
                definition=item.definition,
                included_signal_ids=item.included_signal_ids,
                relation_to_existing_hypotheses=item.relation_to_existing_hypotheses,
                implication=item.implication,
                confidence=item.confidence,
            )
        )
    return themes, usage.prompt_tokens, usage.completion_tokens, usage.prompt_cache_hit_tokens


def run_theme_clustering(
    run_id: str,
    *,
    api_key: Optional[str] = None,
    use_mock: bool = False,
) -> ThemesDocument:
    config = load_config(run_id)
    results = load_results(run_id)
    if not results:
        raise ValueError("尚无分析结果，无法生成开放主题")

    signals = collect_raw_signals(results)
    if not signals:
        doc = ThemesDocument(
            model_name=config.model_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            raw_signal_count=0,
            currency=config.currency,
        )
        save_themes(run_id, doc)
        return doc

    prompt_tokens = 0
    completion_tokens = 0
    cache_hits = 0

    if use_mock:
        candidates = _mock_cluster_round1(signals)
        themes = _mock_cluster_round2(candidates)
    else:
        if not (api_key or "").strip():
            raise ValueError("主题归并需要 API Key")
        client = build_openai_client(config.base_url, api_key or "")
        candidates, p1, c1, h1 = _cluster_round1_llm(client, config, signals)
        themes, p2, c2, h2 = _cluster_round2_llm(client, config, candidates)
        prompt_tokens = p1 + p2
        completion_tokens = c1 + c2
        cache_hits = h1 + h2

    for theme in themes:
        theme.stats = compute_theme_stats(theme, signals)

    pricing = resolve_pricing(config.base_url, config.model_name)
    cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
        prompt_cache_hit_tokens=cache_hits,
        input_price_cache_hit=float(pricing["input_price_cache_hit"]),
    )

    doc = ThemesDocument(
        prompt_version=PROMPT_VERSION,
        model_name=config.model_name,
        created_at=datetime.now(timezone.utc).isoformat(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_cache_hit_tokens=cache_hits,
        cost=cost,
        currency=config.currency,
        raw_signal_count=len(signals),
        themes=sorted(themes, key=lambda t: (-t.stats.comment_count, t.theme_name)),
    )
    save_themes(run_id, doc)
    return doc
