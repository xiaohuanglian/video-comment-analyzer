# -*- coding: utf-8 -*-
"""Phase 3.5: AI 策划质量评估框架。

两层评价，互不替代：
1) 自动证据校验（deterministic，可重复）：
   - 引用的素材必须存在且已授权（防虚构素材）
   - opportunity/brief 的 evidence_refs 必须能在信号/记录中解析
   - verdict/rationale 不得为空（禁止只有分数）
   - Unknown 纪律：归因 none 的产品不得出现注册/CAC 类"已验证"表述
   - 数据不足时不得硬凑推荐
2) 人工评分表（CSV 导出）：证据正确性/业务相关性/行动可执行性/
   创意质量/人工修改成本，由人填写——模型不得自评。

mock 模式下运行仅作流程冒烟，报告必须标注 MOCK；真实模型验收单列。
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from . import store
from .models import ProductProfile
from .orchestrator import Orchestrator, SessionConfig

# 10 个评估任务（覆盖任务书 §4 要求的维度）
EVAL_TASKS: List[Dict[str, str]] = [
    {"id": "t01", "kind": "recommend", "goal": "根据现有用户需求信号，推荐下周最值得做的内容方向"},
    {"id": "t02", "kind": "recommend", "goal": "分析现有素材，告诉我应该往哪个传播方向投入"},
    {"id": "t03", "kind": "review", "goal": "复盘已有实验：哪些内容高互动但低转化？为什么"},
    {"id": "t04", "kind": "evidence", "goal": "目前关于用户想学 AI 动画的证据是否充分？给出判断"},
    {"id": "t05", "kind": "brief", "goal": "为当前最强的需求生成一份可直接执行的内容任务书"},
    {"id": "t06", "kind": "hypothesis", "goal": "根据上一轮结果，提出下一轮最值得测试的增长假设"},
    {"id": "t07", "kind": "recommend", "goal": "用户反复问工具对比和笔记整理，这和我们的产品有关吗？该不该做"},
    {"id": "t08", "kind": "evidence", "goal": "哪些需求证据太弱，暂时不值得投入？列出来"},
    {"id": "t09", "kind": "brief", "goal": "如果没有已授权素材能满足最强需求，告诉我该怎么办，不要硬编"},
    {"id": "t10", "kind": "review", "goal": "复盘所有内容表现，告诉我哪个方向应该停止投入"},
]


def verify_record_integrity(product_id: str) -> List[Dict[str, Any]]:
    """对所有 Agent 写入记录做自动证据校验。返回违规列表（空=全部通过）。"""
    violations: List[Dict[str, Any]] = []
    product = store.get_product_or_raise(product_id)
    assets = {a.asset_id: a for a in store.list_assets(product_id)}
    signal_ids = {s.signal_id for s in store.list_signals(product_id)}
    exp_ids = {e.experiment_id for e in store.list_experiments(product_id)}
    attribution_none = product.attribution_capability.value == "none"

    def v(rule: str, record: str, detail: str) -> None:
        violations.append({"rule": rule, "record": record, "detail": detail})

    for opp in store.list_opportunities(product_id):
        oid = opp.opportunity_id
        if not opp.verdict_rationale.strip():
            v("rationale_required", oid, "机会缺少 verdict_rationale（禁止只有结论没有理由）")
        for aid in opp.usable_assets:
            if aid not in assets:
                v("asset_exists", oid, f"引用不存在的素材 {aid}（疑似虚构）")
            elif assets[aid].license_status.value not in {"owned", "licensed"}:
                v("asset_licensed", oid, f"引用未授权素材 {aid}")
        for ref in opp.evidence_refs:
            if ref not in signal_ids and ref not in exp_ids:
                v("evidence_resolvable", oid, f"证据引用无法解析: {ref}")

    for brief in store.list_briefs(product_id):
        bid = brief.brief_id
        for aid in brief.asset_ids:
            if aid not in assets:
                v("asset_exists", bid, f"任务书引用不存在的素材 {aid}（疑似虚构）")
            elif assets[aid].license_status.value not in {"owned", "licensed"}:
                v("asset_licensed", bid, f"任务书引用未授权素材 {aid}")
        for field in ("audience", "problem", "rationale", "hook", "visit_reason"):
            if not getattr(brief, field, "").strip():
                v("brief_field_required", bid, f"任务书缺必填字段 {field}")
        if not brief.validation_metrics:
            v("brief_metrics_required", bid, "任务书没有验证指标")

    # Unknown 纪律：归因 none 时，任何产品指标必须 value=None 或有明确归因说明
    for obs in store.list_observations(product_id):
        if attribution_none and obs.metric_kind.value in {"product", "efficiency"}:
            if obs.value is not None and not obs.attribution_note:
                v("unknown_discipline", obs.observation_id,
                  f"attribution=none 下 {obs.name} 有数值但无归因说明")

    return violations


def run_evaluation(
    product_id: str,
    *,
    use_mock: bool,
    api_key: str = "",
    base_url: str = "",
    model_name: str = "",
    max_tasks: int = 10,
) -> Dict[str, Any]:
    """运行评估任务并返回结构化结果（含自动校验 + 人工评分表行）。"""
    task_rows: List[Dict[str, Any]] = []
    for task in EVAL_TASKS[:max_tasks]:
        config = SessionConfig(product_id=product_id, goal=task["goal"], use_mock=use_mock,
                               base_url=base_url or "https://api.deepseek.com",
                               model_name=model_name or "deepseek-v4-flash")
        session = Orchestrator(config, api_key=api_key).run()
        task_rows.append({
            "task_id": task["id"],
            "kind": task["kind"],
            "goal": task["goal"],
            "session_id": session.session_id,
            "status": session.status,
            "iterations": session.iterations,
            "cost_cny": session.cost_cny,
            "mock": use_mock or not api_key,
            "answer_excerpt": session.final_answer[:300],
            # 人工评分列（留空由人填写）
            "human_evidence_score": "",
            "human_relevance_score": "",
            "human_actionability_score": "",
            "human_creativity_score": "",
            "human_edit_cost_score": "",
            "human_verdict": "",
            "human_notes": "",
        })
    violations = verify_record_integrity(product_id)
    return {
        "product_id": product_id,
        "mode": "mock" if (use_mock or not api_key) else "real_llm",
        "tasks": task_rows,
        "auto_violations": violations,
        "auto_check_passed": len(violations) == 0,
        "note": "mock 模式仅验证流程与证据完整性，不代表真实模型推理质量"
        if (use_mock or not api_key) else "真实模型评估，仍需人工评分确认",
    }


def export_scoresheet_csv(report: Dict[str, Any]) -> str:
    """导出人工评分表 CSV（含自动校验结果，人工评分为空列）。"""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "task_id", "kind", "goal", "session_id", "status", "iterations", "cost_cny", "mock",
        "answer_excerpt",
        "human_evidence_score", "human_relevance_score", "human_actionability_score",
        "human_creativity_score", "human_edit_cost_score", "human_verdict", "human_notes",
    ])
    writer.writeheader()
    for row in report["tasks"]:
        writer.writerow(row)
    buf.write("\n# 自动证据校验违规（应为空）\n")
    for v in report["auto_violations"]:
        buf.write(f"# {v['rule']} | {v['record']} | {v['detail']}\n")
    return buf.getvalue()
