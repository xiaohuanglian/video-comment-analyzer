# -*- coding: utf-8 -*-
"""Micro-batch + concurrent evidence extraction (evidence_items_v1)."""

from __future__ import annotations

import asyncio
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from openai import AsyncOpenAI
from pydantic import ValidationError

from .evidence_adapter import finalize_card
from .evidence_cache import evidence_fingerprint, get_cached_evidence, put_cached_evidence
from .evidence_prompts import EVIDENCE_SYSTEM_PROMPT, build_evidence_batch_user_message
from .evidence_schemas import (
    EvidenceBatchLLMOutput,
    EvidenceCard,
    EvidenceCardLLMItem,
    EvidenceItem,
    EvidenceItemType,
    EvidenceLevel,
    ItemCertainty,
    PrimaryExpression,
    RecordStatus,
    SpeakerScope,
    compute_evidence_level,
)
from .llm_analyzer import LlmUsage, build_openai_client, parse_usage
from .schemas import RunConfig, SourceRecord
from .validation import quote_exists, source_text_pool

SPLIT_SIZES = (20, 10, 5, 1)
DEFAULT_CONCURRENCY = 8


class AdaptiveGate:
    """Async concurrency gate whose limit can change without recreating workers."""

    def __init__(self, initial: int, *, maximum: int = 16) -> None:
        self.limit = max(1, min(maximum, initial))
        self.maximum = max(1, maximum)
        self._active = 0
        self._cv = asyncio.Condition()

    async def __aenter__(self) -> "AdaptiveGate":
        async with self._cv:
            while self._active >= self.limit:
                await self._cv.wait()
            self._active += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        async with self._cv:
            self._active = max(0, self._active - 1)
            self._cv.notify_all()

    async def set_limit(self, value: int) -> None:
        async with self._cv:
            self.limit = max(1, min(self.maximum, int(value)))
            self._cv.notify_all()


@dataclass
class BatchExtractStats:
    processed: int = 0
    failed: int = 0
    cache_hits: int = 0
    format_failures: int = 0
    retries: int = 0
    splits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    requests_count: int = 0
    batch_latencies: List[float] = field(default_factory=list)
    failed_ids: List[str] = field(default_factory=list)
    failed_errors: Dict[str, str] = field(default_factory=dict)
    performance: Dict[str, object] = field(default_factory=dict)
    concurrency: int = 1
    extract_elapsed_seconds: float = 0.0


@dataclass
class BatchExtractResult:
    cards: List[EvidenceCard]
    stats: BatchExtractStats


