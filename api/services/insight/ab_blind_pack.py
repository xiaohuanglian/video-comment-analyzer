# -*- coding: utf-8 -*-
"""A/B blind-review sample selection (no human scores)."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .evidence_schemas import is_excluded_status, is_spam_validity

TARGET_TOTAL = 50
DEFAULT_SEED = 20260720


def select_blind_sample_ids(
    legacy_by_id: Dict[str, Dict[str, Any]],
    evidence_by_id: Dict[str, Dict[str, Any]],
    research: Optional[Dict[str, Any]] = None,
    *,
    seed: int = DEFAULT_SEED,
    target_total: int = TARGET_TOTAL,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Return sample descriptors [{record_id, sample_group}] and composition notes."""
    rng = random.Random(seed)
    research = research or {}
    common = sorted(set(legacy_by_id) & set(evidence_by_id))

    invalid_ids: List[str] = []
    other_ids: List[str] = []
    b_new_problem_ids: List[str] = []
    for rid in common:
        card = evidence_by_id[rid].get("card") or {}
        validity = card.get("validity")
        expr = card.get("primary_expression") or "other"
        a_analysis = (legacy_by_id[rid].get("analysis") or {})
        a_problems = a_analysis.get("specific_problems") or []
        b_problems = card.get("problem_or_need") or []
        if is_excluded_status(validity) or is_spam_validity(validity) or str(validity) in {
            "invalid",
            "spam_or_garbled",
            "spam",
            "garbled",
            "machine_generated",
            "off_topic",
        }:
            invalid_ids.append(rid)
        if expr == "other":
            other_ids.append(rid)
        if b_problems and not a_problems:
            b_new_problem_ids.append(rid)

    a_support = {"H1": set(), "H2": set(), "H3": set()}
    a_weaken = {"H1": set(), "H2": set(), "H3": set()}
    for rid in common:
        for rel in (legacy_by_id[rid].get("analysis") or {}).get("hypothesis_relations") or []:
            hid = rel.get("hypothesis_id")
            relation = rel.get("relation")
            if hid in a_support and relation == "supports":
                a_support[hid].add(rid)
            if hid in a_weaken and relation == "weakens":
                a_weaken[hid].add(rid)

    b_support: Dict[str, set] = {"H1": set(), "H2": set(), "H3": set()}
    b_weaken: Dict[str, set] = {"H1": set(), "H2": set(), "H3": set()}
    cited: set = set()
    for item in research.get("hypothesis_assessment") or []:
        hid = item.get("hypothesis_id")
        if hid not in b_support:
            continue
        for rid in item.get("supporting_record_ids") or []:
            if rid in common:
                b_support[hid].add(rid)
                cited.add(rid)
        for rid in item.get("weakening_record_ids") or []:
            if rid in common:
                b_weaken[hid].add(rid)
                cited.add(rid)
    for theme in research.get("themes") or []:
        for rid in theme.get("comment_record_ids") or []:
            if rid in common:
                cited.add(rid)

    hyp_conflict: List[str] = []
    for hid in ("H1", "H2", "H3"):
        for rid in b_support[hid] | b_weaken[hid] | a_support[hid] | a_weaken[hid]:
            a_s = rid in a_support[hid]
            a_w = rid in a_weaken[hid]
            b_s = rid in b_support[hid]
            b_w = rid in b_weaken[hid]
            if (a_s != b_s) or (a_w != b_w) or rid in cited:
                hyp_conflict.append(rid)
    hyp_conflict = sorted(set(hyp_conflict))

    selected: Dict[str, str] = {}
    notes: Dict[str, Any] = {
        "seed": seed,
        "pools": {
            "invalid": len(invalid_ids),
            "other": len(other_ids),
            "b_new_problem": len(b_new_problem_ids),
            "hypothesis_conflict": len(hyp_conflict),
        },
        "requested": {"invalid": 15, "other": 15, "b_new_problem": 10, "hypothesis_conflict": 10},
        "actual": {},
        "backfill": [],
    }

    def take(pool: Sequence[str], n: int, group: str, *, shuffle: bool = False) -> List[str]:
        candidates = [rid for rid in pool if rid not in selected]
        if shuffle:
            rng.shuffle(candidates)
        else:
            candidates = sorted(candidates)
        picked = candidates[:n]
        for rid in picked:
            selected[rid] = group
        return picked

    g_invalid = take(invalid_ids, 15, "invalid_all", shuffle=False)
    g_other = take(other_ids, 15, "other_random", shuffle=True)
    g_new = take(b_new_problem_ids, 10, "b_new_problem", shuffle=True)
    g_hyp = take(hyp_conflict, 10, "hypothesis_conflict", shuffle=True)

    notes["actual"] = {
        "invalid": len(g_invalid),
        "other": len(g_other),
        "b_new_problem": len(g_new),
        "hypothesis_conflict": len(g_hyp),
    }

    need = target_total - len(selected)
    if need > 0:
        remaining = [rid for rid in common if rid not in selected]
        rng.shuffle(remaining)
        for rid in remaining[:need]:
            selected[rid] = "backfill_adjacent"
            notes["backfill"].append(rid)
        notes["actual"]["backfill"] = len(notes["backfill"])

    samples = [{"record_id": rid, "sample_group": group} for rid, group in selected.items()]
    group_order = {
        "invalid_all": 0,
        "other_random": 1,
        "b_new_problem": 2,
        "hypothesis_conflict": 3,
        "backfill_adjacent": 4,
    }
    samples.sort(key=lambda x: (group_order.get(x["sample_group"], 9), x["record_id"]))
    notes["total"] = len(samples)
    return samples, notes
