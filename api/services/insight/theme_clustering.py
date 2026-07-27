# -*- coding: utf-8 -*-
"""Collect, cluster, and stats open themes from new_signals."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

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
LLM_RETRY_ATTEMPTS = 3
# Round1 historically emits ~2.5k–4k completion tokens per 40-signal batch when
# many included_signal_ids are returned. A tight cap truncates JSON mid-string.
ROUND1_MAX_TOKENS = 6000
ROUND2_MAX_TOKENS = 4000
ROUND1_MAX_WORKERS = 2


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


def resolve_signal_id(raw: str, valid_ids: Set[str]) -> Optional[str]:
    """Map LLM variants (3401, '3401', 's3401') onto canonical ids like 's3401'."""
    sid = str(raw or "").strip()
    if not sid:
        return None
    if sid in valid_ids:
        return sid
    digits = sid[1:] if sid[:1].lower() == "s" and sid[1:].isdigit() else sid
    if digits.isdigit():
        padded = f"s{int(digits):04d}"
        if padded in valid_ids:
            return padded
        bare = f"s{digits}"
        if bare in valid_ids:
            return bare
    return None


def resolve_signal_ids(raw_ids: List[str], valid_ids: Set[str]) -> List[str]:
    resolved: List[str] = []
    seen: Set[str] = set()
    for raw in raw_ids:
        sid = resolve_signal_id(raw, valid_ids)
        if sid and sid not in seen:
            seen.add(sid)
            resolved.append(sid)
    return resolved


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


def _is_truncated_json_error(exc: Exception, raw: str = "", finish_reason: str = "") -> bool:
    text = f"{exc} {raw} {finish_reason}".lower()
    return (
        finish_reason == "length"
        or "output truncated" in text
        or "unterminated string" in text
        or "expecting" in text
        or "extra data" in text
        or "jsondecodeerror" in text
        or "eof while parsing" in text
    )


def _llm_json_call(
    client,
    *,
    model: str,
    system: str,
    user: str,
    schema_model,
    max_tokens: int,
):
    last_error: Optional[Exception] = None
    token_budget = max_tokens
    for attempt in range(LLM_RETRY_ATTEMPTS):
        raw = ""
        finish_reason = ""
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=token_budget,
            )
            usage = parse_usage(getattr(completion, "usage", None))
            choice = completion.choices[0]
            finish_reason = str(getattr(choice, "finish_reason", "") or "")
            raw = choice.message.content or "{}"
            if finish_reason == "length":
                raise json.JSONDecodeError("output truncated by max_tokens", raw, 0)
            return schema_model.model_validate(json.loads(raw)), usage
        except Exception as exc:  # API, JSON and schema failures are all retryable once.
            last_error = exc
            if attempt + 1 < LLM_RETRY_ATTEMPTS:
                if _is_truncated_json_error(exc, raw, finish_reason):
                    token_budget = min(token_budget * 2, 12000)
                time.sleep(0.6 * (2**attempt))
    raise RuntimeError(f"主题模型调用失败，已重试 {LLM_RETRY_ATTEMPTS} 次：{last_error}")


def _cluster_round1_batch(
    client,
    config: RunConfig,
    batch: List[RawSignalItem],
    *,
    max_tokens: int = ROUND1_MAX_TOKENS,
) -> tuple[Round1ResponseLLM, Any]:
    """Call Round1; on truncated JSON, split the batch once and merge results."""
    try:
        return _llm_json_call(
            client,
            model=config.model_name,
            system=ROUND1_SYSTEM,
            user=build_round1_user_message(batch),
            schema_model=Round1ResponseLLM,
            max_tokens=max_tokens,
        )
    except RuntimeError as exc:
        if len(batch) <= 8 or not _is_truncated_json_error(exc):
            raise
        mid = max(1, len(batch) // 2)
        left, left_usage = _cluster_round1_batch(
            client, config, batch[:mid], max_tokens=max_tokens
        )
        right, right_usage = _cluster_round1_batch(
            client, config, batch[mid:], max_tokens=max_tokens
        )
        merged = Round1ResponseLLM(
            candidate_themes=list(left.candidate_themes) + list(right.candidate_themes)
        )
        usage = type(left_usage)(
            prompt_tokens=left_usage.prompt_tokens + right_usage.prompt_tokens,
            completion_tokens=left_usage.completion_tokens + right_usage.completion_tokens,
            prompt_cache_hit_tokens=(
                left_usage.prompt_cache_hit_tokens + right_usage.prompt_cache_hit_tokens
            ),
            prompt_cache_miss_tokens=(
                left_usage.prompt_cache_miss_tokens + right_usage.prompt_cache_miss_tokens
            ),
        )
        return merged, usage


def _cluster_round1_llm(
    client,
    config: RunConfig,
    signals: List[RawSignalItem],
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event=None,
) -> tuple[List[CandidateThemeLLM], int, int, int]:
    all_candidates: List[CandidateThemeLLM] = []
    prompt_tokens = 0
    completion_tokens = 0
    cache_hits = 0
    valid_ids = {s.signal_id for s in signals}
    batch_total = max(1, (len(signals) + BATCH_SIZE - 1) // BATCH_SIZE) if signals else 0
    signal_type_by_id = {s.signal_id: s.signal_type for s in signals}
    batches = [
        (batch_index, signals[start : start + BATCH_SIZE])
        for batch_index, start in enumerate(range(0, len(signals), BATCH_SIZE), start=1)
    ]

    def process_batch(batch_index: int, batch: List[RawSignalItem]):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("用户已停止开放主题归并")
        if on_progress is not None:
            on_progress(
                {
                    "phase": "round1",
                    "batch_index": batch_index,
                    "batch_total": batch_total,
                    "signal_count": len(signals),
                    "batch_started": True,
                }
            )
        parsed, usage = _cluster_round1_batch(client, config, batch)
        return batch_index, parsed, usage

    # Requests are independent within Round1. Keep concurrency intentionally
    # small so faster runs do not overwhelm provider rate limits.
    with ThreadPoolExecutor(
        max_workers=min(ROUND1_MAX_WORKERS, max(1, len(batches)))
    ) as pool:
        futures = [pool.submit(process_batch, index, batch) for index, batch in batches]
        completed = {}
        for future in as_completed(futures):
            batch_index, parsed, usage = future.result()
            completed[batch_index] = (parsed, usage)
            if on_progress is not None:
                on_progress(
                    {
                        "phase": "round1",
                        "batch_index": batch_index,
                        "batch_total": batch_total,
                        "signal_count": len(signals),
                        "batch_completed": True,
                    }
                )

    # Consume in stable input order so theme IDs and artifacts are deterministic.
    for batch_index in sorted(completed):
        parsed, usage = completed[batch_index]
        prompt_tokens += usage.prompt_tokens
        completion_tokens += usage.completion_tokens
        cache_hits += usage.prompt_cache_hit_tokens
        for cand in parsed.candidate_themes:
            cand.included_signal_ids = resolve_signal_ids(cand.included_signal_ids, valid_ids)
            if not cand.included_signal_ids:
                continue
            if not cand.theme_type or cand.theme_type == "other":
                type_counts: Dict[str, int] = {}
                for sid in cand.included_signal_ids:
                    st = signal_type_by_id.get(sid) or "other"
                    type_counts[st] = type_counts.get(st, 0) + 1
                cand.theme_type = max(type_counts, key=type_counts.get)
            all_candidates.append(cand)
    return all_candidates, prompt_tokens, completion_tokens, cache_hits


def _cluster_round2_llm(
    client,
    config: RunConfig,
    candidates: List[CandidateThemeLLM],
    cancel_event=None,
) -> tuple[List[ThemeRecord], int, int, int]:
    if not candidates:
        return [], 0, 0, 0
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("用户已停止开放主题归并")
    candidate_by_id = {
        f"c{index:04d}": candidate for index, candidate in enumerate(candidates, start=1)
    }
    payload = [
        {
            "candidate_id": candidate_id,
            "theme_name": candidate.theme_name,
            "theme_type": candidate.theme_type,
            "definition": candidate.definition,
            "signal_count": len(candidate.included_signal_ids),
            "relation_to_existing_hypotheses": candidate.relation_to_existing_hypotheses,
        }
        for candidate_id, candidate in candidate_by_id.items()
    ]
    parsed, usage = _llm_json_call(
        client,
        model=config.model_name,
        system=ROUND2_SYSTEM,
        user=build_round2_user_message(payload),
        schema_model=Round2ResponseLLM,
        max_tokens=ROUND2_MAX_TOKENS,
    )
    themes: List[ThemeRecord] = []
    for index, item in enumerate(parsed.themes, start=1):
        theme_id = f"t_{index:03d}_{uuid.uuid4().hex[:6]}"
        selected_candidates = []
        for raw_id in item.included_signal_ids:
            candidate_id = str(raw_id).strip()
            if candidate_id not in candidate_by_id and candidate_id.isdigit():
                candidate_id = f"c{int(candidate_id):04d}"
            candidate = candidate_by_id.get(candidate_id)
            if candidate is not None:
                selected_candidates.append(candidate)
        included = list(
            dict.fromkeys(
                sid
                for candidate in selected_candidates
                for sid in candidate.included_signal_ids
            )
        )
        if not included:
            continue
        themes.append(
            ThemeRecord(
                theme_id=theme_id,
                theme_name=item.theme_name,
                theme_type=item.theme_type,
                definition=item.definition,
                included_signal_ids=included,
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
    persist: bool = True,
    source_files: Optional[Set[str]] = None,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event=None,
) -> ThemesDocument:
    config = load_config(run_id)
    results = load_results(run_id)
    if source_files:
        allowed = set(source_files)
        results = [
            row
            for row in results
            if str((row.get("source") or {}).get("source_file") or "") in allowed
        ]
    if not results:
        if source_files:
            return ThemesDocument(
                model_name=config.model_name,
                created_at=datetime.now(timezone.utc).isoformat(),
                raw_signal_count=0,
                currency=config.currency,
            )
        raise ValueError("尚无分析结果，无法生成开放主题")

    signals = collect_raw_signals(results)
    if not signals:
        doc = ThemesDocument(
            model_name=config.model_name,
            created_at=datetime.now(timezone.utc).isoformat(),
            raw_signal_count=0,
            currency=config.currency,
        )
        if persist:
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
        candidates, p1, c1, h1 = _cluster_round1_llm(
            client, config, signals, on_progress=on_progress, cancel_event=cancel_event
        )
        if on_progress is not None:
            on_progress(
                {
                    "phase": "round2",
                    "batch_index": 0,
                    "batch_total": 0,
                    "signal_count": len(signals),
                    "candidate_count": len(candidates),
                }
            )
        themes, p2, c2, h2 = _cluster_round2_llm(
            client, config, candidates, cancel_event=cancel_event
        )
        prompt_tokens = p1 + p2
        completion_tokens = c1 + c2
        cache_hits = h1 + h2

    for theme in themes:
        theme.stats = compute_theme_stats(theme, signals)

    if source_files and len(source_files) == 1:
        themes = _namespace_theme_ids(themes, next(iter(source_files)))

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
        engine="legacy_llm_v1",
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
    if persist:
        save_themes(run_id, doc)
    return doc


def _namespace_theme_ids(themes: List[ThemeRecord], source_file: str) -> List[ThemeRecord]:
    """Prefix theme ids so per-video clusters stay unique when merged."""
    digest = hashlib.sha1(source_file.encode("utf-8")).hexdigest()[:6]
    prefix = f"v{digest}_"
    remapped: List[ThemeRecord] = []
    for theme in themes:
        theme_id = theme.theme_id
        if not theme_id.startswith(prefix):
            theme_id = f"{prefix}{theme_id}"
        remapped.append(theme.model_copy(update={"theme_id": theme_id}))
    return remapped


def merge_theme_documents(docs: List[ThemesDocument], *, model_name: str = "", currency: str = "CNY") -> ThemesDocument:
    """Merge independently clustered per-video theme docs into one canonical document."""
    themes: List[ThemeRecord] = []
    prompt_tokens = completion_tokens = cache_hits = 0
    cost = 0.0
    raw_signal_count = 0
    for doc in docs:
        themes.extend(doc.themes)
        prompt_tokens += doc.prompt_tokens
        completion_tokens += doc.completion_tokens
        cache_hits += doc.prompt_cache_hit_tokens
        cost += doc.cost
        raw_signal_count += doc.raw_signal_count
        model_name = model_name or doc.model_name
        currency = currency or doc.currency
    return ThemesDocument(
        engine="legacy_llm_v1",
        prompt_version=PROMPT_VERSION,
        model_name=model_name,
        created_at=datetime.now(timezone.utc).isoformat(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_cache_hit_tokens=cache_hits,
        cost=cost,
        currency=currency,
        raw_signal_count=raw_signal_count,
        themes=sorted(themes, key=lambda t: (-t.stats.comment_count, t.theme_name)),
    )
