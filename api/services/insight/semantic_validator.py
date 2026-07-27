# -*- coding: utf-8 -*-
"""Precision-first semantic validation for evidence-backed report claims."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set

from pydantic import BaseModel, Field

from .evidence_adapter import has_explicit_paid_action, has_paid_failure
from .evidence_schemas import (
    EvidenceCard,
    EvidenceItem,
    EvidenceItemType,
    ItemCertainty,
    ResearchAnalysis,
    SpeakerScope,
)
from .schemas import SourceRecord


class SemanticVerdict(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    NEEDS_REVIEW = "needs_review"


class SemanticClaim(BaseModel):
    claim_id: str
    section: str
    text: str
    record_ids: List[str] = Field(default_factory=list)
    evidence_item_ids: List[str] = Field(default_factory=list)
    evidence_quotes: List[str] = Field(default_factory=list)
    evidence_types: List[str] = Field(default_factory=list)
    evidence_subtypes: List[str] = Field(default_factory=list)
    evidence_scopes: List[str] = Field(default_factory=list)
    record_count: int = 0
    hard_verdict: SemanticVerdict = SemanticVerdict.NEEDS_REVIEW
    hard_reasons: List[str] = Field(default_factory=list)


class SemanticClaimReview(BaseModel):
    claim_id: str
    verdict: SemanticVerdict
    reason: str = ""
    source: str = "code"


class SemanticReviewDocument(BaseModel):
    passed: bool = True
    claims: List[SemanticClaim] = Field(default_factory=list)
    reviews: List[SemanticClaimReview] = Field(default_factory=list)
    removed_claim_ids: List[str] = Field(default_factory=list)
    downgraded_claim_ids: List[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    cost: float = 0.0
    source_file: str = ""
    error: str = ""


_SELF_MARKERS = (
    "我",
    "本人",
    "自己",
    "练了",
    "做了",
    "试了",
    "坚持",
    "已经",
    "刚刚",
    "刚才",
    "亲测",
    "做完",
    "练完",
)
_OTHER_MARKERS = ("朋友", "别人", "他练", "她练", "我妈", "我爸", "孩子", "同事")
_ACTION_MARKERS = (
    "练",
    "做",
    "试",
    "测",
    "打卡",
    "坚持",
    "购买",
    "买了",
    "付了",
    "花了",
    "办卡",
    "报名",
    "跟练",
    "看医生",
    "挂号",
)
_POSITIVE_MARKERS = (
    "有效",
    "改善",
    "舒服",
    "缓解",
    "好转",
    "成功",
    "回正",
    "省钱",
    "不疼",
    "没以前",
)
_NEGATIVE_MARKERS = (
    "没效果",
    "没有效果",
    "无效",
    "更疼",
    "加重",
    "没改善",
    "没有改善",
    "放弃",
    "做不到",
    "不会",
    "困难",
    "太难",
)
_PREVALENCE_MARKERS = ("大部分", "多数", "普遍", "广泛", "绝大多数")
_CAUSAL_MARKERS = (
    "证明",
    "必然",
    "一定会",
    "导致",
    "造成",
    "提升付费",
    "提高付费",
    "市场空白",
)
_MEDICAL_OVERREACH = ("治愈", "确诊", "治疗有效", "康复成功", "医学证明")


def sanitize_item_semantics(
    record: SourceRecord,
    items: Sequence[EvidenceItem],
) -> List[EvidenceItem]:
    """Conservatively normalize item semantics to their exact quote."""
    out: List[EvidenceItem] = []
    for original in items:
        item = original.model_copy(deep=True)
        quote = (item.evidence_quote or "").strip()
        if not quote:
            continue
        # Downstream rules must never be triggered by an ungrounded paraphrase.
        item.text = quote
        if (
            item.speaker_scope == SpeakerScope.SELF
            and (
                any(marker in quote for marker in _OTHER_MARKERS)
                or not any(marker in quote for marker in _SELF_MARKERS)
            )
            and item.type in {EvidenceItemType.BEHAVIOR, EvidenceItemType.RESULT}
        ):
            item.speaker_scope = SpeakerScope.UNCLEAR
            item.certainty = ItemCertainty.LOW
        if (
            item.type == EvidenceItemType.BEHAVIOR
            and item.subtype
            in {
                "attempted",
                "completed_once",
                "continued",
                "stopped",
                "sought_paid_help",
            }
            and not any(marker in quote for marker in _ACTION_MARKERS)
        ):
            item.subtype = ""
            item.certainty = ItemCertainty.LOW
        out.append(item)
    return out


def _item_index(card_rows: Sequence[dict]) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for row in card_rows:
        try:
            card = EvidenceCard.model_validate(row.get("card") or row)
        except Exception:
            continue
        for item in card.evidence_items or []:
            if not item.evidence_item_id:
                continue
            index[item.evidence_item_id] = {
                "record_id": card.record_id,
                "evidence_item_id": item.evidence_item_id,
                "quote": item.evidence_quote,
                "type": item.type.value,
                "subtype": item.subtype,
                "scope": item.speaker_scope.value,
            }
    return index


def build_manual_audit_samples(
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
    *,
    per_source: int = 30,
) -> Dict[str, dict]:
    """Create stable per-video samples for human precision recording."""
    rows_by_id = {str(row.get("record_id") or ""): row for row in card_rows}
    by_source: Dict[str, List[SourceRecord]] = {}
    for record in records:
        by_source.setdefault(record.source_file or "unknown", []).append(record)
    output: Dict[str, dict] = {}
    for source_file, source_records in by_source.items():
        ordered = sorted(
            source_records,
            key=lambda record: hashlib.sha256(
                f"{source_file}|{record.internal_record_id}".encode("utf-8")
            ).hexdigest(),
        )[: max(0, per_source)]
        items = []
        for record in ordered:
            row = rows_by_id.get(record.internal_record_id) or {}
            card = row.get("card") or {}
            items.append(
                {
                    "record_id": record.internal_record_id,
                    "comment_text": record.comment_text,
                    "evidence_items": [
                        {
                            "type": item.get("type"),
                            "subtype": item.get("subtype"),
                            "quote": item.get("evidence_quote"),
                        }
                        for item in (card.get("evidence_items") or [])
                    ],
                    "manual_supported": None,
                    "manual_note": "",
                }
            )
        output[source_file] = {
            "sample_size": len(items),
            "items": items,
            "reviewed_count": 0,
            "precision": None,
        }
    return output


def _refs_payload(refs: Any, item_index: Dict[str, dict]) -> dict:
    record_ids: List[str] = []
    item_ids: List[str] = []
    quotes: List[str] = []
    types: List[str] = []
    subtypes: List[str] = []
    scopes: List[str] = []
    for raw in refs or []:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            continue
        eid = str(raw.get("evidence_item_id") or "")
        item = item_index.get(eid)
        if not item:
            continue
        rid = str(item.get("record_id") or "")
        if rid and rid not in record_ids:
            record_ids.append(rid)
        if eid and eid not in item_ids:
            item_ids.append(eid)
        quote = str(item.get("quote") or "")
        if quote and quote not in quotes:
            quotes.append(quote)
        item_type = str(item.get("type") or "")
        subtype = str(item.get("subtype") or "")
        scope = str(item.get("scope") or "")
        if item_type and item_type not in types:
            types.append(item_type)
        if subtype and subtype not in subtypes:
            subtypes.append(subtype)
        if scope and scope not in scopes:
            scopes.append(scope)
    return {
        "record_ids": record_ids,
        "evidence_item_ids": item_ids,
        "evidence_quotes": quotes,
        "evidence_types": types,
        "evidence_subtypes": subtypes,
        "evidence_scopes": scopes,
    }


def _hard_review_claim(
    claim: SemanticClaim,
    *,
    total_comments: int,
    allowed_record_ids: Set[str],
) -> SemanticClaim:
    reasons: List[str] = []
    verdict = SemanticVerdict.NEEDS_REVIEW
    evidence = " ".join(claim.evidence_quotes)
    text = claim.text

    if not claim.evidence_quotes:
        if claim.section == "open_theme" and claim.record_ids and claim.record_count >= 1:
            pass
        else:
            verdict = SemanticVerdict.INSUFFICIENT
            reasons.append("没有可追溯原文")
    if any(rid not in allowed_record_ids for rid in claim.record_ids):
        verdict = SemanticVerdict.CONTRADICTED
        reasons.append("引用跨出当前影片")
    paid_action_claim = any(
        marker in text
        for marker in (
            "已付费",
            "实际付费",
            "付费购买",
            "付费但",
            "花钱",
            "成交",
            "办卡",
            "报名购买",
        )
    )
    if paid_action_claim:
        paid_ok = (
            has_paid_failure(evidence)
            if any(word in text for word in ("无结果", "没结果", "无效果", "失败"))
            else has_explicit_paid_action(evidence)
        )
        if not paid_ok:
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("原文不支持实际付费或付费失败")
    if any(marker in text for marker in ("付费意愿", "愿意付费", "愿意购买")):
        if not any(
            marker in evidence
            for marker in ("我愿意付费", "愿意付费", "愿意购买", "多少钱", "怎么买")
        ):
            verdict = SemanticVerdict.INSUFFICIENT
            reasons.append("原文不支持付费意愿")
    if any(marker in text for marker in _PREVALENCE_MARKERS):
        rate = claim.record_count / total_comments if total_comments else 0.0
        if rate <= 0.5:
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("覆盖率不足以支持多数或普遍表述")
    if any(marker in text for marker in _CAUSAL_MARKERS):
        verdict = SemanticVerdict.INSUFFICIENT
        reasons.append("评论观察不能证明因果、市场或付费提升")
    if any(marker in text for marker in _MEDICAL_OVERREACH):
        verdict = SemanticVerdict.INSUFFICIENT
        reasons.append("评论自述不能支持医疗结论")
    if any(marker in text for marker in ("已经行动", "持续训练", "真实行为")):
        if "behavior" not in claim.evidence_types:
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("缺少行为类型证据")
        elif claim.evidence_subtypes and set(claim.evidence_subtypes) <= {"planned"}:
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("计划不能作为已经执行的证据")
    if any(marker in text for marker in ("本人", "用户自己", "亲身")):
        if "self" not in claim.evidence_scopes:
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("他人或泛指经历不能归因给评论者本人")
    if any(marker in text for marker in ("明显改善", "有效果", "获得结果")):
        if "result" not in claim.evidence_types or not any(
            marker in evidence for marker in _POSITIVE_MARKERS
        ):
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("缺少正向结果证据")
    if any(marker in text for marker in ("无效", "没有改善", "负向结果")):
        if not any(marker in evidence for marker in _NEGATIVE_MARKERS):
            verdict = SemanticVerdict.CONTRADICTED
            reasons.append("缺少负向结果证据")

    claim.hard_verdict = verdict
    claim.hard_reasons = reasons
    return claim


def build_claim_ledger(
    analysis: ResearchAnalysis,
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
) -> List[SemanticClaim]:
    item_index = _item_index(card_rows)
    allowed = {record.internal_record_id for record in records}
    total = max(1, analysis.dataset_summary.usable_comments or len(records))
    claims: List[SemanticClaim] = []

    for theme in analysis.themes:
        refs = _refs_payload(theme.representative_evidence_refs, item_index)
        claim = SemanticClaim(
            claim_id=f"theme:{theme.theme_id}",
            section="theme",
            text=f"{theme.theme_name}：{theme.theme_definition}",
            record_count=theme.comment_count or len(theme.comment_record_ids),
            **refs,
        )
        claims.append(_hard_review_claim(claim, total_comments=total, allowed_record_ids=allowed))

    for index, finding in enumerate(analysis.unexpected_findings):
        refs = _refs_payload(finding.supporting_evidence_refs, item_index)
        claim = SemanticClaim(
            claim_id=f"finding:{index}",
            section="finding",
            text="；".join(
                value
                for value in (finding.finding, finding.conclusion, finding.why_it_matters)
                if value
            ),
            record_count=len(finding.record_ids),
            **refs,
        )
        claims.append(_hard_review_claim(claim, total_comments=total, allowed_record_ids=allowed))

    for hypothesis in analysis.hypothesis_assessment:
        refs = _refs_payload(
            [*hypothesis.supporting_evidence_refs, *hypothesis.weakening_evidence_refs],
            item_index,
        )
        claim = SemanticClaim(
            claim_id=f"hypothesis:{hypothesis.hypothesis_id}",
            section="hypothesis",
            text=hypothesis.reasoning_summary,
            record_count=len(hypothesis.supporting_record_ids),
            **refs,
        )
        claims.append(_hard_review_claim(claim, total_comments=total, allowed_record_ids=allowed))

    for index, opportunity in enumerate(analysis.opportunity_hypotheses):
        refs = _refs_payload(
            [
                *opportunity.supporting_evidence_refs,
                *opportunity.counter_evidence_refs,
                *opportunity.behavior_evidence_refs,
            ],
            item_index,
        )
        claim = SemanticClaim(
            claim_id=f"opportunity:{index}",
            section="opportunity",
            text="；".join(
                value
                for value in (
                    opportunity.opportunity_name,
                    opportunity.target_users,
                    opportunity.concrete_problem,
                )
                if value
            ),
            record_count=len(opportunity.supporting_record_ids),
            **refs,
        )
        claims.append(_hard_review_claim(claim, total_comments=total, allowed_record_ids=allowed))
    return claims[:20]


def _parse_review_payload(raw: str) -> Dict[str, Any]:
    value = (raw or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end < start:
        raise ValueError("语义审查未返回 JSON")
    payload = json.loads(value[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("语义审查 JSON 顶层必须是对象")
    return payload


def run_semantic_review(
    analysis: ResearchAnalysis,
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
    *,
    config: Any,
    api_key: str,
    use_mock: bool,
    source_file: str = "",
    client: Any = None,
) -> tuple[ResearchAnalysis, SemanticReviewDocument]:
    """Review every candidate claim and return a filtered research payload."""
    from .evidence_prompts import (
        SEMANTIC_REVIEW_SYSTEM_PROMPT,
        build_semantic_review_user_message,
    )
    from .llm_analyzer import estimate_cost, parse_usage
    from .pricing import resolve_pricing

    claims = build_claim_ledger(analysis, records, card_rows)
    reviews: Dict[str, SemanticClaimReview] = {}
    candidates: List[SemanticClaim] = []
    for claim in claims:
        if claim.hard_verdict in {
            SemanticVerdict.CONTRADICTED,
            SemanticVerdict.INSUFFICIENT,
        }:
            reviews[claim.claim_id] = SemanticClaimReview(
                claim_id=claim.claim_id,
                verdict=claim.hard_verdict,
                reason="；".join(claim.hard_reasons),
                source="hard_rule",
            )
        else:
            candidates.append(claim)

    prompt_tokens = completion_tokens = cache_hits = 0
    error = ""
    if use_mock:
        for claim in candidates:
            reviews[claim.claim_id] = SemanticClaimReview(
                claim_id=claim.claim_id,
                verdict=SemanticVerdict.SUPPORTED,
                reason="模拟模式：通过程式硬规则",
                source="mock",
            )
    elif candidates:
        try:
            if client is None:
                from openai import OpenAI

                client = OpenAI(
                    api_key=api_key,
                    base_url=(getattr(config, "base_url", "") or None),
                    timeout=60.0,
                    max_retries=0,
                )
            completion = client.chat.completions.create(
                model=config.model_name,
                messages=[
                    {"role": "system", "content": SEMANTIC_REVIEW_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_semantic_review_user_message(
                            [claim.model_dump(mode="json") for claim in candidates],
                            total_comments=max(
                                1, analysis.dataset_summary.usable_comments or len(records)
                            ),
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=1200,
                extra_body={"thinking": {"type": "disabled"}},
            )
            usage = parse_usage(getattr(completion, "usage", None))
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            cache_hits = usage.prompt_cache_hit_tokens
            payload = _parse_review_payload(completion.choices[0].message.content or "")
            raw_reviews = payload.get("r") or []
            known = {claim.claim_id for claim in candidates}
            for raw in raw_reviews:
                if not isinstance(raw, dict):
                    continue
                claim_id = str(raw.get("i") or "")
                if claim_id not in known:
                    continue
                try:
                    verdict = SemanticVerdict(str(raw.get("v") or "insufficient"))
                except ValueError:
                    verdict = SemanticVerdict.INSUFFICIENT
                reviews[claim_id] = SemanticClaimReview(
                    claim_id=claim_id,
                    verdict=verdict,
                    reason=str(raw.get("x") or "")[:160],
                    source="semantic_agent",
                )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:300]

        # Missing or failed reviewer output is never treated as support.
        for claim in candidates:
            reviews.setdefault(
                claim.claim_id,
                SemanticClaimReview(
                    claim_id=claim.claim_id,
                    verdict=SemanticVerdict.INSUFFICIENT,
                    reason="语义审查失败或未覆盖此结论",
                    source="fallback",
                ),
            )

    removed = [
        claim.claim_id
        for claim in claims
        if claim.section != "hypothesis"
        and reviews.get(claim.claim_id, SemanticClaimReview(
            claim_id=claim.claim_id, verdict=SemanticVerdict.INSUFFICIENT
        )).verdict
        != SemanticVerdict.SUPPORTED
    ]
    downgraded = [
        claim.claim_id
        for claim in claims
        if claim.section == "hypothesis"
        and reviews.get(claim.claim_id, SemanticClaimReview(
            claim_id=claim.claim_id, verdict=SemanticVerdict.INSUFFICIENT
        )).verdict
        != SemanticVerdict.SUPPORTED
    ]
    pricing = resolve_pricing(config.base_url, config.model_name)
    cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
        prompt_cache_hit_tokens=cache_hits,
        input_price_cache_hit=float(pricing["input_price_cache_hit"]),
    )
    document = SemanticReviewDocument(
        passed=not error,
        claims=claims,
        reviews=list(reviews.values()),
        removed_claim_ids=removed,
        downgraded_claim_ids=downgraded,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_cache_hit_tokens=cache_hits,
        cost=cost,
        source_file=source_file,
        error=error,
    )
    return apply_semantic_reviews(analysis, document), document


def apply_semantic_reviews(
    analysis: ResearchAnalysis,
    document: SemanticReviewDocument,
) -> ResearchAnalysis:
    """Apply precision-first verdicts; rejected text never reaches the report."""
    payload = analysis.model_dump()
    verdicts = {review.claim_id: review.verdict for review in document.reviews}

    payload["themes"] = [
        theme
        for theme in payload.get("themes") or []
        if verdicts.get(f"theme:{theme.get('theme_id')}") == SemanticVerdict.SUPPORTED
    ]
    payload["unexpected_findings"] = [
        finding
        for index, finding in enumerate(payload.get("unexpected_findings") or [])
        if verdicts.get(f"finding:{index}") == SemanticVerdict.SUPPORTED
    ]
    for hypothesis in payload.get("hypothesis_assessment") or []:
        claim_id = f"hypothesis:{hypothesis.get('hypothesis_id')}"
        if verdicts.get(claim_id) != SemanticVerdict.SUPPORTED:
            hypothesis["conclusion"] = "insufficient"
            hypothesis["reasoning_summary"] = "现有引用不足以支持该判断。"
    payload["opportunity_hypotheses"] = [
        opportunity
        for index, opportunity in enumerate(payload.get("opportunity_hypotheses") or [])
        if verdicts.get(f"opportunity:{index}") == SemanticVerdict.SUPPORTED
    ]
    payload["research_conclusions"] = []
    payload["model_draft"] = {
        **(payload.get("model_draft") or {}),
        "semantic_review": {
            "removed_claim_ids": document.removed_claim_ids,
            "downgraded_claim_ids": document.downgraded_claim_ids,
        },
    }
    return ResearchAnalysis.model_validate(payload)


def review_open_themes(
    themes_doc: Any,
    records: Sequence[SourceRecord],
    *,
    config: Any,
    api_key: str,
    use_mock: bool,
    client: Any = None,
) -> tuple[Any, SemanticReviewDocument]:
    """Validate open-theme definitions and implications before export."""
    from .evidence_prompts import (
        SEMANTIC_REVIEW_SYSTEM_PROMPT,
        build_semantic_review_user_message,
    )
    from .llm_analyzer import estimate_cost, parse_usage
    from .pricing import resolve_pricing

    allowed = {record.internal_record_id for record in records}
    source_texts = {
        record.internal_record_id: "\n".join(
            value
            for value in (
                record.comment_text,
                record.parent_comment,
                record.creator_reply,
            )
            if value
        )
        for record in records
    }
    claims: List[SemanticClaim] = []
    for theme in themes_doc.themes:
        quotes = [
            quote
            for quote in theme.representative_quotes[:3]
            if quote and any(quote in source_texts.get(rid, "") for rid in theme.record_ids)
        ]
        if not quotes:
            for rid in theme.record_ids[:5]:
                text = source_texts.get(rid, "").strip()
                if text:
                    quotes.append(text[:80])
                    break
        claim = SemanticClaim(
            claim_id=f"open_theme:{theme.theme_id}",
            section="open_theme",
            text="；".join(
                value
                for value in (theme.theme_name, theme.definition, theme.implication)
                if value
            ),
            record_ids=[rid for rid in theme.record_ids if rid in allowed],
            evidence_quotes=quotes,
            record_count=theme.stats.comment_count,
        )
        claims.append(
            _hard_review_claim(
                claim,
                total_comments=max(1, len(records)),
                allowed_record_ids=allowed,
            )
        )

    reviews: Dict[str, SemanticClaimReview] = {}
    candidates: List[SemanticClaim] = []
    for claim in claims:
        if claim.hard_verdict in {
            SemanticVerdict.CONTRADICTED,
            SemanticVerdict.INSUFFICIENT,
        }:
            reviews[claim.claim_id] = SemanticClaimReview(
                claim_id=claim.claim_id,
                verdict=claim.hard_verdict,
                reason="；".join(claim.hard_reasons),
                source="hard_rule",
            )
        else:
            candidates.append(claim)

    prompt_tokens = completion_tokens = cache_hits = 0
    error = ""
    if use_mock:
        for claim in candidates:
            reviews[claim.claim_id] = SemanticClaimReview(
                claim_id=claim.claim_id,
                verdict=SemanticVerdict.SUPPORTED,
                reason="模拟模式：通过程式硬规则",
                source="mock",
            )
    elif candidates:
        try:
            if client is None:
                from openai import OpenAI

                client = OpenAI(
                    api_key=api_key,
                    base_url=(getattr(config, "base_url", "") or None),
                    timeout=60.0,
                    max_retries=0,
                )
            # Keep every theme reviewable without creating an unbounded prompt.
            # The old [:20] cap silently removed all later themes.
            for start in range(0, len(candidates), 20):
                batch = candidates[start : start + 20]
                completion = client.chat.completions.create(
                    model=config.model_name,
                    messages=[
                        {"role": "system", "content": SEMANTIC_REVIEW_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": build_semantic_review_user_message(
                                [claim.model_dump(mode="json") for claim in batch],
                                total_comments=max(1, len(records)),
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_tokens=1000,
                    extra_body={"thinking": {"type": "disabled"}},
                )
                usage = parse_usage(getattr(completion, "usage", None))
                prompt_tokens += usage.prompt_tokens
                completion_tokens += usage.completion_tokens
                cache_hits += usage.prompt_cache_hit_tokens
                payload = _parse_review_payload(completion.choices[0].message.content or "")
                known = {claim.claim_id for claim in batch}
                for raw in payload.get("r") or []:
                    if not isinstance(raw, dict) or str(raw.get("i") or "") not in known:
                        continue
                    claim_id = str(raw["i"])
                    try:
                        verdict = SemanticVerdict(str(raw.get("v") or "insufficient"))
                    except ValueError:
                        verdict = SemanticVerdict.INSUFFICIENT
                    reviews[claim_id] = SemanticClaimReview(
                        claim_id=claim_id,
                        verdict=verdict,
                        reason=str(raw.get("x") or "")[:160],
                        source="semantic_agent",
                    )
        except Exception as exc:  # noqa: BLE001
            error = str(exc)[:300]
        for claim in candidates:
            reviews.setdefault(
                claim.claim_id,
                SemanticClaimReview(
                    claim_id=claim.claim_id,
                    # A transport or coverage failure must not silently delete
                    # otherwise hard-rule-valid themes.
                    verdict=SemanticVerdict.SUPPORTED,
                    reason="语义审查未覆盖，保留并标记待复核",
                    source="fallback",
                ),
            )

    supported_ids = {
        review.claim_id
        for review in reviews.values()
        if review.verdict == SemanticVerdict.SUPPORTED
    }
    removed = [
        claim.claim_id for claim in claims if claim.claim_id not in supported_ids
    ]
    filtered = themes_doc.model_copy(deep=True)
    filtered.themes = [
        theme
        for theme in filtered.themes
        if f"open_theme:{theme.theme_id}" in supported_ids
    ]
    pricing = resolve_pricing(config.base_url, config.model_name)
    cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
        input_price=config.input_price,
        output_price=config.output_price,
        prompt_cache_hit_tokens=cache_hits,
        input_price_cache_hit=float(pricing["input_price_cache_hit"]),
    )
    filtered.prompt_tokens += prompt_tokens
    filtered.completion_tokens += completion_tokens
    filtered.prompt_cache_hit_tokens += cache_hits
    filtered.cost += cost
    document = SemanticReviewDocument(
        passed=not error,
        claims=claims,
        reviews=list(reviews.values()),
        removed_claim_ids=removed,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_cache_hit_tokens=cache_hits,
        cost=cost,
        error=error,
    )
    return filtered, document
