# -*- coding: utf-8 -*-
"""Run the compact protocol against the same 502-record dataset.

API keys are read from DEEPSEEK_API_KEY or a hidden prompt and never persisted.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import threading
import time
from pathlib import Path
from openai import OpenAI

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from api.services.insight.analyzer import build_summary, run_analysis_batch
from api.services.insight.evidence_schemas import EVIDENCE_PROMPT_VERSION
from api.services.insight.evidence_extractor import call_evidence_batch_llm
from api.services.insight.run_locations import run_dir_for_id
from api.services.insight.schemas import SourceRecord
from api.services.insight.storage import (
    create_run,
    load_config,
    load_evidence_cards,
    load_progress,
    load_source_records,
)
from api.services.insight.validation import quote_exists, source_text_pool

BASELINE = {
    "prompt_tokens": 85716,
    "completion_tokens": 162610,
    "actual_cost": 0.3894,
}


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _pct_drop(before: float, after: float) -> str:
    if not before:
        return "—"
    return f"{(before - after) / before:.1%}"


def _evidence_counts(rows: list[dict]) -> dict[str, int]:
    return {key: len(value) for key, value in _evidence_id_sets(rows).items()}


def _evidence_id_sets(rows: list[dict]) -> dict[str, set[str]]:
    matched = {
        "problem": set(),
        "behavior": set(),
        "action_gap": set(),
        "paid_help": set(),
        "quantitative": set(),
    }
    for row in rows:
        rid = str(row.get("record_id") or "")
        card = row.get("card") or {}
        items = [item for item in card.get("evidence_items") or [] if isinstance(item, dict)]
        types = {str(item.get("type") or "") for item in items}
        for key in ("problem", "behavior", "action_gap", "quantitative"):
            if key in types:
                matched[key].add(rid)
        if any(
            str(item.get("subtype") or "") in {"sought_paid_help", "paid_but_no_result"}
            for item in items
        ):
            matched["paid_help"].add(rid)
    return matched


def _quote_integrity(rows: list[dict]) -> tuple[int, int]:
    valid = 0
    total = 0
    for row in rows:
        source = row.get("source") or {}
        pool = source_text_pool(SourceRecord.model_validate(source))
        for item in (row.get("card") or {}).get("evidence_items") or []:
            quote = str((item or {}).get("evidence_quote") or "")
            if not quote:
                continue
            total += 1
            valid += int(quote_exists(quote, pool))
    return valid, total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run", default="评论洞察任务")
    parser.add_argument("--run-id", default="评论洞察任务_compact_v9_502")
    args = parser.parse_args()

    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not api_key:
        api_key = getpass.getpass("DeepSeek API Key（不会保存）: ").strip()
    if not api_key:
        raise SystemExit("缺少 API Key，未执行付费实测")

    source_config = load_config(args.source_run)
    records = load_source_records(args.source_run)
    if len(records) != 502:
        raise SystemExit(f"必须使用同一批 502 条数据，当前为 {len(records)} 条")

    smoke_config = source_config.model_copy(
        update={"batch_size": 20, "concurrency": 8, "use_mock": False}
    )
    print("先执行 2 条 API 烟雾测试…", flush=True)
    smoke_client = OpenAI(
        api_key=api_key,
        base_url=(smoke_config.base_url or None) or None,
        timeout=45.0,
        max_retries=0,
    )
    try:
        smoke_cards, smoke_usage = call_evidence_batch_llm(
            records[:2], smoke_config, api_key, client=smoke_client
        )
    except Exception as exc:
        raise SystemExit(f"烟雾测试失败，已停止 502 条实测：{type(exc).__name__}: {exc}") from exc
    if len(smoke_cards) != 2:
        raise SystemExit(f"烟雾测试只返回 {len(smoke_cards)}/2 条，已停止")
    print(
        f"烟雾测试通过：输入 {smoke_usage.prompt_tokens} / 输出 "
        f"{smoke_usage.completion_tokens} Token；开始 502 条实测。",
        flush=True,
    )
    try:
        existing_dir = run_dir_for_id(args.run_id)
    except FileNotFoundError:
        existing_dir = None

    if existing_dir is not None:
        existing_progress = load_progress(args.run_id)
        if existing_progress.completed > 0 or load_evidence_cards(args.run_id):
            raise SystemExit(f"任务 {args.run_id} 已有结果；为避免混用数据，请更换 --run-id")
        print(f"继续未完成任务：{args.run_id}", flush=True)
    else:
        config = source_config.model_copy(
            update={
                "run_id": args.run_id,
                "name": args.run_id,
                "storage_dir": "",
                "use_mock": False,
                "analysis_limit": 0,
                "batch_size": 20,
                "concurrency": 8,
            }
        )
        create_run(config, records)

    stop_heartbeat = threading.Event()
    started = time.monotonic()

    def heartbeat() -> None:
        while not stop_heartbeat.wait(15):
            elapsed = int(time.monotonic() - started)
            print(f"仍在分析中，已运行 {elapsed} 秒…", flush=True)

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()
    try:
        run_analysis_batch(args.run_id, use_mock=False, api_key=api_key)
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)
    build_summary(args.run_id)

    progress = load_progress(args.run_id)
    run_dir = run_dir_for_id(args.run_id)
    extract_perf = _read_json(run_dir / "extract_performance.json")
    research_perf = _read_json(run_dir / "research_performance.json")
    new_rows = load_evidence_cards(args.run_id)
    old_rows = load_evidence_cards(args.source_run)
    quote_valid, quote_total = _quote_integrity(new_rows)
    old_counts = _evidence_counts(old_rows)
    new_counts = _evidence_counts(new_rows)
    old_sets = _evidence_id_sets(old_rows)
    new_sets = _evidence_id_sets(new_rows)
    recalls = {
        key: len(old_sets[key] & new_sets[key]) / len(old_sets[key]) if old_sets[key] else 1.0
        for key in old_sets
    }
    old_status = {
        str(row.get("record_id") or ""): str((row.get("card") or {}).get("record_status") or "")
        for row in old_rows
    }
    new_status = {
        str(row.get("record_id") or ""): str((row.get("card") or {}).get("record_status") or "")
        for row in new_rows
    }
    status_agreement = (
        sum(new_status.get(rid) == status for rid, status in old_status.items()) / len(old_status)
        if old_status
        else 1.0
    )

    baseline_total = BASELINE["prompt_tokens"] + BASELINE["completion_tokens"]
    extract_prompt_tokens = int(extract_perf.get("prompt_tokens") or 0)
    extract_completion_tokens = int(extract_perf.get("completion_tokens") or 0)
    extract_cost = float(extract_perf.get("actual_cost") or 0)
    compact_total = extract_prompt_tokens + extract_completion_tokens
    rows = [
        ("输入 Token", BASELINE["prompt_tokens"], extract_prompt_tokens),
        ("输出 Token", BASELINE["completion_tokens"], extract_completion_tokens),
        ("总 Token", baseline_total, compact_total),
        ("平均输入 Token/条", BASELINE["prompt_tokens"] / 502, extract_prompt_tokens / 502),
        ("平均输出 Token/条", BASELINE["completion_tokens"] / 502, extract_completion_tokens / 502),
        ("平均总 Token/条", baseline_total / 502, compact_total / 502),
        (
            "请求次数",
            "基线未同口径留存",
            int(extract_perf.get("requests_count") or 0)
            + int(bool((research_perf.get("prompt_tokens") or 0) + (research_perf.get("completion_tokens") or 0))),
        ),
        ("重试次数", "基线未同口径留存", extract_perf.get("retry_count", "—")),
        ("提取耗时", "基线未同口径留存", f"{extract_perf.get('elapsed_seconds', '—')}s"),
        ("研究耗时", "基线未同口径留存", f"{research_perf.get('research_elapsed_seconds', '—')}s"),
        ("总费用", BASELINE["actual_cost"], extract_cost),
    ]
    table = [
        "| 指标 | 当前完整 JSON | 紧凑协议 | 降幅 |",
        "|---|---:|---:|---:|",
    ]
    for label, before, after in rows:
        drop = _pct_drop(float(before), float(after)) if isinstance(before, (int, float)) and isinstance(after, (int, float)) else "—"
        table.append(f"| {label} | {before} | {after} | {drop} |")

    success_rate = progress.completed / progress.total_records if progress.total_records else 0
    quote_rate = quote_valid / quote_total if quote_total else 1.0
    completion_drop = (BASELINE["completion_tokens"] - extract_completion_tokens) / BASELINE["completion_tokens"]
    total_drop = (baseline_total - compact_total) / baseline_total
    cost_drop = (BASELINE["actual_cost"] - extract_cost) / BASELINE["actual_cost"]
    passed = (
        extract_completion_tokens / 502 <= 180
        and completion_drop >= 0.35
        and total_drop >= 0.25
        and cost_drop >= 0.20
        and quote_rate == 1.0
        and success_rate >= 0.99
        and recalls["behavior"] >= 0.85
        and recalls["action_gap"] >= 0.85
        and recalls["paid_help"] >= 0.90
        and recalls["quantitative"] >= 0.85
        and status_agreement >= 0.90
    )

    report = "\n".join(
        [
            f"# 紧凑协议 502 条实测 · {EVIDENCE_PROMPT_VERSION}",
            "",
            *table,
            "",
            "## 质量门槛",
            "",
            f"- 成功率：{progress.completed}/{progress.total_records}（{success_rate:.1%}）",
            f"- quote 完整率：{quote_valid}/{quote_total}（{quote_rate:.1%}）",
            f"- problem 旧样本召回：{recalls['problem']:.1%}（{old_counts['problem']} → {new_counts['problem']}）",
            f"- behavior 旧样本召回：{recalls['behavior']:.1%}（{old_counts['behavior']} → {new_counts['behavior']}）",
            f"- action_gap 旧样本召回：{recalls['action_gap']:.1%}（{old_counts['action_gap']} → {new_counts['action_gap']}）",
            f"- paid_help 旧样本召回：{recalls['paid_help']:.1%}（{old_counts['paid_help']} → {new_counts['paid_help']}）",
            f"- quantitative 旧样本召回：{recalls['quantitative']:.1%}（{old_counts['quantitative']} → {new_counts['quantitative']}）",
            f"- record_status 一致率：{status_agreement:.1%}",
            f"- 研究 Token：输入 {research_perf.get('prompt_tokens', 0)} / 输出 {research_perf.get('completion_tokens', 0)}",
            f"- 全流程费用（提取+研究）：{progress.actual_cost:.6f} {progress.currency}",
            f"- Token 验收：{'通过' if passed else '未通过'}",
            "",
            "注：基线 Token/费用只统计评论提取，因此主表严格使用紧凑协议的提取数据；研究 Token 另列，不混入主表。基线未留存同口径请求次数与耗时，不做伪造比较。",
            "",
        ]
    )
    (run_dir / "compact_token_benchmark.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"报告：{run_dir / 'compact_token_benchmark.md'}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
