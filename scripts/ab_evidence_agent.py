# -*- coding: utf-8 -*-
"""A/B runner: legacy per-record results (A) vs evidence_agent_v1 (B)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.services.insight.conclusion_review import run_conclusion_review
from api.services.insight.evidence_extractor import run_evidence_extraction
from api.services.insight.evidence_schemas import (
    ANALYSIS_VERSION_EVIDENCE,
    is_spam_validity,
    normalize_validity,
)
from api.services.insight.research_agent import run_research_analysis
from api.services.insight.schemas import FieldMapping, RunConfig, SourceRecord
from api.services.insight.storage import (
    create_run,
    load_evidence_cards,
    load_results,
    save_conclusion_review,
    save_research_analysis,
    save_research_report,
)

DEFAULT_LEGACY_RUN = "戴夫健身_2"
DEFAULT_LIMIT = 100


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize_legacy_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    intent_counts: Dict[str, int] = {}
    hyp_support = {"H1": 0, "H2": 0, "H3": 0}
    hyp_weaken = {"H1": 0, "H2": 0, "H3": 0}
    with_problems = 0
    with_hyp = 0
    for row in rows:
        analysis = row.get("analysis") or {}
        intent = analysis.get("primary_intent") or "unknown"
        intent_counts[intent] = intent_counts.get(intent, 0) + 1
        if analysis.get("specific_problems"):
            with_problems += 1
        relations = analysis.get("hypothesis_relations") or []
        if relations:
            with_hyp += 1
        for rel in relations:
            hid = rel.get("hypothesis_id")
            relation = rel.get("relation")
            if hid in hyp_support and relation == "supports":
                hyp_support[hid] += 1
            if hid in hyp_weaken and relation == "weakens":
                hyp_weaken[hid] += 1
    return {
        "n": len(rows),
        "intent_counts": intent_counts,
        "comments_with_problems": with_problems,
        "comments_with_hypothesis_fields": with_hyp,
        "hypothesis_supports": hyp_support,
        "hypothesis_weakens": hyp_weaken,
        "notes": [
            "A 组为逐条强制填写 H1/H2/H3、product_fit、signals 等字段的旧管线产物。",
            "本报告优先复用已有 results.jsonl，避免重复计费。",
        ],
    }


def _summarize_evidence(card_rows: List[Dict[str, Any]], research: Dict[str, Any], review: Dict[str, Any]) -> Dict[str, Any]:
    expr_counts: Dict[str, int] = {}
    validity_counts: Dict[str, int] = {}
    with_problems = 0
    with_behavior = 0
    spam_or_legacy_invalid = 0
    cache_reuse = 0
    for row in card_rows:
        card = row.get("card") or {}
        expr = card.get("primary_expression") or "other"
        expr_counts[expr] = expr_counts.get(expr, 0) + 1
        validity = normalize_validity(card.get("validity")).value
        validity_counts[validity] = validity_counts.get(validity, 0) + 1
        if card.get("problem_or_need"):
            with_problems += 1
        if card.get("actual_behavior"):
            with_behavior += 1
        if is_spam_validity(card.get("validity")):
            spam_or_legacy_invalid += 1
        if card.get("reused_from_record_id") or row.get("from_cache"):
            cache_reuse += 1
    hyp = []
    for item in (research.get("hypothesis_assessment") or []):
        hyp.append(
            {
                "hypothesis_id": item.get("hypothesis_id"),
                "conclusion": item.get("conclusion"),
                "support_n": len(item.get("supporting_record_ids") or []),
                "weaken_n": len(item.get("weakening_record_ids") or []),
            }
        )
    summary = research.get("dataset_summary") or {}
    structural = review.get("structural_review_passed")
    if structural is None:
        structural = review.get("passed")
    return {
        "n": len(card_rows),
        "expression_counts": expr_counts,
        "validity_counts": validity_counts,
        "comments_with_problems": with_problems,
        "comments_with_behavior": with_behavior,
        "spam_or_garbled_or_legacy_invalid": spam_or_legacy_invalid,
        "cache_reuse": cache_reuse,
        "dataset_summary": summary,
        "theme_covered_comments": summary.get("theme_covered_comments"),
        "theme_coverage_rate": summary.get("theme_coverage_rate"),
        "hypothesis_assessment": hyp,
        "themes": [
            {
                "theme_id": t.get("theme_id"),
                "theme_name": t.get("theme_name"),
                "comment_count": t.get("comment_count"),
            }
            for t in (research.get("themes") or [])
        ],
        "structural_review_passed": structural,
        "review_issue_count": len(review.get("issues") or []),
        "notes": [
            "B 组单条不强制判断 H1/H2/H3；假设在数据集级统一评估。",
            "统计数字由代码按 record_id 回算。",
            "structural_review_passed 仅表示证据与结构校验通过，不表示内容质量通过。",
        ],
    }


def build_markdown_report(
    *,
    legacy_run_id: str,
    evidence_run_id: str,
    a_summary: Dict[str, Any],
    b_summary: Dict[str, Any],
    mode: str,
    extract_stats: Dict[str, Any],
) -> str:
    perf = extract_stats.get("performance") or {}
    lines = [
        "# A/B 证据 Agent 对比报告",
        "",
        f"- 生成时间：`{_utc_now()}`",
        f"- A 组来源任务：`{legacy_run_id}`（旧 results.jsonl）",
        f"- B 组任务：`{evidence_run_id}`（evidence_agent_v1）",
        f"- B 组运行模式：`{mode}`",
        f"- 样本条数：{a_summary.get('n')} / {b_summary.get('n')}",
        "",
        "## 速度与成本",
        "",
        "| 指标 | A 组 | B 组 |",
        "|---|---:|---:|",
        f"| 样本数 | {a_summary.get('n')} | {b_summary.get('n')} |",
        f"| 总耗时（秒） | 不完整（历史任务） | {perf.get('elapsed_seconds', '—')} |",
        f"| 每分钟评论数 | 不完整 | {perf.get('comments_per_minute', '—')} |",
        f"| 请求次数 | 不完整 | {perf.get('requests_count', extract_stats.get('requests_count', '—'))} |",
        f"| 重试次数 | 不完整 | {perf.get('retry_count', extract_stats.get('retries', '—'))} |",
        f"| 批次数 | 不完整 | {perf.get('batch_count', '—')} |",
        f"| 平均批延迟（秒） | — | {perf.get('average_batch_latency', '—')} |",
        f"| P50 批延迟（秒） | — | {perf.get('p50_batch_latency', '—')} |",
        f"| P95 批延迟（秒） | — | {perf.get('p95_batch_latency', '—')} |",
        f"| prompt_tokens | 不完整 | {extract_stats.get('prompt_tokens')} |",
        f"| completion_tokens | 不完整 | {extract_stats.get('completion_tokens')} |",
        f"| cache_hits | 不完整 | {extract_stats.get('cache_hits')} |",
        f"| format_failures | — | {extract_stats.get('format_failures')} |",
        f"| actual_cost | 不完整 | {perf.get('actual_cost')} |",
        "",
        "> A 组性能数据不完整，不能做严格同口径比较。未配置单价时 `actual_cost` 为 null，不以静态估算冒充实测。",
        "",
        "## 主题覆盖率（B）",
        "",
        f"- 有效/参与评论数：`{(b_summary.get('dataset_summary') or {}).get('valid_comments')}`",
        f"- 有意义证据：`{(b_summary.get('dataset_summary') or {}).get('meaningful_comments')}`",
        f"- 低信息有效：`{(b_summary.get('dataset_summary') or {}).get('low_information_comments')}`",
        f"- spam/乱码：`{(b_summary.get('dataset_summary') or {}).get('spam_comments')}`",
        f"- 进入主题评论数：`{b_summary.get('theme_covered_comments')}`",
        f"- 主题覆盖率：`{b_summary.get('theme_coverage_rate')}`",
        f"- 未归入主题的有意义评论：`{(b_summary.get('dataset_summary') or {}).get('unthemed_meaningful_comments')}`",
        "",
        "## 自动校验说明",
        "",
        f"- `structural_review_passed`：`{b_summary.get('structural_review_passed')}`（证据与结构校验通过，**不等于**内容质量通过）",
        f"- issue 数：`{b_summary.get('review_issue_count')}`",
        "",
        "## A 组（旧逐条分析）摘要",
        "",
        "```json",
        json.dumps(a_summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## B 组（证据卡 → 研究 → 校验）摘要",
        "",
        "```json",
        json.dumps(b_summary, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 人工盲评",
        "",
        "- 人工评分完成前，**不得**宣称 B 质量通过，也不得切换默认路径。",
        "",
        "## 迁移建议",
        "",
        "- 完成本地盲评并统计 invalid 误伤率 / other 可细分率 / B 新增问题准确率后，再决定是否进入第二阶段。",
        "- 本阶段**未**改前端默认路径，旧任务仍可读。",
        "",
    ]
    return "\n".join(lines)


def run_ab(
    *,
    legacy_run_id: str = DEFAULT_LEGACY_RUN,
    limit: int = DEFAULT_LIMIT,
    use_mock: bool = True,
    api_key: str = "",
    evidence_run_id: Optional[str] = None,
    report_path: Optional[Path] = None,
    record_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    legacy_rows = load_results(legacy_run_id, limit=0 if record_ids else limit)
    if not legacy_rows:
        raise FileNotFoundError(f"找不到 A 组结果：run_id={legacy_run_id}")

    if record_ids:
        want = set(record_ids)
        by_id = {}
        for row in legacy_rows:
            rid = row.get("record_id") or (row.get("source") or {}).get("internal_record_id")
            if rid:
                by_id[rid] = row
        missing = [rid for rid in record_ids if rid not in by_id]
        if missing:
            raise FileNotFoundError(f"A 组缺少 {len(missing)} 条 record_id，例：{missing[:3]}")
        legacy_rows = [by_id[rid] for rid in record_ids]

    records: List[SourceRecord] = []
    for row in legacy_rows:
        source = row.get("source") or {}
        if not source.get("internal_record_id") and row.get("record_id"):
            source = {**source, "internal_record_id": row["record_id"]}
        # Ensure required fields
        if "source_file" not in source:
            source["source_file"] = source.get("source_file") or "ab_sample"
        if "source_row_number" not in source:
            source["source_row_number"] = 0
        if "comment_text" not in source:
            source["comment_text"] = ""
        records.append(SourceRecord.model_validate(source))

    suffix = f"{len(records)}_b3" if record_ids else str(limit)
    run_id = evidence_run_id or f"ab_evidence_{legacy_run_id}_{suffix}"
    config = RunConfig(
        run_id=run_id,
        name=f"AB evidence vs {legacy_run_id}",
        file_paths=[],
        field_mapping=FieldMapping(comment_text="content"),
        use_mock=use_mock,
        analysis_version=ANALYSIS_VERSION_EVIDENCE,
        analysis_mode="full_llm",
        batch_size=20,
        concurrency=8,
        created_at=_utc_now(),
        analysis_limit=0,
        use_llm_review=False,
    )
    # Fresh run dir each time for AB
    create_run(config, records)

    from api.services.insight.run_locations import run_dir_for_id

    evidence_path = run_dir_for_id(run_id) / "evidence_cards.jsonl"
    evidence_path.write_text("", encoding="utf-8")

    result = run_evidence_extraction(
        records,
        use_mock=use_mock,
        config=config,
        api_key=api_key,
        batch_size=config.batch_size,
    )
    record_by_id = {r.internal_record_id: r for r in records}
    from api.services.insight.evidence_writer import EvidenceWriterQueue
    from api.services.insight.storage import replace_evidence_cards

    # Clear again after extract so any stray mid-run appends cannot duplicate
    evidence_path.write_text("", encoding="utf-8")
    writer = EvidenceWriterQueue(run_id)
    writer.start()
    try:
        for card in result.cards:
            source = record_by_id[card.record_id]
            writer.put(
                source,
                card,
                prompt_tokens=0,
                completion_tokens=0,
                from_cache=bool(card.reused_from_record_id),
            )
    finally:
        writer.close()

    # Finalize with deduped rows (last write wins)
    card_rows = load_evidence_cards(run_id)
    replace_evidence_cards(run_id, card_rows)
    import time as _time

    research_started = _time.perf_counter()
    research, _research_usage = run_research_analysis(
        records,
        card_rows,
        use_mock=use_mock,
        config=config,
        api_key=api_key,
    )
    research_elapsed = _time.perf_counter() - research_started
    save_research_analysis(run_id, research.model_dump())

    review, _review_usage = run_conclusion_review(
        research,
        records,
        card_rows=card_rows,
        use_mock=use_mock,
        config=config,
        api_key=api_key,
        use_llm_review=False,
    )
    save_conclusion_review(run_id, review.model_dump())

    from api.services.insight.readable_report import build_readable_report

    perf = dict(result.stats.performance or {})
    perf["research_elapsed_seconds"] = round(research_elapsed, 3)
    readable = build_readable_report(
        research=research.model_dump(),
        records=records,
        card_rows=card_rows,
        run_id=run_id,
        performance=perf,
    )
    save_research_report(run_id, readable)
    readable_path = run_dir_for_id(run_id) / "research_report.md"

    a_summary = _summarize_legacy_rows(legacy_rows)
    b_summary = _summarize_evidence(card_rows, research.model_dump(), review.model_dump())
    mode = "mock" if use_mock else "real_api"
    extract_stats = {
        "processed": result.stats.processed,
        "failed": result.stats.failed,
        "cache_hits": result.stats.cache_hits,
        "format_failures": result.stats.format_failures,
        "splits": result.stats.splits,
        "retries": result.stats.retries,
        "requests_count": result.stats.requests_count,
        "prompt_tokens": result.stats.prompt_tokens + _research_usage.prompt_tokens + _review_usage.prompt_tokens,
        "completion_tokens": result.stats.completion_tokens
        + _research_usage.completion_tokens
        + _review_usage.completion_tokens,
        "performance": perf,
        "research_elapsed_seconds": round(research_elapsed, 3),
    }
    # Persist performance next to run artifacts
    perf_path = run_dir_for_id(run_id) / "performance.json"
    perf_path.write_text(json.dumps(extract_stats, ensure_ascii=False, indent=2), encoding="utf-8")
    report = build_markdown_report(
        legacy_run_id=legacy_run_id,
        evidence_run_id=run_id,
        a_summary=a_summary,
        b_summary=b_summary,
        mode=mode,
        extract_stats=extract_stats,
    )
    out = report_path or (APP_DIR / "data" / ".insight" / f"{evidence_run_id}_ab_report.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    return {
        "legacy_run_id": legacy_run_id,
        "evidence_run_id": run_id,
        "mode": mode,
        "report_path": str(out),
        "a_summary": a_summary,
        "b_summary": b_summary,
        "extract_stats": extract_stats,
        "structural_review_passed": review.structural_review_passed,
        "review_passed": review.passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run evidence-agent A/B comparison")
    parser.add_argument("--legacy-run", default=DEFAULT_LEGACY_RUN)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--real", action="store_true", help="Call real LLM API (needs API key)")
    parser.add_argument("--api-key", default=os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or "")
    parser.add_argument("--evidence-run", default="", help="B group run_id (e.g. ab_evidence_戴夫健身_2_100_b2)")
    parser.add_argument("--report", default="")
    parser.add_argument(
        "--record-ids-file",
        default="",
        help="JSON list of record_id or [{record_id,bucket}...] for high-risk subset runs",
    )
    args = parser.parse_args()
    use_mock = not args.real
    if args.real and not args.api_key.strip():
        raise SystemExit("真实 API 模式需要 --api-key 或环境变量 DEEPSEEK_API_KEY / OPENAI_API_KEY")
    record_ids = None
    if args.record_ids_file:
        payload = json.loads(Path(args.record_ids_file).read_text(encoding="utf-8"))
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            record_ids = [row["record_id"] for row in payload]
        elif isinstance(payload, list):
            record_ids = [str(x) for x in payload]
        else:
            raise SystemExit("--record-ids-file 需为 JSON 数组")
    result = run_ab(
        legacy_run_id=args.legacy_run,
        limit=args.limit,
        use_mock=use_mock,
        api_key=args.api_key,
        evidence_run_id=args.evidence_run or None,
        report_path=Path(args.report) if args.report else None,
        record_ids=record_ids,
    )
    print(json.dumps({k: result[k] for k in ("evidence_run_id", "mode", "report_path", "review_passed", "extract_stats")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
