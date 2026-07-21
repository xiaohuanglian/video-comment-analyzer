# -*- coding: utf-8 -*-
"""Dataset-level research agent — semantic induction; counts from code."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from pydantic import ValidationError

from .evidence_prompts import RESEARCH_SYSTEM_PROMPT, build_research_user_message
from .evidence_schemas import (
    DatasetSummaryCounts,
    EvidenceLevel,
    EvidenceRef,
    HypothesisAssessment,
    HypothesisConclusion,
    HypothesisEvidenceRef,
    OpportunityHypothesis,
    RecordStatus,
    ResearchAnalysis,
    ResearchTheme,
    UnexpectedFinding,
    is_participating_status,
    is_excluded_status,
    normalize_evidence_level,
    normalize_record_status,
)
from .evidence_adapter import assign_evidence_item_ids
from .evidence_schemas import EvidenceCard
from .llm_analyzer import LlmUsage, build_openai_client, parse_usage
from .schemas import RunConfig, SourceRecord
from .user_identity import user_key


def _index_evidence_items(card_rows: Sequence[dict]) -> Dict[str, dict]:
    """Map evidence_item_id -> item dict (+ record_id)."""
    index: Dict[str, dict] = {}
    for row in card_rows:
        card_raw = row.get("card") or row
        try:
            card = EvidenceCard.model_validate(card_raw)
        except Exception:
            continue
        card = assign_evidence_item_ids(card)
        for item in card.evidence_items or []:
            eid = (item.evidence_item_id or "").strip()
            if not eid:
                continue
            index[eid] = {
                "record_id": card.record_id,
                "evidence_item_id": eid,
                "text": item.text,
                "evidence_quote": item.evidence_quote,
                "speaker_scope": item.speaker_scope.value,
                "certainty": item.certainty.value,
                "type": item.type.value,
                "subtype": item.subtype,
            }
    return index


def _parse_evidence_refs(
    raw_list: Any,
    *,
    known_record_ids: Set[str],
    item_index: Dict[str, dict],
) -> tuple[List[EvidenceRef], List[dict]]:
    ok: List[EvidenceRef] = []
    dropped: List[dict] = []
    for raw in raw_list or []:
        if isinstance(raw, str):
            # legacy: bare quote or record id — drop for report quotes
            dropped.append({"raw": raw, "reason": "string_ref_not_allowed"})
            continue
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("record_id") or "").strip()
        eid = str(raw.get("evidence_item_id") or "").strip()
        if not rid or rid not in known_record_ids:
            dropped.append({**raw, "reason": "unknown_record_id"})
            continue
        if not eid or eid not in item_index:
            dropped.append({**raw, "reason": "unknown_evidence_item_id"})
            continue
        if item_index[eid].get("record_id") != rid:
            dropped.append({**raw, "reason": "record_id_mismatch"})
            continue
        ok.append(EvidenceRef(record_id=rid, evidence_item_id=eid))
    return ok, dropped


def _parse_hyp_refs(
    raw_list: Any,
    *,
    known_record_ids: Set[str],
    item_index: Dict[str, dict],
) -> tuple[List[HypothesisEvidenceRef], List[dict]]:
    ok: List[HypothesisEvidenceRef] = []
    dropped: List[dict] = []
    for raw in raw_list or []:
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("record_id") or "").strip()
        eid = str(raw.get("evidence_item_id") or "").strip()
        if not rid or rid not in known_record_ids:
            dropped.append({**raw, "reason": "unknown_record_id"})
            continue
        if eid and eid not in item_index:
            dropped.append({**raw, "reason": "unknown_evidence_item_id"})
            continue
        strength_raw = str(raw.get("strength") or "weak_context")
        try:
            from .evidence_schemas import EvidenceStrength

            strength = EvidenceStrength(strength_raw)
        except ValueError:
            from .evidence_schemas import EvidenceStrength

            strength = EvidenceStrength.WEAK_CONTEXT
        ok.append(
            HypothesisEvidenceRef(
                record_id=rid,
                evidence_item_id=eid,
                strength=strength,
                note=str(raw.get("note") or "")[:200],
            )
        )
    return ok, dropped


def compute_dataset_summary(
    records: Sequence[SourceRecord],
    cards: Sequence[dict],
    *,
    themed_record_ids: Optional[Set[str]] = None,
) -> DatasetSummaryCounts:
    """Code-owned counts — never trust model numbers."""
    card_by_id = {}
    for row in cards:
        rid = row.get("record_id") or (row.get("card") or {}).get("record_id")
        card = row.get("card") or row
        if rid:
            card_by_id[rid] = card

    users: Set[str] = set()
    files: Set[str] = set()
    videos: Set[str] = set()
    creators: Set[str] = set()
    usable = 0
    unclear = 0
    off_topic = 0
    machine_generated = 0
    spam = 0
    garbled = 0
    strong = medium = weak = none = 0
    problem_n = behavior_n = gap_n = 0
    for record in records:
        rid = record.internal_record_id
        uk = user_key(
            {
                "user_id": record.user_id,
                "username": record.username,
                "user_homepage_url": record.user_homepage_url,
            }
        )
        if uk:
            users.add(uk)
        if record.source_file:
            files.add(record.source_file)
        if record.video_title or record.video_url:
            videos.add(record.video_title or record.video_url)
        if record.creator_name:
            creators.add(record.creator_name)
        card = card_by_id.get(rid) or {}
        status_raw = card.get("record_status") or card.get("validity") or RecordStatus.USABLE.value
        status = normalize_record_status(status_raw)
        level = normalize_evidence_level(card.get("evidence_level") or card.get("validity") or EvidenceLevel.WEAK.value)
        items = card.get("evidence_items") or []
        types = {str((it or {}).get("type") or "") for it in items if isinstance(it, dict)}
        if not types:
            # legacy arrays
            if card.get("problem_or_need"):
                types.add("problem")
            if card.get("training_behavior") or card.get("actual_behavior"):
                types.add("behavior")
            if card.get("action_gap"):
                types.add("action_gap")
        if "problem" in types:
            problem_n += 1
        if "behavior" in types:
            behavior_n += 1
        if "action_gap" in types:
            gap_n += 1
        if status == RecordStatus.SPAM:
            spam += 1
        elif status == RecordStatus.GARBLED:
            garbled += 1
        elif status == RecordStatus.MACHINE_GENERATED:
            machine_generated += 1
        elif status == RecordStatus.OFF_TOPIC:
            off_topic += 1
        elif status == RecordStatus.UNCLEAR:
            unclear += 1
        else:
            usable += 1
        if level == EvidenceLevel.STRONG:
            strong += 1
        elif level == EvidenceLevel.MEDIUM:
            medium += 1
        elif level == EvidenceLevel.WEAK:
            weak += 1
        else:
            none += 1

    participating = usable + unclear
    themed = set(themed_record_ids or set())
    theme_covered = len(
        [
            rid
            for rid in themed
            if rid in card_by_id
            and is_participating_status(
                (card_by_id[rid] or {}).get("record_status") or (card_by_id[rid] or {}).get("validity")
            )
        ]
    )
    rate = round(theme_covered / participating, 4) if participating else 0.0
    themed_usable = len(
        [
            rid
            for rid in themed
            if normalize_record_status((card_by_id.get(rid) or {}).get("record_status") or (card_by_id.get(rid) or {}).get("validity"))
            == RecordStatus.USABLE
        ]
    )
    unthemed_usable = max(0, usable - themed_usable)

    return DatasetSummaryCounts(
        total_comments=len(records),
        usable_comments=usable,
        unclear_comments=unclear,
        off_topic_comments=off_topic,
        machine_generated_comments=machine_generated,
        spam_comments=spam,
        garbled_comments=garbled,
        strong_evidence_comments=strong,
        medium_evidence_comments=medium,
        weak_evidence_comments=weak,
        none_evidence_comments=none,
        problem_comments=problem_n,
        behavior_comments=behavior_n,
        action_gap_comments=gap_n,
        valid_comments=participating,
        meaningful_comments=strong + medium,
        low_information_comments=weak,
        unique_users=len(users),
        source_files=len(files),
        videos=len(videos),
        creators=len(creators),
        theme_covered_comments=theme_covered,
        theme_coverage_rate=rate,
        unthemed_usable_comments=unthemed_usable,
        unthemed_meaningful_comments=unthemed_usable,
    )


def _filter_ids(ids: Iterable[str], known: Set[str], *, ordered_ids: Optional[List[str]] = None) -> List[str]:
    """Keep known record_ids; map numeric indices back to ordered_ids when the model returns positions."""
    resolved: List[str] = []
    seen: Set[str] = set()
    ordered = ordered_ids or []
    for raw in ids:
        rid = str(raw).strip()
        if not rid:
            continue
        if rid in known:
            chosen = rid
        elif rid.isdigit() and ordered:
            idx = int(rid)
            chosen = ""
            for candidate in (idx, idx - 1):  # tolerate 0-based or 1-based
                if 0 <= candidate < len(ordered) and ordered[candidate] in known:
                    chosen = ordered[candidate]
                    break
            if not chosen:
                continue
        else:
            continue
        if chosen not in seen:
            seen.add(chosen)
            resolved.append(chosen)
    return resolved


def recount_research_analysis(
    draft: dict,
    *,
    known_ids: Set[str],
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
) -> ResearchAnalysis:
    """Apply model draft then overwrite all counts via code."""
    known = set(known_ids)
    ordered_ids = [r.internal_record_id for r in records if r.internal_record_id in known]
    # Prefer card row order when present (matches prompt summary order)
    card_order: List[str] = []
    for row in card_rows:
        rid = row.get("record_id") or (row.get("card") or {}).get("record_id")
        if rid and rid in known and rid not in card_order:
            card_order.append(rid)
    if card_order:
        ordered_ids = card_order

    record_by_id = {r.internal_record_id: r for r in records}
    item_index = _index_evidence_items(card_rows)
    dropped_refs: List[dict] = []

    themes: List[ResearchTheme] = []
    for raw in draft.get("themes") or []:
        if not isinstance(raw, dict):
            continue
        ids = _filter_ids(raw.get("comment_record_ids") or [], known, ordered_ids=ordered_ids)
        users: Set[str] = set()
        sources: Set[str] = set()
        for rid in ids:
            rec = record_by_id.get(rid)
            if not rec:
                continue
            uk = user_key(
                {
                    "user_id": rec.user_id,
                    "username": rec.username,
                    "user_homepage_url": rec.user_homepage_url,
                }
            )
            if uk:
                users.add(uk)
            if rec.source_file:
                sources.add(rec.source_file)
        refs, drop = _parse_evidence_refs(
            raw.get("representative_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        dropped_refs.extend(drop)
        # Ignore any model-supplied representative_quotes (must be code-backfilled)
        themes.append(
            ResearchTheme(
                theme_id=str(raw.get("theme_id") or f"T{len(themes)+1}"),
                theme_name=str(raw.get("theme_name") or ""),
                theme_definition=str(raw.get("theme_definition") or ""),
                comment_record_ids=ids,
                comment_count=len(ids),
                unique_user_count=len(users),
                source_count=len(sources),
                representative_evidence_refs=refs[:5],
                representative_quotes=[],
                current_solutions=list(raw.get("current_solutions") or [])[:5],
                impact_or_cost=list(raw.get("impact_or_cost") or [])[:5],
                counter_evidence=list(raw.get("counter_evidence") or [])[:5],
                confidence=float(raw.get("confidence") or 0.0),
            )
        )

    assessments: List[HypothesisAssessment] = []
    for raw in draft.get("hypothesis_assessment") or []:
        if not isinstance(raw, dict):
            continue
        hid = str(raw.get("hypothesis_id") or "")
        if hid not in {"H1", "H2", "H3"}:
            continue
        support = _filter_ids(raw.get("supporting_record_ids") or [], known, ordered_ids=ordered_ids)
        weaken = _filter_ids(raw.get("weakening_record_ids") or [], known, ordered_ids=ordered_ids)
        conclusion_raw = str(raw.get("conclusion") or "insufficient")
        try:
            conclusion = HypothesisConclusion(conclusion_raw)
        except ValueError:
            conclusion = HypothesisConclusion.INSUFFICIENT
        if conclusion == HypothesisConclusion.SUPPORTED and not support:
            conclusion = HypothesisConclusion.INSUFFICIENT
        s_refs, d1 = _parse_hyp_refs(
            raw.get("supporting_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        w_refs, d2 = _parse_hyp_refs(
            raw.get("weakening_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        dropped_refs.extend(d1)
        dropped_refs.extend(d2)
        assessments.append(
            HypothesisAssessment(
                hypothesis_id=hid,
                conclusion=conclusion,
                supporting_record_ids=support,
                weakening_record_ids=weaken,
                supporting_evidence_refs=s_refs,
                weakening_evidence_refs=w_refs,
                reasoning_summary=str(raw.get("reasoning_summary") or ""),
                unknowns=list(raw.get("unknowns") or []),
            )
        )
    for hid in ("H1", "H2", "H3"):
        if not any(a.hypothesis_id == hid for a in assessments):
            assessments.append(
                HypothesisAssessment(hypothesis_id=hid, conclusion=HypothesisConclusion.INSUFFICIENT)
            )

    findings: List[UnexpectedFinding] = []
    for raw in draft.get("unexpected_findings") or []:
        if not isinstance(raw, dict) or not raw.get("finding"):
            continue
        f_refs, d = _parse_evidence_refs(
            raw.get("supporting_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        dropped_refs.extend(d)
        rids = _filter_ids(raw.get("record_ids") or [], known, ordered_ids=ordered_ids)
        if not rids:
            rids = [ref.record_id for ref in f_refs]
        findings.append(
            UnexpectedFinding(
                finding=str(raw["finding"]),
                record_ids=rids,
                supporting_evidence_refs=f_refs[:5],
                why_it_matters=str(raw.get("why_it_matters") or ""),
                conclusion=str(raw.get("conclusion") or ""),
                limitations=str(raw.get("limitations") or ""),
                next_step=str(raw.get("next_step") or ""),
            )
        )

    opportunities: List[OpportunityHypothesis] = []
    for raw in draft.get("opportunity_hypotheses") or []:
        if not isinstance(raw, dict) or not raw.get("opportunity_name"):
            continue
        s_refs, d1 = _parse_evidence_refs(
            raw.get("supporting_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        c_refs, d2 = _parse_evidence_refs(
            raw.get("counter_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        b_refs, d3 = _parse_evidence_refs(
            raw.get("behavior_evidence_refs") or [],
            known_record_ids=known,
            item_index=item_index,
        )
        dropped_refs.extend(d1 + d2 + d3)
        opportunities.append(
            OpportunityHypothesis(
                opportunity_name=str(raw["opportunity_name"]),
                supporting_evidence=list(raw.get("supporting_evidence") or [])[:5],
                supporting_evidence_refs=s_refs[:5],
                counter_evidence=list(raw.get("counter_evidence") or [])[:5],
                counter_evidence_refs=c_refs[:5],
                possible_product_form=list(raw.get("possible_product_form") or []),
                possible_content_form=list(raw.get("possible_content_form") or []),
                current_unknowns=list(raw.get("current_unknowns") or []),
                recommended_validation=list(raw.get("recommended_validation") or []),
                supporting_record_ids=_filter_ids(
                    raw.get("supporting_record_ids") or [], known, ordered_ids=ordered_ids
                ),
                target_users=str(raw.get("target_users") or ""),
                concrete_problem=str(raw.get("concrete_problem") or ""),
                current_alternatives=list(raw.get("current_alternatives") or [])[:5],
                behavior_evidence_refs=b_refs[:5],
            )
        )

    summary = compute_dataset_summary(records, list(card_rows))
    themed_ids: Set[str] = set()
    for theme in themes:
        themed_ids.update(theme.comment_record_ids)
    summary = compute_dataset_summary(records, list(card_rows), themed_record_ids=themed_ids)
    draft_out = dict(draft) if isinstance(draft, dict) else {}
    if dropped_refs:
        draft_out["dropped_evidence_refs"] = dropped_refs[:50]
    return ResearchAnalysis(
        dataset_summary=summary,
        themes=themes,
        hypothesis_assessment=assessments,
        unexpected_findings=findings,
        opportunity_hypotheses=opportunities,
        research_conclusions=[str(x) for x in (draft.get("research_conclusions") or []) if x],
        recommended_interviews=[str(x) for x in (draft.get("recommended_interviews") or []) if x],
        recommended_experiments=[str(x) for x in (draft.get("recommended_experiments") or []) if x],
        model_draft=draft_out,
    )


def _card_summary_for_prompt(card_rows: Sequence[dict], *, limit: int = 120) -> List[dict]:
    from .evidence_adapter import card_to_research_summary

    summaries: List[dict] = []
    for row in card_rows[:limit]:
        card = row.get("card") or row
        try:
            summary = card_to_research_summary(card)
        except Exception:
            summary = {
                "record_id": row.get("record_id") or card.get("record_id"),
                "record_status": card.get("record_status") or card.get("validity"),
                "evidence_items": card.get("evidence_items") or [],
            }
        source = row.get("source") or {}
        # Prefer evidence quotes; do not resend full raw comments by default
        summary["video_title"] = (source.get("video_title") or "")[:40]
        summaries.append(summary)
    return summaries


def _first_item_refs(card_rows: Sequence[dict], record_ids: Sequence[str], *, limit: int = 5) -> List[dict]:
    """Build {record_id, evidence_item_id} refs from cards — never invent quote text."""
    want = list(record_ids)
    by_rid = {
        (row.get("record_id") or (row.get("card") or {}).get("record_id")): row for row in card_rows
    }
    refs: List[dict] = []
    for rid in want:
        row = by_rid.get(rid)
        if not row:
            continue
        try:
            card = assign_evidence_item_ids(EvidenceCard.model_validate(row.get("card") or row))
        except Exception:
            continue
        if not card.evidence_items:
            continue
        item = card.evidence_items[0]
        refs.append({"record_id": rid, "evidence_item_id": item.evidence_item_id})
        if len(refs) >= limit:
            break
    return refs


def research_analysis_mock(
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
) -> ResearchAnalysis:
    """Deterministic mock research for tests — no paid API; quotes via ID refs only."""
    known = {r.internal_record_id for r in records}
    by_expr: Dict[str, List[str]] = defaultdict(list)
    problem_ids: List[str] = []
    help_ids: List[str] = []
    for row in card_rows:
        card = row.get("card") or row
        rid = row.get("record_id") or card.get("record_id")
        if not rid or rid not in known:
            continue
        expr = card.get("primary_expression") or "other"
        by_expr[expr].append(rid)
        if card.get("problem_or_need") or any(
            (it or {}).get("type") == "problem" for it in (card.get("evidence_items") or []) if isinstance(it, dict)
        ):
            problem_ids.append(rid)
        if expr in {"help_request", "question"}:
            help_ids.append(rid)

    theme_ids = problem_ids[:30] or list(known)[:5]
    draft = {
        "themes": [
            {
                "theme_id": "T1",
                "theme_name": "训练疑问与求助",
                "theme_definition": "用户提出动作/安排相关问题或求助",
                "comment_record_ids": theme_ids,
                "representative_evidence_refs": _first_item_refs(card_rows, theme_ids, limit=3),
                "representative_quotes": [],
                "current_solutions": [],
                "impact_or_cost": [],
                "counter_evidence": [],
                "confidence": 0.7,
            }
        ],
        "hypothesis_assessment": [
            {
                "hypothesis_id": "H1",
                "conclusion": "mixed" if problem_ids else "insufficient",
                "supporting_record_ids": problem_ids[:10],
                "supporting_evidence_refs": [
                    {**ref, "strength": "direct"} for ref in _first_item_refs(card_rows, problem_ids, limit=5)
                ],
                "weakening_record_ids": by_expr.get("gratitude", [])[:5],
                "reasoning_summary": "有问题反馈支持过程需求；纯感谢较弱。",
                "unknowns": ["是否具备持续训练动力仍需访谈"],
            },
            {
                "hypothesis_id": "H2",
                "conclusion": "mixed" if help_ids else "insufficient",
                "supporting_record_ids": help_ids[:10],
                "supporting_evidence_refs": [
                    {**ref, "strength": "behavioral"} for ref in _first_item_refs(card_rows, help_ids, limit=5)
                ],
                "weakening_record_ids": by_expr.get("check_in", [])[:5],
                "reasoning_summary": "求助类评论可能支持实时反馈需求。",
                "unknowns": [],
            },
            {
                "hypothesis_id": "H3",
                "conclusion": "insufficient",
                "supporting_record_ids": [],
                "weakening_record_ids": [],
                "reasoning_summary": "证据不足以判断 Agent 规划需求。",
                "unknowns": ["是否希望代为安排计划"],
            },
        ],
        "unexpected_findings": (
            [
                {
                    "finding": "存在主动求助信号",
                    "record_ids": help_ids[:5],
                    "supporting_evidence_refs": _first_item_refs(card_rows, help_ids, limit=3),
                    "why_it_matters": "可能适合访谈招募",
                    "conclusion": "存在主动求助信号",
                    "limitations": "样本量有限",
                    "next_step": "抽样访谈",
                }
            ]
            if help_ids
            else []
        ),
        "opportunity_hypotheses": [
            {
                "opportunity_name": "动作疑问即时答疑",
                "supporting_evidence": ["多条提问/求助证据卡"],
                "supporting_evidence_refs": _first_item_refs(
                    card_rows, help_ids[:8] or problem_ids[:5], limit=5
                ),
                "counter_evidence": ["部分打卡评论无问题"],
                "possible_product_form": ["跟练纠错助手"],
                "possible_content_form": ["高频疑问短视频"],
                "current_unknowns": ["付费意愿未知"],
                "recommended_validation": ["对求助用户做 10 人访谈"],
                "supporting_record_ids": help_ids[:8] or problem_ids[:5],
                "target_users": "有明确动作疑问或求助的训练者",
                "concrete_problem": "跟练时不知动作是否正确",
                "current_alternatives": ["反复看视频", "问教练"],
                "behavior_evidence_refs": _first_item_refs(card_rows, help_ids[:5], limit=3),
            }
        ],
        "research_conclusions": [
            "最主要问题：训练过程疑问与求助较常见。",
            "最重要行为信号：提问/求助相对打卡更多指向可访谈用户。",
            "最值得先验证：动作疑问即时答疑类原型。",
            "当前证据不能证明：付费意愿或产品必然成立。",
        ],
        "recommended_interviews": ["访谈有明确问题或求助的用户"],
        "recommended_experiments": ["用纠错助手原型验证 H2"],
    }
    return recount_research_analysis(draft, known_ids=known, records=records, card_rows=card_rows)


def run_research_analysis(
    records: Sequence[SourceRecord],
    card_rows: Sequence[dict],
    *,
    use_mock: bool = True,
    config: Optional[RunConfig] = None,
    api_key: str = "",
    client=None,
) -> tuple[ResearchAnalysis, LlmUsage]:
    known_ids = [r.internal_record_id for r in records]
    known_set = set(known_ids)
    if use_mock or not api_key:
        return research_analysis_mock(records, card_rows), LlmUsage()

    assert config is not None
    llm = client or build_openai_client(config.base_url, api_key)
    summaries = _card_summary_for_prompt(card_rows)
    code_summary = compute_dataset_summary(records, list(card_rows)).model_dump()
    messages = [
        {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_research_user_message(
                card_summaries=summaries,
                known_record_ids=known_ids,
                dataset_summary=code_summary,
                project_context=(
                    getattr(config, "project_context", "")
                    or getattr(config, "project_context_compact", "")
                    or ""
                ),
            ),
        },
    ]
    completion = llm.chat.completions.create(
        model=config.model_name,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    usage = parse_usage(getattr(completion, "usage", None))
    raw = completion.choices[0].message.content or ""
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"研究分析 JSON 无法解析: {exc}") from exc
    if not isinstance(draft, dict):
        raise ValueError("研究分析输出必须是 JSON 对象")
    analysis = recount_research_analysis(
        draft, known_ids=known_set, records=records, card_rows=card_rows
    )
    return analysis, usage