def _looks_like_spam(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    spam_tokens = ("加微信", "代刷", "免费领取", "点击链接", "http://", "https://")
    return any(token in stripped for token in spam_tokens) and len(stripped) < 80


def _looks_like_garbled(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    return bool(re.fullmatch(r"[\W_]+", stripped))


def _looks_like_machine_generated(text: str) -> bool:
    markers = ("本内容由AI视频小助理生成", "AI视频小助理", "由AI视频助理生成", "--本内容由AI")
    return any(m in (text or "") for m in markers)


def local_excluded_card(record: SourceRecord, status: RecordStatus, reason: str) -> EvidenceCard:
    card = EvidenceCard(
        record_id=record.internal_record_id,
        record_status=status,
        evidence_level=EvidenceLevel.NONE,
        status_reason=reason,
        primary_expression=PrimaryExpression.OTHER,
        evidence_items=[],
        confidence=0.95,
    )
    return finalize_card(card)


def evidence_item_count(card: EvidenceCard) -> int:
    return len(card.evidence_items or [])


def _sanitize_items(items: List[EvidenceItem], pool: str) -> List[EvidenceItem]:
    from .validation import _best_evidence_quote

    cleaned: List[EvidenceItem] = []
    for item in items or []:
        quote = (item.evidence_quote or "").strip()
        text = (item.text or "").strip()
        # Empty quote → drop (instruction: do not keep untraceable items)
        if not quote:
            continue
        if quote_exists(quote, pool):
            pass
        else:
            # Prefer repairing near-miss quotes over dropping the whole item
            repaired = _best_evidence_quote(quote, pool, limit=80) or _best_evidence_quote(text, pool, limit=80)
            if not repaired:
                continue
            quote = repaired
        data = item.model_dump()
        data["evidence_quote"] = quote
        data["text"] = text or quote[:40]
        cleaned.append(EvidenceItem.model_validate(data))
    return cleaned


def _bootstrap_items_from_text(record: SourceRecord) -> List[EvidenceItem]:
    """Last-resort local extraction when model returns empty usable card."""
    mock = extract_evidence_card_mock(record, finalize=False)
    if mock.record_status != RecordStatus.USABLE:
        return []
    return list(mock.evidence_items or [])


def sanitize_evidence_card(
    record: SourceRecord,
    card: EvidenceCard,
    *,
    allow_bootstrap: bool = True,
) -> EvidenceCard:
    pool = source_text_pool(record)
    text = (record.comment_text or "").strip()
    card.evidence_items = _sanitize_items(card.evidence_items or [], pool)

    if not text:
        card.record_status = RecordStatus.GARBLED
        card.status_reason = card.status_reason or "empty"
        card.evidence_items = []
    elif _looks_like_machine_generated(text):
        card.record_status = RecordStatus.MACHINE_GENERATED
        card.status_reason = card.status_reason or "machine_generated"
        card.evidence_items = []
    if card.record_status == RecordStatus.SPAM_OR_GARBLED:
        card.record_status = RecordStatus.GARBLED if _looks_like_garbled(text) or not text else RecordStatus.SPAM

    # Joke / off-topic should not stay as spam when clearly narrative gag
    if card.record_status == RecordStatus.SPAM and any(k in text for k in ("啤酒鸭", "纹身", "门什么时候")):
        card.record_status = RecordStatus.OFF_TOPIC
        card.status_reason = card.status_reason or "off_topic"

    # Recover empty usable cards with recoverable content (do not leave silent holes)
    if (
        allow_bootstrap
        and card.record_status == RecordStatus.USABLE
        and not card.evidence_items
        and text
        and len(text) >= 4
    ):
        boot = _bootstrap_items_from_text(record)
        if boot:
            card.evidence_items = _sanitize_items(boot, pool)
            card.downgrade_reason = card.downgrade_reason or "recovered_from_empty_model_output"

    if card.record_status == RecordStatus.USABLE and text:
        card.evidence_items = _enrich_missing_signal_items(record, card.evidence_items or [])

    card.contact_value_reason = ""
    card.possible_new_signal = []
    return finalize_card(card)


def _enrich_missing_signal_items(record: SourceRecord, items: List[EvidenceItem]) -> List[EvidenceItem]:
    """Code-side recall patch for high-confidence lexical signals the model often omits."""
    text = (record.comment_text or "").strip()
    pool = source_text_pool(record)
    out = list(items)

    def has(etype: EvidenceItemType, subtype: str = "") -> bool:
        for i in out:
            if i.type != etype:
                continue
            if not subtype or i.subtype == subtype:
                return True
        return False

    def add(etype: EvidenceItemType, summary: str, *, subtype: str = "", certainty: ItemCertainty = ItemCertainty.HIGH, quote_hint: str = "") -> None:
        from .validation import _best_evidence_quote

        quote = ""
        for hint in (quote_hint, summary):
            if hint and hint in text:
                quote = hint[:80]
                break
        if not quote:
            quote = _best_evidence_quote(quote_hint or summary, pool, limit=80) or _best_evidence_quote(text, pool, limit=48)
        if not quote:
            return
        out.append(
            EvidenceItem(
                type=etype,
                text=summary,
                evidence_quote=quote,
                speaker_scope=SpeakerScope.SELF,
                certainty=certainty,
                subtype=subtype,
            )
        )

    if ("办卡" in text or ("健身房" in text and "办" in text)) and not has(EvidenceItemType.BEHAVIOR, "sought_paid_help"):
        hint = "办卡" if "办卡" in text else "健身房"
        add(EvidenceItemType.BEHAVIOR, "付费办卡或健身房", subtype="sought_paid_help", quote_hint=hint)

    # Quantitative tokens commonly dropped on long plan lists
    for token, subtype in (
        ("10个", "reps"),
        ("20个", "reps"),
        ("25个", "reps"),
        ("50个", "reps"),
        ("80个", "reps"),
        ("100个", "reps"),
        ("10次", "reps"),
        ("20次", "reps"),
        ("15次", "reps"),
        ("45秒", "duration"),
        ("7个多月", "duration"),
        ("两个月", "duration"),
        ("九分钟", "duration"),
        ("一个月", "duration"),
        ("一组", "sets"),
        ("三组", "sets"),
        ("4组", "sets"),
    ):
        if token in text and not has(EvidenceItemType.QUANTITATIVE):
            add(EvidenceItemType.QUANTITATIVE, token, subtype=subtype, quote_hint=token)
            break
    if re.search(r"\d+\s*(个|次|秒|组|分钟|月)", text) and not has(EvidenceItemType.QUANTITATIVE):
        m = re.search(r"\d+\s*(?:个|次|秒|组|分钟|月)", text)
        if m:
            add(EvidenceItemType.QUANTITATIVE, m.group(0), subtype="reps", quote_hint=m.group(0))

    return out


def align_evidence_level(card: EvidenceCard) -> EvidenceCard:
    """Backward-compatible name — level is always code-owned via finalize_card."""
    return finalize_card(card)


def extract_evidence_card_mock(record: SourceRecord, *, finalize: bool = True) -> EvidenceCard:
    """Rule-based mock — zero paid API."""
    text = (record.comment_text or "").strip()
    if not text:
        return local_excluded_card(record, RecordStatus.GARBLED, "empty")
    if _looks_like_machine_generated(text):
        return local_excluded_card(record, RecordStatus.MACHINE_GENERATED, "machine_generated")
    if _looks_like_garbled(text):
        return local_excluded_card(record, RecordStatus.GARBLED, "garbled")
    if _looks_like_spam(text) and not any(k in text for k in ("谢谢", "打卡", "收藏", "太难", "开始练")):
        return local_excluded_card(record, RecordStatus.SPAM, "spam")
    if any(k in text for k in ("啤酒鸭", "连人带盒")) and "练" not in text[:10]:
        return local_excluded_card(record, RecordStatus.OFF_TOPIC, "off_topic_joke")
    if any(k in text for k in ("纹身", "门什么时候")) and not any(
        k in text for k in ("练", "俯卧撑", "倒立", "深蹲")
    ):
        return local_excluded_card(record, RecordStatus.OFF_TOPIC, "off_topic")

    items: List[EvidenceItem] = []
    expression = PrimaryExpression.OTHER

    def q(max_len: int = 48) -> str:
        return text[:max_len]

    def add(
        etype: EvidenceItemType,
        summary: str,
        *,
        subtype: str = "",
        scope: SpeakerScope = SpeakerScope.SELF,
        certainty: ItemCertainty = ItemCertainty.HIGH,
    ) -> None:
        items.append(
            EvidenceItem(
                type=etype,
                text=summary,
                evidence_quote=q(),
                speaker_scope=scope,
                certainty=certainty,
                subtype=subtype,
            )
        )

    if any(k in text for k in ("谢谢", "感谢", "太帅", "名不虚传")):
        expression = PrimaryExpression.PRAISE
        add(EvidenceItemType.OPINION, "赞赏或感谢", certainty=ItemCertainty.MEDIUM)
    if re.search(r"(?i)\bday\s*\d+\b", text) or text.strip() in {"Day3", "day3"}:
        expression = PrimaryExpression.CHECK_IN
        add(EvidenceItemType.ENGAGEMENT, "打卡天数", subtype="checked_in")
        add(EvidenceItemType.BEHAVIOR, "连续训练暗示", subtype="continued", certainty=ItemCertainty.MEDIUM)
    if any(k in text for k in ("打卡", "已打卡")):
        expression = PrimaryExpression.CHECK_IN if expression == PrimaryExpression.OTHER else expression
        add(EvidenceItemType.ENGAGEMENT, "评论区打卡", subtype="checked_in")
    if "收藏" in text:
        add(EvidenceItemType.ENGAGEMENT, "收藏", subtype="saved")
        if any(k in text for k in ("不练", "从不开始", "退出", "只是看看", "只看看", "看看就算")):
            subtype = "saved_but_not_started" if "收藏" in text else "watched_but_not_practiced"
            add(EvidenceItemType.ACTION_GAP, "改变意愿与行动落差", subtype=subtype)
            expression = expression if expression != PrimaryExpression.OTHER else PrimaryExpression.OTHER
    if any(k in text for k in ("关注了收藏了", "关注收藏就学会")):
        add(
            EvidenceItemType.ACTION_GAP,
            "对普遍不行动现象的观察",
            subtype="saved_but_not_started",
            scope=SpeakerScope.GENERAL_OBSERVATION,
            certainty=ItemCertainty.MEDIUM,
        )
    if any(k in text for k in ("?", "？", "吗", "怎么", "为什么", "正常吗", "有什么区别", "请加入")):
        expression = PrimaryExpression.QUESTION
        add(EvidenceItemType.PROBLEM, "提出疑问")
    if any(k in text for k in ("帮我", "求教", "怎么办")):
        expression = PrimaryExpression.HELP_REQUEST
        add(EvidenceItemType.PROBLEM, "主动求助")
    if any(k in text for k in ("计划", "打算练", "准备练", "明天继续")):
        add(EvidenceItemType.BEHAVIOR, "计划训练", subtype="planned")
    if any(k in text for k in ("可以", "会做")) and any(k in text for k in ("倒立", "俯卧撑", "引体")):
        add(EvidenceItemType.BEHAVIOR, "自报能力", subtype="self_reported_ability", certainty=ItemCertainty.MEDIUM)
    if any(k in text for k in ("做完", "刚做完")):
        add(EvidenceItemType.BEHAVIOR, "完成一次训练", subtype="completed_once")
        expression = PrimaryExpression.RESULT_FEEDBACK
    if any(k in text for k in ("练了", "做了", "试了", "跟练", "刚刚试", "做到")):
        add(EvidenceItemType.BEHAVIOR, "已尝试训练", subtype="attempted")
        if expression == PrimaryExpression.OTHER:
            expression = PrimaryExpression.RESULT_FEEDBACK
    if any(k in text for k in ("坚持", "每天", "继续练")) and any(k in text for k in ("周", "月", "年", "现在", "一周")):
        add(EvidenceItemType.BEHAVIOR, "持续训练", subtype="continued")
    if any(k in text for k in ("办卡", "健身房")):
        add(EvidenceItemType.BEHAVIOR, "付费办卡或健身房", subtype="sought_paid_help")
        if any(k in text for k in ("没有一点改变", "没变化", "无效果")):
            add(EvidenceItemType.ACTION_GAP, "付费后无结果", subtype="paid_but_no_result")
    if any(k in text for k in ("换成", "还不如直接上器械")):
        add(EvidenceItemType.BEHAVIOR, "调整训练方式", subtype="changed_plan", certainty=ItemCertainty.MEDIUM)
        add(EvidenceItemType.SOLUTION, "替代方案", certainty=ItemCertainty.MEDIUM)
    if any(k in text for k in ("酸", "痛", "太难", "做不到", "做不了", "学不会")):
        add(EvidenceItemType.BARRIER, "难度或体感障碍")
        if expression == PrimaryExpression.OTHER:
            expression = PrimaryExpression.COMPLAINT
    if any(k in text for k in ("先跑步", "小区健身", "自己搜")):
        add(EvidenceItemType.SOLUTION, "自行方案或建议", scope=SpeakerScope.GENERAL_OBSERVATION, certainty=ItemCertainty.MEDIUM)
    if any(k in text for k in ("产后", "膝盖", "腰", "体重", "斤", "腰间盘")):
        add(EvidenceItemType.CONTEXT, "用户提及身体或人群背景", certainty=ItemCertainty.MEDIUM)

    for token, subtype in (
        ("10个", "reps"),
        ("20个", "reps"),
        ("25个", "reps"),
        ("50个", "reps"),
        ("80个", "reps"),
        ("100", "reps"),
        ("45秒", "duration"),
        ("7个多月", "duration"),
        ("两个月", "duration"),
        ("200斤", "weight"),
        ("九分钟", "duration"),
        ("一个月", "duration"),
    ):
        if token in text:
            add(EvidenceItemType.QUANTITATIVE, token, subtype=subtype)

    if any(k in text for k in ("从", "到")) and any(k in text for k in ("个", "次")):
        add(EvidenceItemType.QUANTITATIVE, "能力进步", subtype="progress")
        add(EvidenceItemType.BEHAVIOR, "训练进步", subtype="progress")

    card = EvidenceCard(
        record_id=record.internal_record_id,
        record_status=RecordStatus.USABLE,
        primary_expression=expression,
        evidence_items=items,
        confidence=0.75,
    )
    if not finalize:
        return card
    return sanitize_evidence_card(record, card, allow_bootstrap=False)


def align_batch_cards(
    expected_ids: Sequence[str],
    raw_cards: Sequence[EvidenceCardLLMItem],
) -> Dict[str, EvidenceCardLLMItem]:
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("输入批次含重复 record_id")
    expected = set(expected_ids)
    mapped: Dict[str, EvidenceCardLLMItem] = {}
    for item in raw_cards:
        rid = (item.record_id or "").strip()
        if not rid or rid not in expected:
            continue
        if rid in mapped:
            raise ValueError(f"输出含重复 record_id: {rid}")
        mapped[rid] = item
    return mapped


def parse_batch_payload(payload: dict, expected_ids: Sequence[str]) -> Dict[str, EvidenceCardLLMItem]:
    if "cards" not in payload and isinstance(payload.get("results"), list):
        payload = {"cards": payload["results"]}
    batch = EvidenceBatchLLMOutput.model_validate(payload)
    return align_batch_cards(expected_ids, batch.cards)


def _llm_item_to_card(item: EvidenceCardLLMItem) -> EvidenceCard:
    return EvidenceCard.model_validate(
        {
            "record_id": item.record_id,
            "record_status": item.record_status,
            "primary_expression": item.primary_expression,
            "evidence_items": [i.model_dump() for i in item.evidence_items],
            "status_reason": item.status_reason,
        }
    )


def call_evidence_batch_llm(
    records: Sequence[SourceRecord],
    config: RunConfig,
    api_key: str,
    *,
    client=None,
) -> tuple[Dict[str, EvidenceCard], LlmUsage]:
    if not records:
        return {}, LlmUsage()
    expected_ids = [r.internal_record_id for r in records]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("输入批次含重复 record_id")

    llm = client or build_openai_client(config.base_url, api_key)
    compact = getattr(config, "project_context_compact", "") or ""
    messages = [
        {"role": "system", "content": EVIDENCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_evidence_batch_user_message(records, project_context_compact=compact),
        },
    ]
    last_error: Exception | None = None
    usage_total = LlmUsage()
    for attempt in range(2):
        completion = llm.chat.completions.create(
            model=config.model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        usage = parse_usage(getattr(completion, "usage", None))
        usage_total.prompt_tokens += usage.prompt_tokens
        usage_total.completion_tokens += usage.completion_tokens
        usage_total.prompt_cache_hit_tokens += usage.prompt_cache_hit_tokens
        raw = completion.choices[0].message.content or ""
        try:
            payload = json.loads(raw)
            mapped = parse_batch_payload(payload, expected_ids)
            missing = [rid for rid in expected_ids if rid not in mapped]
            if missing:
                raise ValueError(f"批次漏项: {missing[:5]}{'…' if len(missing) > 5 else ''}")
            cards = {rid: _llm_item_to_card(item) for rid, item in mapped.items()}
            return cards, usage_total
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            last_error = exc
            if attempt == 0:
                messages = messages + [
                    {
                        "role": "user",
                        "content": (
                            f"上次输出无法对齐（{type(exc).__name__}: {exc}）。"
                            f"请返回含 cards 数组的 JSON，且恰好覆盖这些 record_id："
                            f"{json.dumps(expected_ids, ensure_ascii=False)}"
                        ),
                    }
                ]
            continue
    raise ValueError(f"证据批次 JSON 无法解析: {last_error}")


async def call_evidence_batch_llm_async(
    records: Sequence[SourceRecord],
    config: RunConfig,
    api_key: str,
    *,
    client: Optional[AsyncOpenAI] = None,
) -> tuple[Dict[str, EvidenceCard], LlmUsage]:
    if not records:
        return {}, LlmUsage()
    expected_ids = [r.internal_record_id for r in records]
    owns_client = client is None
    llm = client or AsyncOpenAI(api_key=api_key, base_url=(config.base_url or None) or None)
    compact = getattr(config, "project_context_compact", "") or ""
    messages = [
        {"role": "system", "content": EVIDENCE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_evidence_batch_user_message(records, project_context_compact=compact),
        },
    ]
    last_error: Exception | None = None
    usage_total = LlmUsage()
    try:
        for attempt in range(2):
            completion = None
            for rate_try in range(5):
                try:
                    completion = await llm.chat.completions.create(
                        model=config.model_name,
                        messages=messages,
                        response_format={"type": "json_object"},
                        temperature=0.2,
                    )
                    break
                except Exception as rate_exc:
                    msg = str(rate_exc).lower()
                    is_429 = (
                        "429" in msg
                        or "rate limit" in msg
                        or "rate_limit" in msg
                        or type(rate_exc).__name__ == "RateLimitError"
                        or getattr(rate_exc, "status_code", None) == 429
                    )
                    if not is_429 or rate_try >= 4:
                        raise
                    await asyncio.sleep(min(32.0, (2**rate_try) + 0.5))
            if completion is None:
                raise ValueError("证据批次请求失败：无响应")
            usage = parse_usage(getattr(completion, "usage", None))
            usage_total.prompt_tokens += usage.prompt_tokens
            usage_total.completion_tokens += usage.completion_tokens
            usage_total.prompt_cache_hit_tokens += usage.prompt_cache_hit_tokens
            raw = completion.choices[0].message.content or ""
            try:
                payload = json.loads(raw)
                mapped = parse_batch_payload(payload, expected_ids)
                missing = [rid for rid in expected_ids if rid not in mapped]
                if missing:
                    raise ValueError(f"批次漏项: {missing[:5]}")
                return {rid: _llm_item_to_card(item) for rid, item in mapped.items()}, usage_total
            except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
                last_error = exc
                if attempt == 0:
                    messages = messages + [
                        {
                            "role": "user",
                            "content": (
                                f"上次输出无法对齐（{type(exc).__name__}: {exc}）。"
                                f"请返回含 cards 的 JSON，覆盖："
                                f"{json.dumps(expected_ids, ensure_ascii=False)}"
                            ),
                        }
                    ]
                continue
        raise ValueError(f"证据批次 JSON 无法解析: {last_error}")
    finally:
        if owns_client:
            await llm.close()


def _short_circuit_card(record: SourceRecord) -> Optional[EvidenceCard]:
    text = (record.comment_text or "").strip()
    if not text:
        return local_excluded_card(record, RecordStatus.GARBLED, "empty")
    if _looks_like_machine_generated(text):
        return local_excluded_card(record, RecordStatus.MACHINE_GENERATED, "machine_generated")
    if _looks_like_garbled(text):
        return local_excluded_card(record, RecordStatus.GARBLED, "garbled")
    if any(k in text for k in ("啤酒鸭", "连人带盒")) and "练" not in text[:10]:
        return local_excluded_card(record, RecordStatus.OFF_TOPIC, "off_topic_joke")
    if any(k in text for k in ("纹身", "门什么时候")) and not any(
        k in text for k in ("练", "俯卧撑", "倒立", "深蹲")
    ):
        return local_excluded_card(record, RecordStatus.OFF_TOPIC, "off_topic")
    if _looks_like_spam(text) and not any(k in text for k in ("谢谢", "打卡", "收藏", "太难", "开始练")):
        return local_excluded_card(record, RecordStatus.SPAM, "spam")
    return None


def _chunk_records(records: Sequence[SourceRecord], batch_size: int) -> List[List[SourceRecord]]:
    size = max(1, min(batch_size, 30))
    # Shorter batches when many long comments
    long_n = sum(1 for r in records if len(r.comment_text or "") > 180)
    if long_n >= max(3, len(records) // 3):
        size = min(size, 15)
    return [list(records[i : i + size]) for i in range(0, len(records), size)]


async def _extract_batches_concurrent(
    batches: List[List[SourceRecord]],
    *,
    use_mock: bool,
    config: Optional[RunConfig],
    api_key: str,
    concurrency: int,
    stats: BatchExtractStats,
    call_fn=None,
) -> Dict[str, EvidenceCard]:
    done: Dict[str, EvidenceCard] = {}
    gate = AdaptiveGate(max(1, concurrency), maximum=16)
    adaptive = max(1, concurrency)
    success_streak = 0
    fail_streak = 0
    lock = asyncio.Lock()
    client: Optional[AsyncOpenAI] = None
    if not use_mock and config is not None:
        client = AsyncOpenAI(api_key=api_key, base_url=(config.base_url or None) or None)

    def _fp(record: SourceRecord) -> str:
        return evidence_fingerprint(
            record,
            project_version=getattr(config, "project_version", "1") if config else "1",
            model_name=getattr(config, "model_name", "") if config else "",
            project_context_compact=getattr(config, "project_context_compact", "") if config else "",
        )

    async def one_batch(chunk: List[SourceRecord]) -> None:
        nonlocal adaptive, success_streak, fail_streak
        need_llm: List[SourceRecord] = []
        for record in chunk:
            short = _short_circuit_card(record)
            if short is not None:
                async with lock:
                    done[short.record_id] = short
                    stats.processed += 1
                continue
            if config is not None:
                cached = get_cached_evidence(_fp(record))
                if cached is not None:
                    card = cached.model_copy(deep=True)
                    card.record_id = record.internal_record_id
                    card.reused_from_record_id = cached.record_id or "cache"
                    card = finalize_card(card)
                    async with lock:
                        done[card.record_id] = card
                        stats.processed += 1
                        stats.cache_hits += 1
                    continue
            need_llm.append(record)
        if not need_llm:
            return

        async with gate:
            started = time.perf_counter()
            try:
                if use_mock:
                    mapped = {r.internal_record_id: extract_evidence_card_mock(r) for r in need_llm}
                    usage = LlmUsage()
                elif call_fn is not None:
                    loop = asyncio.get_running_loop()
                    mapped, usage = await loop.run_in_executor(
                        None, lambda: call_fn(need_llm, config, api_key, client=None)
                    )
                    async with lock:
                        stats.requests_count += 1
                else:
                    mapped, usage = await call_evidence_batch_llm_async(
                        need_llm, config, api_key, client=client
                    )
                    async with lock:
                        stats.requests_count += 1
                async with lock:
                    stats.batch_latencies.append(time.perf_counter() - started)
                    stats.prompt_tokens += usage.prompt_tokens
                    stats.completion_tokens += usage.completion_tokens
                    stats.cache_hit_tokens += getattr(usage, "prompt_cache_hit_tokens", 0) or 0
                    success_streak += 1
                    fail_streak = 0
                    bump = False
                    if success_streak >= 4 and adaptive < 16 and concurrency >= 8:
                        adaptive = min(16, adaptive + 4)
                        bump = True
                if bump:
                    await gate.set_limit(adaptive)
                for record in need_llm:
                    card = mapped.get(record.internal_record_id)
                    if card is None:
                        raise ValueError(f"缺少 record_id={record.internal_record_id}")
                    card = sanitize_evidence_card(record, card)
                    card.record_id = record.internal_record_id
                    if config is not None:
                        put_cached_evidence(_fp(record), card)
                    async with lock:
                        done[card.record_id] = card
                        stats.processed += 1
            except Exception as exc:
                msg = str(exc).lower()
                is_429 = "429" in msg or "rate limit" in msg or "rate_limit" in msg
                drop = False
                async with lock:
                    stats.format_failures += 1
                    stats.retries += 1
                    fail_streak += 1
                    success_streak = 0
                    if fail_streak >= 2 or is_429:
                        adaptive = 4
                        drop = True
                if drop:
                    await gate.set_limit(adaptive)
                if is_429:
                    await asyncio.sleep(2.0)
                if len(need_llm) <= 1:
                    for record in need_llm:
                        async with lock:
                            stats.failed += 1
                            stats.failed_ids.append(record.internal_record_id)
                            stats.failed_errors[record.internal_record_id] = str(exc)
                    return
                async with lock:
                    stats.splits += 1
                next_size = 10 if len(need_llm) > 10 else (5 if len(need_llm) > 5 else 1)
                for i in range(0, len(need_llm), next_size):
                    await one_batch(need_llm[i : i + next_size])

    try:
        await asyncio.gather(*(one_batch(b) for b in batches))
    finally:
        if client is not None:
            await client.close()
    stats.concurrency = adaptive
    return done


def extract_batch_with_split(
    records: Sequence[SourceRecord],
    *,
    use_mock: bool,
    config: Optional[RunConfig] = None,
    api_key: str = "",
    client=None,
    call_fn: Optional[Callable[..., tuple[Dict[str, EvidenceCard], LlmUsage]]] = None,
    batch_size: int = 20,
    stats: Optional[BatchExtractStats] = None,
    concurrency: Optional[int] = None,
) -> BatchExtractResult:
    """Extract with concurrent micro-batches; split on failure."""
    stats = stats or BatchExtractStats()
    if not records:
        return BatchExtractResult(cards=[], stats=stats)

    conc = concurrency
    if conc is None:
        conc = int(getattr(config, "concurrency", DEFAULT_CONCURRENCY) or DEFAULT_CONCURRENCY) if config else 1
    if use_mock:
        conc = max(1, min(conc, 4))
    stats.concurrency = conc

    from .performance_metrics import PerformanceMetrics

    perf = PerformanceMetrics()
    perf.mark_start()
    extract_started = time.perf_counter()

    batches = _chunk_records(records, batch_size)
    # Sync path for single-thread / explicit sync client tests with call_fn and concurrency=1
    if conc <= 1 and (use_mock or call_fn is not None or client is not None):
        done_cards: Dict[str, EvidenceCard] = {}
        for chunk in batches:
            _process_chunk_sync(
                chunk,
                size_hint=batch_size,
                use_mock=use_mock,
                config=config,
                api_key=api_key,
                client=client,
                call_fn=call_fn,
                stats=stats,
                done_cards=done_cards,
            )
        ordered = [done_cards[r.internal_record_id] for r in records if r.internal_record_id in done_cards]
    else:
        done_cards = asyncio.run(
            _extract_batches_concurrent(
                batches,
                use_mock=use_mock,
                config=config,
                api_key=api_key,
                concurrency=conc,
                stats=stats,
                call_fn=call_fn,
            )
        )
        ordered = [done_cards[r.internal_record_id] for r in records if r.internal_record_id in done_cards]

    stats.extract_elapsed_seconds = time.perf_counter() - extract_started
    size = max(1, min(batch_size, 30))
    for latency in stats.batch_latencies:
        perf.add_batch_latency(latency)
    stats.performance = perf.finalize(
        processed=stats.processed,
        failed=stats.failed,
        cache_hits=stats.cache_hits,
        format_failures=stats.format_failures,
        splits=stats.splits,
        retry_count=stats.retries,
        requests_count=stats.requests_count,
        prompt_tokens=stats.prompt_tokens,
        completion_tokens=stats.completion_tokens,
        cache_hit_tokens=stats.cache_hit_tokens,
        batch_size=size,
        concurrency=stats.concurrency,
        model_name=getattr(config, "model_name", "") if config else "",
        input_price=getattr(config, "input_price", None) if config else None,
        output_price=getattr(config, "output_price", None) if config else None,
        currency=getattr(config, "currency", "CNY") if config else "CNY",
    )
    stats.performance["extract_elapsed_seconds"] = round(stats.extract_elapsed_seconds, 3)
    stats.performance["comments_per_hour"] = (
        round(stats.processed / (stats.extract_elapsed_seconds / 3600), 1)
        if stats.extract_elapsed_seconds > 0
        else 0
    )
    return BatchExtractResult(cards=ordered, stats=stats)


def _process_chunk_sync(
    chunk: List[SourceRecord],
    *,
    size_hint: int,
    use_mock: bool,
    config: Optional[RunConfig],
    api_key: str,
    client,
    call_fn,
    stats: BatchExtractStats,
    done_cards: Dict[str, EvidenceCard],
) -> None:
    if not chunk:
        return
    need_llm: List[SourceRecord] = []
    for record in chunk:
        short = _short_circuit_card(record)
        if short is not None:
            done_cards[short.record_id] = short
            stats.processed += 1
            continue
        if config is not None:
            fp = evidence_fingerprint(
                record,
                project_version=config.project_version,
                model_name=config.model_name,
                project_context_compact=getattr(config, "project_context_compact", "") or "",
            )
            cached = get_cached_evidence(fp)
            if cached is not None:
                card = cached.model_copy(deep=True)
                card.record_id = record.internal_record_id
                card.reused_from_record_id = cached.record_id or "cache"
                done_cards[card.record_id] = finalize_card(card)
                stats.processed += 1
                stats.cache_hits += 1
                continue
        need_llm.append(record)
    if not need_llm:
        return
    started = time.perf_counter()
    try:
        if use_mock:
            mapped = {r.internal_record_id: extract_evidence_card_mock(r) for r in need_llm}
            usage = LlmUsage()
        else:
            fn = call_fn or call_evidence_batch_llm
            mapped, usage = fn(need_llm, config, api_key, client=client)
            stats.requests_count += 1
        stats.batch_latencies.append(time.perf_counter() - started)
        stats.prompt_tokens += usage.prompt_tokens
        stats.completion_tokens += usage.completion_tokens
        stats.cache_hit_tokens += getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        for record in need_llm:
            card = mapped.get(record.internal_record_id)
            if card is None:
                raise ValueError(f"缺少 record_id={record.internal_record_id}")
            card = sanitize_evidence_card(record, card)
            card.record_id = record.internal_record_id
            if config is not None:
                fp = evidence_fingerprint(
                    record,
                    project_version=config.project_version,
                    model_name=config.model_name,
                    project_context_compact=getattr(config, "project_context_compact", "") or "",
                )
                put_cached_evidence(fp, card)
            done_cards[card.record_id] = card
            stats.processed += 1
    except Exception as exc:
        stats.format_failures += 1
        stats.retries += 1
        next_size = None
        for candidate in SPLIT_SIZES:
            if candidate < size_hint:
                next_size = candidate
                break
        if next_size is None or len(need_llm) <= 1:
            for record in need_llm:
                rid = record.internal_record_id
                stats.failed += 1
                stats.failed_ids.append(rid)
                stats.failed_errors[rid] = str(exc)
            return
        stats.splits += 1
        for i in range(0, len(need_llm), next_size):
            _process_chunk_sync(
                need_llm[i : i + next_size],
                size_hint=next_size,
                use_mock=use_mock,
                config=config,
                api_key=api_key,
                client=client,
                call_fn=call_fn,
                stats=stats,
                done_cards=done_cards,
            )


def run_evidence_extraction(
    records: Sequence[SourceRecord],
    *,
    use_mock: bool = True,
    config: Optional[RunConfig] = None,
    api_key: str = "",
    batch_size: int = 20,
    skip_ids: Optional[Set[str]] = None,
    call_fn=None,
    concurrency: Optional[int] = None,
) -> BatchExtractResult:
    skip = skip_ids or set()
    pending = [r for r in records if r.internal_record_id not in skip]
    return extract_batch_with_split(
        pending,
        use_mock=use_mock,
        config=config,
        api_key=api_key,
        batch_size=batch_size,
        call_fn=call_fn,
        concurrency=concurrency,
    )


# Back-compat aliases used by older tests
def local_spam_card(record: SourceRecord, reason: str = "spam") -> EvidenceCard:
    status = RecordStatus.GARBLED if reason in {"empty", "garbled"} else RecordStatus.SPAM
    return local_excluded_card(record, status, reason)


def local_off_topic_card(record: SourceRecord, reason: str = "off_topic") -> EvidenceCard:
    return local_excluded_card(record, RecordStatus.OFF_TOPIC, reason)


def local_machine_generated_card(record: SourceRecord, reason: str = "machine_generated") -> EvidenceCard:
    return local_excluded_card(record, RecordStatus.MACHINE_GENERATED, reason)
