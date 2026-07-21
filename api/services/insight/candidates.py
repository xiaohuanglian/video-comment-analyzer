# -*- coding: utf-8 -*-
"""Build user-level candidate list from analysis results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from .candidate_schemas import CandidateComment, CandidateRecord, CandidatesDocument
from .evidence_adapter import analysis_dict_from_result_row
from .field_mapping import resolve_source_links
from .research_matching import match_research_targets, research_relevance_score
from .score_breakdown import explain_candidate_score
from .statistics import candidate_priority, compute_candidate_score, contactability, user_key

PRODUCT_FIT_RANK = {"high": 3, "medium": 2, "low": 1, "unclear": 0}
TRAINING_RANK = {"continued": 3, "tried": 2, "planned": 1, "none": 0}


def _better_product_fit(current: str, new: str) -> str:
    return new if PRODUCT_FIT_RANK.get(new, 0) > PRODUCT_FIT_RANK.get(current, 0) else current


def _better_training(current: str, new: str) -> str:
    return new if TRAINING_RANK.get(new, 0) > TRAINING_RANK.get(current, 0) else current


def build_contact_reason(analysis: Dict[str, Any], score: int, *, research_matches: List[str] | None = None) -> str:
    parts: List[str] = []
    if research_matches:
        parts.append(f"符合调研对象：{'、'.join(research_matches)}")
    evidence = analysis.get("actual_training_evidence") or "none"
    if evidence in {"tried", "continued"}:
        parts.append("有真实训练证据")
    if analysis.get("help_seeking"):
        parts.append("主动求助")
    problems = analysis.get("specific_problems") or []
    if problems:
        parts.append(f"具体问题：{'；'.join(str(p) for p in problems[:2])}")
    relation = analysis.get("single_video_relation") or ""
    if relation in {"personalized_judgment_needed", "realtime_observation_needed"}:
        parts.append("单向视频可能不足")
    fit = analysis.get("product_fit") or ""
    if fit == "high":
        parts.append("产品适配度高")
    if score >= 7:
        parts.append("综合评分高")
    text = "；".join(parts) or "评论内容与居家训练反馈相关，值得进一步了解"
    forbidden = ("付费意愿", "强烈付费", "购买意向", "询价")
    if any(token in text for token in forbidden):
        text = "用户明确实际训练过，并提出了单向视频难以解决的具体动作问题"
    return text


def build_candidates(results: List[Dict[str, Any]], *, research_targets: List[str] | None = None) -> CandidatesDocument:
    groups: Dict[str, Dict[str, Any]] = {}

    for row in results:
        source = row.get("source") or {}
        analysis = analysis_dict_from_result_row(row)
        record_id = str(row.get("record_id") or analysis.get("record_id") or "")
        if not record_id:
            continue

        ukey = user_key(source) or f"record:{record_id}"
        homepage, comment_url = resolve_source_links(source)
        score = compute_candidate_score(analysis)
        contact_level = contactability(source)

        if ukey not in groups:
            groups[ukey] = {
                "user_key": ukey,
                "username": str(source.get("username") or source.get("user_id") or ""),
                "platform": str(source.get("platform") or ""),
                "creator_type": str(source.get("creator_type") or ""),
                "homepage_url": homepage,
                "comment_urls": [],
                "record_ids": [],
                "comments": [],
                "candidate_score": 0,
                "specific_problems": set(),
                "single_video_relations": set(),
                "product_fit": "unclear",
                "actual_training_evidence": "none",
                "help_seeking": False,
                "representative_quotes": [],
                "research_target_matches": set(),
                "research_relevance_score": 0,
                "contactability": contact_level,
                "best_row": row,
                "best_score": -1,
            }

        group = groups[ukey]
        group["candidate_score"] = max(group["candidate_score"], score)
        if score > group["best_score"]:
            group["best_score"] = score
            group["best_row"] = row
        if homepage and not group["homepage_url"]:
            group["homepage_url"] = homepage
        if not group["username"]:
            group["username"] = str(source.get("username") or source.get("user_id") or "")

        if comment_url and comment_url not in group["comment_urls"]:
            group["comment_urls"].append(comment_url)
        if record_id not in group["record_ids"]:
            group["record_ids"].append(record_id)

        comment_text = str(source.get("comment_text") or "")
        group["comments"].append(
            CandidateComment(
                record_id=record_id,
                comment_text=comment_text,
                video_title=str(source.get("video_title") or ""),
                creator_name=str(source.get("creator_name") or ""),
                comment_url=comment_url,
                analyzed_at=str(row.get("analyzed_at") or ""),
            )
        )

        for problem in analysis.get("specific_problems") or []:
            if problem:
                group["specific_problems"].add(str(problem))
        relation = analysis.get("single_video_relation") or ""
        if relation:
            group["single_video_relations"].add(str(relation))
        group["product_fit"] = _better_product_fit(group["product_fit"], str(analysis.get("product_fit") or "unclear"))
        group["actual_training_evidence"] = _better_training(
            group["actual_training_evidence"], str(analysis.get("actual_training_evidence") or "none")
        )
        group["help_seeking"] = group["help_seeking"] or bool(analysis.get("help_seeking"))

        quote = comment_text[:80].strip()
        if quote and quote not in group["representative_quotes"] and len(group["representative_quotes"]) < 5:
            group["representative_quotes"].append(quote)

        matches = match_research_targets(source, analysis, research_targets or [])
        for item in matches:
            group["research_target_matches"].add(item)
        group["research_relevance_score"] = max(
            group["research_relevance_score"],
            research_relevance_score(matches, analysis),
        )

        # Best contactability wins
        rank = {"high": 3, "medium": 2, "low": 1}
        if rank.get(contact_level, 0) > rank.get(group["contactability"], 0):
            group["contactability"] = contact_level

    candidates: List[CandidateRecord] = []
    for group in groups.values():
        best_row = group.get("best_row") or {}
        best_analysis = analysis_dict_from_result_row(best_row) if best_row else {}
        score = group["candidate_score"]
        breakdown = [item["label"] for item in explain_candidate_score(best_analysis)]
        research_matches = sorted(group["research_target_matches"])
        if any(best_analysis.get("action_gap") or []):
            breakdown.append("行动差距信号")
        if best_analysis.get("paid_help"):
            breakdown.append("付费求助信号")
        candidates.append(
            CandidateRecord(
                user_key=group["user_key"],
                username=group["username"],
                platform=group["platform"],
                creator_type=group["creator_type"],
                homepage_url=group["homepage_url"],
                comment_urls=group["comment_urls"],
                record_ids=group["record_ids"],
                comments=group["comments"],
                candidate_score=score,
                priority=candidate_priority(score),
                contactability=group["contactability"],
                specific_problems=sorted(group["specific_problems"]),
                single_video_relations=sorted(group["single_video_relations"]),
                product_fit=group["product_fit"],
                actual_training_evidence=group["actual_training_evidence"],
                help_seeking=group["help_seeking"],
                representative_quotes=group["representative_quotes"],
                contact_reason=build_contact_reason(best_analysis, score, research_matches=research_matches),
                score_breakdown=breakdown,
                research_target_matches=research_matches,
                research_relevance_score=group["research_relevance_score"],
            )
        )

    if research_targets:
        candidates.sort(
            key=lambda c: (-c.research_relevance_score, -c.candidate_score, -len(c.record_ids), c.username)
        )
    else:
        candidates.sort(key=lambda c: (-c.candidate_score, -len(c.record_ids), c.username))
    return CandidatesDocument(
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_candidates=len(candidates),
        candidates=candidates,
    )


def merge_candidate_updates(
    doc: CandidatesDocument,
    *,
    user_key: str,
    contact_status: Optional[str] = None,
    product_manager_note: Optional[str] = None,
) -> Optional[CandidateRecord]:
    for candidate in doc.candidates:
        if candidate.user_key != user_key:
            continue
        if contact_status is not None:
            candidate.contact_status = contact_status  # type: ignore[assignment]
        if product_manager_note is not None:
            candidate.product_manager_note = product_manager_note
        return candidate
    return None
