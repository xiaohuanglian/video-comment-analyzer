# -*- coding: utf-8 -*-
"""Evaluate high-risk 30-sample gates for evidence_items_v1."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from api.services.insight.evidence_extractor import evidence_item_count
from api.services.insight.evidence_schemas import (
    EvidenceCard,
    EvidenceItemType,
    is_meaningful_level,
)
from api.services.insight.schemas import SourceRecord
from api.services.insight.storage import load_evidence_cards
from api.services.insight.validation import quote_exists, source_text_pool

STATUS_MARKERS = {
    "machine_generated": ("AI视频", "本内容由AI"),
    "off_topic": ("啤酒鸭", "纹身", "门什么时候"),
}

PERSONAL_BEHAVIOR_MARKERS = (
    "刚刚试",
    "试了试",
    "做完",
    "办卡",
    "零基础，直接",
    "明天继续",
    "会做几个",
    "1分钟后",
    "从初中开始练",
    "一组最次",
)


def _all_quotes_ok(card: EvidenceCard, record: SourceRecord) -> bool:
    pool = source_text_pool(record)
    items = card.evidence_items or []
    if items:
        for item in items:
            q = (item.evidence_quote or "").strip()
            if not q or not quote_exists(q, pool):
                return False
        return True
    # legacy fallback
    for arr in (
        card.explicit_facts,
        card.problem_or_need,
        card.training_behavior,
        card.content_engagement,
        card.action_gap,
        card.current_solution,
        card.impact_or_cost,
        card.user_context,
        card.quantitative_evidence,
    ):
        for item in arr or []:
            q = (getattr(item, "evidence_quote", "") or "").strip()
            if not q or not quote_exists(q, pool):
                return False
    return True


def _has_type(card: EvidenceCard, etype: EvidenceItemType) -> bool:
    return any(i.type == etype for i in (card.evidence_items or []))


def _has_behavior(card: EvidenceCard) -> bool:
    if _has_type(card, EvidenceItemType.BEHAVIOR) or card.training_behavior:
        return True
    return False


def _has_gap(card: EvidenceCard) -> bool:
    return _has_type(card, EvidenceItemType.ACTION_GAP) or bool(card.action_gap)


def _has_paid(card: EvidenceCard) -> bool:
    return any(
        i.type == EvidenceItemType.BEHAVIOR and i.subtype == "sought_paid_help"
        for i in (card.evidence_items or [])
    ) or any(getattr(t, "type", None) and t.type.value == "sought_paid_help" for t in (card.training_behavior or []))


def _has_quant(card: EvidenceCard) -> bool:
    return _has_type(card, EvidenceItemType.QUANTITATIVE) or bool(card.quantitative_evidence)


def evaluate(run_id: str, sample_path: Path) -> dict:
    samples = json.loads(sample_path.read_text(encoding="utf-8"))
    bucket_by_id = {s["record_id"]: s.get("bucket") for s in samples}
    rows = load_evidence_cards(run_id)
    by_id = {r.get("record_id"): r for r in rows}

    meaningful_empty = 0
    quote_ok = quote_total = 0
    status_counts: Counter = Counter()
    level_counts: Counter = Counter()

    behavior_expected: list[str] = []
    behavior_hit = 0
    gap_expected: list[str] = []
    gap_hit = 0
    paid_expected: list[str] = []
    paid_hit = 0
    quant_expected: list[str] = []
    quant_hit = 0
    status_expected: list[str] = []
    status_hit = 0
    details = []

    for rid, bucket in bucket_by_id.items():
        row = by_id.get(rid)
        if not row:
            details.append({"record_id": rid, "error": "missing"})
            continue
        card = EvidenceCard.model_validate(row.get("card") or {})
        src = row.get("source") or {}
        record = SourceRecord.model_validate(
            {
                **src,
                "internal_record_id": rid,
                "source_file": src.get("source_file") or "x",
                "source_row_number": src.get("source_row_number") or 0,
                "comment_text": src.get("comment_text") or "",
            }
        )
        text = record.comment_text or ""
        count = evidence_item_count(card)
        status_counts[card.record_status.value] += 1
        level_counts[card.evidence_level.value] += 1

        if is_meaningful_level(card.evidence_level) and count == 0:
            meaningful_empty += 1

        quote_total += 1
        if _all_quotes_ok(card, record):
            quote_ok += 1

        if bucket == "behavior" or any(m in text for m in PERSONAL_BEHAVIOR_MARKERS):
            if any(m in text for m in PERSONAL_BEHAVIOR_MARKERS) or bucket == "behavior":
                # stricter: only personal markers for recall denominator when present
                if any(m in text for m in PERSONAL_BEHAVIOR_MARKERS) and card.record_status.value == "usable":
                    behavior_expected.append(rid)
                    if _has_behavior(card):
                        behavior_hit += 1

        if bucket == "action_gap":
            gap_expected.append(rid)
            if _has_gap(card):
                gap_hit += 1

        if card.record_status.value == "usable" and ("办卡" in text or ("健身房" in text and "办" in text)):
            paid_expected.append(rid)
            if _has_paid(card):
                paid_hit += 1

        if card.record_status.value == "usable" and (
            bucket == "long_quant" or (len(text) >= 60 and re.search(r"\d", text) and "AI视频" not in text)
        ):
            if bucket == "long_quant" or re.search(r"\d+\s*(个|次|秒|组|分钟|月)", text):
                quant_expected.append(rid)
                if _has_quant(card):
                    quant_hit += 1

        if bucket == "status_class":
            status_expected.append(rid)
            expected = None
            if any(m in text for m in STATUS_MARKERS["machine_generated"]):
                expected = "machine_generated"
            elif any(m in text for m in STATUS_MARKERS["off_topic"]):
                expected = "off_topic"
            if expected and card.record_status.value == expected:
                status_hit += 1
            elif expected is None and card.record_status.value in {
                "off_topic",
                "machine_generated",
                "spam",
                "garbled",
            }:
                status_hit += 1

        details.append(
            {
                "record_id": rid,
                "bucket": bucket,
                "record_status": card.record_status.value,
                "evidence_level": card.evidence_level.value,
                "evidence_item_count": count,
                "types": [i.type.value for i in (card.evidence_items or [])],
                "subtypes": [i.subtype for i in (card.evidence_items or []) if i.subtype],
            }
        )

    def rate(hit: int, exp: list) -> float | None:
        return round(hit / len(exp), 4) if exp else None

    gates = {
        "meaningful_empty": meaningful_empty,
        "meaningful_empty_pass": meaningful_empty == 0,
        "quote_completeness": round(quote_ok / quote_total, 4) if quote_total else 0,
        "quote_completeness_pass": quote_total > 0 and quote_ok == quote_total,
        "behavior_recall": rate(behavior_hit, behavior_expected),
        "behavior_recall_pass": (behavior_hit / len(behavior_expected) >= 0.85) if behavior_expected else None,
        "action_gap_recall": rate(gap_hit, gap_expected),
        "action_gap_pass": (gap_hit / len(gap_expected) >= 0.85) if gap_expected else None,
        "paid_help_recall": rate(paid_hit, paid_expected),
        "paid_help_pass": (paid_hit / len(paid_expected) >= 0.9) if paid_expected else None,
        "quant_recall": rate(quant_hit, quant_expected),
        "quant_pass": (quant_hit / len(quant_expected) >= 0.85) if quant_expected else None,
        "status_class_accuracy": rate(status_hit, status_expected),
        "status_class_pass": (status_hit / len(status_expected) >= 0.9) if status_expected else None,
    }
    return {
        "run_id": run_id,
        "n": len(bucket_by_id),
        "status_counts": dict(status_counts),
        "level_counts": dict(level_counts),
        "gates": gates,
        "behavior_expected_n": len(behavior_expected),
        "behavior_hit": behavior_hit,
        "gap_expected_n": len(gap_expected),
        "gap_hit": gap_hit,
        "paid_expected_n": len(paid_expected),
        "paid_hit": paid_hit,
        "quant_expected_n": len(quant_expected),
        "quant_hit": quant_hit,
        "status_expected_n": len(status_expected),
        "status_hit": status_hit,
        "details": details,
    }


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(
            "用法: python scripts/eval_b3_gates.py <run_id> <highrisk_sample.json> [out_dir]\n"
            "示例: python scripts/eval_b3_gates.py ab_evidence_戴夫健身_2_30_items_v1 ./tmp/b3_highrisk_30.json"
        )
    run_id = sys.argv[1]
    sample_path = Path(sys.argv[2])
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else APP_DIR / "data" / ".insight" / f"{run_id}_gates"
    report = evaluate(run_id, sample_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "b3_gate_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# evidence_items_v1 高风险 30 条门槛报告",
        "",
        f"- run_id: `{report['run_id']}`",
        f"- n: `{report['n']}`",
        "",
        "## Gates",
        "",
        "```json",
        json.dumps(report["gates"], ensure_ascii=False, indent=2),
        "```",
        "",
        f"- status: `{report['status_counts']}`",
        f"- level: `{report['level_counts']}`",
        "",
    ]
    (out_dir / "b3_gate_report.md").write_text("\n".join(md), encoding="utf-8")
    print(
        json.dumps(
            {
                "gates": report["gates"],
                "status_counts": report["status_counts"],
                "level_counts": report["level_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
