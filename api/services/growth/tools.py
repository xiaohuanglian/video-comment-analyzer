# -*- coding: utf-8 -*-
"""Agent tool registry (Phase 2).

Each tool declares: input schema, output schema (loose), permission level,
per-session call cap and timeout. Handlers wrap *existing* capabilities —
no reimplementation of the insight pipeline.

Permission levels (任务书 §4):
- L1: autonomous inside authorized data scope & budget.
- L2: needs task-scoped grant recorded on the session (time/budget bounded).
- L3: always needs explicit human approval; the orchestrator never self-grants.
"""

from __future__ import annotations

import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from . import store
from .models import (
    AuditRecord,
    ContentAsset,
    ContentBrief,
    GrowthExperiment,
    GrowthOpportunity,
    LearningRecord,
    MetricKind,
    MetricsObservation,
    PublishRecord,
    Signal,
    UserSegmentReport,
    utc_now_iso,
)

L1, L2, L3 = "L1", "L2", "L3"


class ToolSpec(BaseModel):
    name: str
    description: str
    args_schema: Dict[str, Any] = Field(default_factory=dict)  # JSON schema (object)
    permission: str = L1
    max_calls_per_session: int = 3
    timeout_seconds: int = 30


class ToolDenied(Exception):
    pass


def _normalize_dedupe_key(text: str) -> str:
    """归一化查重键：去空白/标点/大小写。只做候选去重；语义归并要求更高置信，由人工确认。"""
    import re

    return re.sub(r"[\s，。？！、,.?!:：;；「」“”\"']+", "", (text or "")).lower()[:80]


def _ctx_data_nature(ctx: ToolContext) -> str:
    """本会话写入的数据性质：演示产品 → demo；mock 会话 → mock；否则 real。"""
    try:
        product = store.get_product(ctx.product_id)
        if product and product.is_demo:
            return "demo"
    except Exception:
        pass
    return "mock" if ctx.mock else "real"


class ToolResult(BaseModel):
    status: str = "ok"  # ok / denied / error
    data: Any = None
    error: str = ""


# --- context -----------------------------------------------------------------


class ToolContext:
    """Per-session execution state passed to every tool call."""

    def __init__(
        self,
        *,
        product_id: str,
        session_id: str,
        l2_grants: Optional[List[str]] = None,
        api_key: str = "",
        base_url: str = "",
        model_name: str = "",
        mock: bool = False,
    ) -> None:
        self.product_id = product_id
        self.session_id = session_id
        self.l2_grants = set(l2_grants or [])
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.mock = mock  # 本会话产出的经验记录标 mock，不进正式策略检索


# --- handlers (reuse existing modules) ---------------------------------------


def _list_analysis_runs(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    from ..insight.run_locations import load_run_index

    index = load_run_index()
    if isinstance(index, dict):
        entries = [{"run_id": str(k), "storage_dir": str(v)} for k, v in index.items()]
    else:
        entries = [r for r in (index or []) if isinstance(r, dict)]
    return {"runs": entries[: int(args.get("limit", 20))], "total": len(entries),
            "note": "已有评论分析任务索引；详情用 get_run_summary"}


def _get_run_summary(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    from ..insight import storage as run_storage

    run_id = str(args["run_id"])
    try:
        config = run_storage.load_config(run_id)
    except FileNotFoundError:
        raise ValueError(f"run 不存在: {run_id}")
    summary = run_storage.load_summary(run_id)
    progress = run_storage.load_progress(run_id)
    return {
        "run_id": run_id,
        "project_id": config.project_id,
        "total_records": progress.total_records,
        "completed": progress.completed,
        "summary_keys": sorted(summary.keys()) if isinstance(summary, dict) else [],
    }


def _get_run_top_needs(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """Code-only aggregation over existing analysis results (no LLM)."""
    from ..insight import storage as run_storage

    run_id = str(args["run_id"])
    limit = int(args.get("limit", 10))
    try:
        run_storage.load_config(run_id)
    except FileNotFoundError:
        raise ValueError(f"run 不存在: {run_id}")
    needs: Counter = Counter()
    problems: Counter = Counter()
    quotes: Dict[str, List[str]] = {}
    for row in run_storage.iter_results(run_id):
        analysis = (row or {}).get("analysis") or {}
        for field, counter in (("potential_needs", needs), ("specific_problems", problems)):
            for item in analysis.get(field) or []:
                text = str(item).strip()
                if text:
                    counter[text] += 1
        # evidence_items_v1：新信号也常包含需求/问题文本
        for sig in analysis.get("new_signals") or []:
            if not isinstance(sig, dict):
                continue
            text = str(sig.get("text") or "").strip()
            stype = str(sig.get("type") or "")
            if not text:
                continue
            if stype in {"new_problem", "new_barrier"}:
                problems[text] += 1
            else:
                needs[text] += 1
        for quote in analysis.get("evidence_quotes") or []:
            quotes.setdefault("evidence_quotes", []).append(str(quote)[:120])
    return {
        "run_id": run_id,
        "top_needs": needs.most_common(limit),
        "top_problems": problems.most_common(limit),
        "sample_quotes": {k: v[:5] for k, v in quotes.items()},
    }


def _import_signals_from_run(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """Convert existing comment analysis rows into unified Signal records (code-only)."""
    from ..insight import storage as run_storage

    run_id = str(args["run_id"])
    limit = int(args.get("limit", 200))
    try:
        run_storage.load_config(run_id)
    except FileNotFoundError:
        raise ValueError(f"run 不存在: {run_id}")
    _existing = {"v": None}

    def existing_ids():
        if _existing["v"] is None:
            _existing["v"] = {s.signal_id for s in store.list_signals(ctx.product_id)}
        return _existing["v"]

    created: List[str] = []
    skipped = 0
    for row in run_storage.iter_results(run_id, limit=limit):
        src = (row or {}).get("source") or {}
        analysis = (row or {}).get("analysis") or {}
        needs = analysis.get("potential_needs") or []
        problems = analysis.get("specific_problems") or []
        # evidence_items_v1 回退：结构化字段为空时取 new_signals 文本
        new_signals = [s for s in (analysis.get("new_signals") or []) if isinstance(s, dict)]
        new_texts = [str(s.get("text") or "").strip() for s in new_signals]
        new_texts = [t for t in new_texts if t]
        if not needs and not problems and not new_texts:
            continue
        rid = str(src.get("internal_record_id") or analysis.get("record_id") or uuid.uuid4())
        signal_id = f"{run_id}:{rid}"
        if signal_id in existing_ids():
            skipped += 1
            continue  # 幂等：重复导入不产生重复信号
        existing_ids().add(signal_id)
        need_text = (needs or problems or new_texts)[0][:200]
        sig = Signal(
            signal_id=signal_id,
            product_id=ctx.product_id,
            source_type="external_comment",
            source_platform=str(src.get("platform") or "unknown"),
            dataset_ref=run_id,
            evidence_refs=[rid],  # 原始记录可追溯
            collected_at=utc_now_iso(),
            signal_type=str(analysis.get("primary_intent") or ""),
            need_or_problem=need_text,
            ai_classification={
                "signals": analysis.get("signals") or [],
                "confidence": analysis.get("confidence") or 0.0,
                "needs": needs[:5],
                "problems": problems[:5],
                "new_signals": new_signals[:5],
                "evidence_quotes": [str(q)[:200] for q in (analysis.get("evidence_quotes") or [])][:5],
            },
            confidence=float(analysis.get("confidence") or 0.0),
            evidence_quality="high",
            usage_rights="internal_only",  # 外部评论原文默认不外发
        )
        created.append(sig.signal_id)
        store.add_signals([sig])
    if created:
        store.record_import_batch(ctx.product_id, {
            "kind": "signals_from_run",
            "source": f"analysis_run:{run_id}",
            "count": len(created),
            "data_nature": "real",  # 来自真实采集评论
            "note": "外部公开评论的需求信号；非本产品站内行为数据",
        })
    return {"imported": len(created), "skipped_duplicates": skipped, "signal_ids": created[:20]}


def _signal_dataset_summary(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """代码级清单：库里有哪些数据集、各多少条——先看全景再定向深入，避免盲翻。"""
    counter: Counter = Counter()
    kinds: Counter = Counter()
    for s in store.list_signals(ctx.product_id):
        counter[s.dataset_ref or "(unknown)"] += 1
        kinds[s.signal_type or "(untyped)"] += 1
    return {
        "total": sum(counter.values()),
        "datasets": [{"dataset_ref": k, "count": v} for k, v in counter.most_common()],
        "signal_types": dict(kinds),
        "note": "用 query_signals(keyword=...) 或按 dataset_ref 定向深入某个数据集",
    }


def _query_signals(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    signals = store.list_signals(ctx.product_id)
    source_type = (args.get("source_type") or "").strip()
    keyword = (args.get("keyword") or "").strip()
    out = []
    dataset_ref = (args.get("dataset_ref") or "").strip()
    for s in signals:
        if source_type and s.source_type != source_type:
            continue
        if dataset_ref and s.dataset_ref != dataset_ref:
            continue
        if keyword and keyword not in (s.need_or_problem + s.signal_type):
            continue
        out.append(s.model_dump())
    limit = int(args.get("limit", 50))
    return {"total": len(out), "signals": out[:limit]}


def _query_assets(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    assets = [a.model_dump() for a in store.list_assets(ctx.product_id)]
    topic = (args.get("topic") or "").strip()
    if topic:
        assets = [a for a in assets if topic in (a.get("title", "") + "".join(a.get("topics", [])) + a.get("summary", ""))]
    return {"total": len(assets), "assets": assets[: int(args.get("limit", 50))]}


def _upsert_asset(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    asset = ContentAsset.model_validate({**args, "product_id": ctx.product_id, "created_at": utc_now_iso()})
    store.upsert_asset(asset)
    return {"asset_id": asset.asset_id, "license_status": asset.license_status}


def _match_assets_to_needs(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """Deterministic matching; AI adds interpretation on top of these facts."""
    signals = store.list_signals(ctx.product_id)
    assets = store.list_assets(ctx.product_id)
    need_counter: Counter = Counter()
    for s in signals:
        if s.need_or_problem:
            need_counter[s.need_or_problem] += 1
    matches = []
    for need, count in need_counter.most_common(int(args.get("limit", 10))):
        related = [
            a.asset_id
            for a in assets
            if any(tok and tok in need for tok in (a.topics + [a.title]))
            and a.license_status in {"owned", "licensed"}
        ]
        blocked = [
            a.asset_id
            for a in assets
            if any(tok and tok in need for tok in (a.topics + [a.title]))
            and a.license_status not in {"owned", "licensed"}
        ]
        matches.append({"need": need, "signal_count": count,
                        "usable_assets": related, "blocked_unlicensed": blocked})
    return {"matches": matches, "note": "blocked_unlicensed 素材禁止对外使用"}


def _create_opportunity(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    payload = {
        **args,
        "product_id": ctx.product_id,
        "opportunity_id": args.get("opportunity_id") or f"op_{uuid.uuid4().hex[:8]}",
        "created_by": "agent",
        "created_at": utc_now_iso(),
    }
    # 两种模式清晰区分：有可用素材 = asset_ready；无 = demand_first（待制作，
    # 必须写 production_need，不得声称可直接发布）
    usable = payload.get("usable_assets") or []
    if usable:
        payload["opportunity_kind"] = "asset_ready"
        assets = {a.asset_id: a for a in store.list_assets(ctx.product_id)}
        unlicensed = [aid for aid in usable
                      if aid in assets and assets[aid].license_status.value not in {"owned", "licensed"}]
        if unlicensed:
            raise ToolDenied(f"机会引用了未授权素材: {unlicensed}")
    else:
        payload["opportunity_kind"] = "demand_first"
        if not str(payload.get("production_need") or "").strip():
            raise ValueError("无可用素材的机会必须填写 production_need（应制作什么）")
        if payload.get("verdict") == "recommend":
            payload["verdict"] = "hold"  # 待制作机会不直接 recommend 发布
    payload["created_by_session"] = ctx.session_id
    payload["data_nature"] = _ctx_data_nature(ctx)
    key = _normalize_dedupe_key(str(payload.get("problem") or ""))
    for existing in store.list_opportunities(ctx.product_id):
        if _normalize_dedupe_key(existing.problem) == key and key:
            return {"opportunity_id": existing.opportunity_id, "verdict": existing.verdict,
                    "opportunity_kind": existing.opportunity_kind, "deduped": True,
                    "note": "相同问题的机会已存在，复用而非重复创建；如需不同内容版本请在任务书层区分"}
    opp = GrowthOpportunity.model_validate(payload)
    store.upsert_opportunity(opp)
    return {"opportunity_id": opp.opportunity_id, "verdict": opp.verdict,
            "opportunity_kind": opp.opportunity_kind, "deduped": False}


def _create_experiment(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    brief_id = str(args.get("brief_id") or "")
    if brief_id:
        briefs = {b.brief_id: b for b in store.list_briefs(ctx.product_id)}
        brief = briefs.get(brief_id)
        if brief is None:
            raise ValueError(f"任务书不存在: {brief_id}")
        if brief.status != "approved":
            raise ToolDenied(f"任务书 {brief_id} 未获人工批准，不能建立实验")
    exp = GrowthExperiment.model_validate({
        **args,
        "product_id": ctx.product_id,
        "experiment_id": args.get("experiment_id") or f"exp_{uuid.uuid4().hex[:8]}",
    })
    store.upsert_experiment(exp)
    return {"experiment_id": exp.experiment_id, "status": exp.status}


def _compute_experiment_metrics(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    exp_id = str(args.get("experiment_id") or "")
    obs = store.list_observations(ctx.product_id, experiment_id=exp_id)
    by_kind: Dict[str, Dict[str, float]] = {}
    for o in obs:
        by_kind.setdefault(o.metric_kind.value, {})[o.name] = by_kind.get(o.metric_kind.value, {}).get(o.name, 0.0) + o.value
    product = store.get_product_or_raise(ctx.product_id)
    return {
        "experiment_id": exp_id,
        "metrics_by_kind": by_kind,
        "observation_count": len(obs),
        "attribution_capability": product.attribution_capability,
        "note": "attribution_capability=none 时，站内转化不可验证，禁止推断注册/CAC",
    }


def _record_learning(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    payload = {
        **args,
        "product_id": ctx.product_id,
        "learning_id": args.get("learning_id") or f"l_{uuid.uuid4().hex[:8]}",
        "created_at": utc_now_iso(),
        "created_by_session": ctx.session_id,
    }
    if ctx.mock:
        payload["data_nature"] = "mock"
    else:
        payload["data_nature"] = _ctx_data_nature(ctx)
    rec = LearningRecord.model_validate(payload)
    store.upsert_learning(rec)
    return {"learning_id": rec.learning_id}


def _recall_learnings(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    recs = [r.model_dump() for r in store.list_learnings(ctx.product_id)]
    if not args.get("include_mock"):
        recs = [r for r in recs if r.get("data_nature", "real") != "mock"]
    keyword = (args.get("keyword") or "").strip()
    if keyword:
        recs = [r for r in recs if keyword in (r.get("what_tested", "") + r.get("outcome", ""))]
    return {"total": len(recs), "learnings": recs[-int(args.get("limit", 20)):]}


# --- Phase 3 handlers --------------------------------------------------------


def _import_assets(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """批量导入素材（CSV/JSON 已在 API 层转为 dict 列表）。授权缺失一律 unknown，禁止对外使用。"""
    items = args.get("assets") or []
    if not isinstance(items, list) or not items:
        raise ValueError("assets 必须是非空列表")
    created, updated = [], []
    existing = {a.asset_id for a in store.list_assets(ctx.product_id)}
    for raw in items[:500]:
        if not isinstance(raw, dict) or not raw.get("asset_id") or not raw.get("title"):
            raise ValueError("每条素材必须包含 asset_id 与 title")
        payload = {**raw, "product_id": ctx.product_id}
        payload.setdefault("license_status", "unknown")
        asset = ContentAsset.model_validate(payload)
        if asset.asset_id in existing:
            updated.append(asset.asset_id)
        else:
            created.append(asset.asset_id)
        store.upsert_asset(asset)
    if created:
        store.record_import_batch(ctx.product_id, {
            "kind": "assets",
            "source": str(args.get("source_label") or "manual_or_crawl"),
            "count": len(created),
            "data_nature": str(args.get("data_nature") or "unknown"),
            "note": str(args.get("note") or ""),
        })
    return {"created": len(created), "updated": len(updated),
            "note": "license_status=unknown 的素材禁止对外使用，需人工确认授权"}


def _create_content_brief(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """生成内容任务书（草稿）。强制校验素材存在且已授权。"""
    asset_ids = list(args.get("asset_ids") or [])
    assets = {a.asset_id: a for a in store.list_assets(ctx.product_id)}
    missing = [aid for aid in asset_ids if aid not in assets]
    if missing:
        raise ValueError(f"素材不存在: {missing}（禁止虚构素材）")
    unlicensed = [aid for aid in asset_ids if assets[aid].license_status not in {"owned", "licensed"}]
    if unlicensed:
        raise ToolDenied(f"素材未确认授权，禁止用于对外内容: {unlicensed}")
    if not asset_ids:
        # 任务书是 asset_first 产物；demand_first 请用 create_opportunity(production_need=...)
        raise ValueError("任务书必须引用至少一份已授权素材；无素材的需求请创建 demand_first 机会")
    brief_key = _normalize_dedupe_key(str(args.get("title") or "") + str(args.get("problem") or ""))
    for existing in store.list_briefs(ctx.product_id):
        if _normalize_dedupe_key(existing.title + existing.problem) == brief_key and brief_key:
            return {"brief_id": existing.brief_id, "status": existing.status, "deduped": True,
                    "note": "相同主题的任务书已存在，复用而非重复创建"}
    brief = ContentBrief.model_validate({
        **args,
        "product_id": ctx.product_id,
        "brief_id": args.get("brief_id") or f"br_{uuid.uuid4().hex[:8]}",
        "status": "draft",
        "created_by": "agent",
        "created_by_session": ctx.session_id,
        "data_nature": _ctx_data_nature(ctx),
    })
    store.upsert_brief(brief)
    return {"brief_id": brief.brief_id, "status": "draft", "deduped": False,
            "note": "任务书为草稿，需人工批准后才能建实验/分发"}


_REACH_NAMES = {"views", "impressions", "completion", "likes", "favorites", "comments",
                "曝光", "播放", "完播", "点赞", "收藏", "评论"}
_TRAFFIC_NAMES = {"tracked_clicks", "valid_visits", "点击", "到站", "有效访问"}
_PRODUCT_NAMES = {"signups", "first_action", "retention", "注册", "首次核心行为", "留存"}
_EFFICIENCY_NAMES = {"production_cost", "cac", "制作成本", "获客成本"}


def _classify_metric(name: str) -> MetricKind:
    n = name.strip().lower()
    if n in {x.lower() for x in _TRAFFIC_NAMES}:
        return MetricKind.TRAFFIC
    if n in {x.lower() for x in _PRODUCT_NAMES}:
        return MetricKind.PRODUCT
    if n in {x.lower() for x in _EFFICIENCY_NAMES}:
        return MetricKind.EFFICIENCY
    return MetricKind.REACH


def _record_publish_results(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """登记一条发布记录及其指标。未获取的指标必须 value=None（Unknown），不得填 0。"""
    experiment_id = str(args["experiment_id"])
    experiments = {e.experiment_id: e for e in store.list_experiments(ctx.product_id)}
    if experiment_id not in experiments:
        raise ValueError(f"实验不存在: {experiment_id}")
    exp = experiments[experiment_id]
    pub = PublishRecord(
        channel=str(args.get("channel") or ""),
        account=str(args.get("account") or ""),
        url=str(args.get("url") or ""),
        published_at=str(args.get("published_at") or ""),
        variant_id=str(args.get("variant_id") or ""),
    )
    exp.publish_records.append(pub)
    if exp.status.value == "planned":
        from .models import ExperimentStatus

        exp.status = ExperimentStatus.RUNNING
    store.upsert_experiment(exp)

    metrics = args.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise ValueError("metrics 必须是 {指标名: 数值或 null} 的对象")
    period_start = str(args.get("period_start") or "")
    period_end = str(args.get("period_end") or "")
    stats_method = str(args.get("stats_method") or "")
    attribution_note = str(args.get("attribution_note") or "")
    obs_list = []
    for name, value in metrics.items():
        obs_list.append(MetricsObservation(
            observation_id=f"ob_{uuid.uuid4().hex[:10]}",
            product_id=ctx.product_id,
            experiment_id=experiment_id,
            metric_kind=_classify_metric(str(name)),
            name=str(name),
            value=None if value is None else float(value),  # None = Unknown
            channel=pub.channel,
            source=str(args.get("source") or "manual_import"),
            period_start=period_start,
            period_end=period_end,
            stats_method=stats_method,
            attribution_note=attribution_note,
            verified=bool(args.get("verified", False)),
            collected_at=utc_now_iso(),
        ))
    store.add_observations(obs_list)
    return {"experiment_id": experiment_id, "metrics_recorded": len(obs_list),
            "unknown_metrics": [o.name for o in obs_list if o.value is None]}


def _review_experiments(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """代码级事实汇总（不按播放量排名，排序与判断交给 AI）。

    只产出可核算事实：每个实验的传播/导流/产品指标、Unknown 列表、
    归因能力、样本标记；是否停止/继续由模型结合档案判断。
    """
    product = store.get_product_or_raise(ctx.product_id)
    experiments = store.list_experiments(ctx.product_id)
    if args.get("experiment_id"):
        experiments = [e for e in experiments if e.experiment_id == args["experiment_id"]]
    learnings_n = len(store.list_learnings(ctx.product_id))
    out = []
    for exp in experiments:
        obs = store.list_observations(ctx.product_id, experiment_id=exp.experiment_id)
        known: Dict[str, Dict[str, float]] = {}
        unknown: List[str] = []
        for o in obs:
            if o.value is None:
                unknown.append(o.name)
                continue
            kind = known.setdefault(o.metric_kind.value, {})
            kind[o.name] = round(kind.get(o.name, 0.0) + float(o.value), 4)
        views = known.get("reach", {}).get("views")
        visits = known.get("traffic", {}).get("valid_visits")
        ratio = round(visits / views, 6) if (views and visits is not None) else None
        sample_flag = "small_sample" if (views is not None and views < 1000) else "ok"
        structured = {
            "experiment_id": exp.experiment_id,
            "status": exp.status.value,
            "hypothesis": exp.hypothesis,
            "channels": exp.channels,
            "published": len(exp.publish_records),
            "metrics_known": known,
            "metrics_unknown": sorted(set(unknown)),
            "visit_per_view": ratio,  # 导流效率（仅两者都有数时）
            "sample_flag": sample_flag,
            "comparison_notes": exp.comparison_notes,
        }
        out.append(structured)
    return {
        "experiments": out,
        "attribution_capability": product.attribution_capability.value,
        "attribution_warning": (
            "当前产品站内转化不可验证：禁止声称验证了拉新/注册/CAC"
            if product.attribution_capability.value == "none" else ""
        ),
        "historical_learnings": learnings_n,
        "note": "仅输出可核算事实；是否停止/继续/调整由你结合假设与证据质量判断，并记录为 learning",
    }


def _create_segment_report(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """潜在用户研究报告（L1）。确定性校验：
    - certainty=evidenced 的分段必须有可解析的 evidence_refs；
    - 推测渠道必须填 hypothesized_channels，不得塞进 platforms；
    - 必须写 data_limitations（数据边界）。
    """
    if not str(args.get("data_limitations") or "").strip():
        raise ValueError("必须填写 data_limitations：当前数据能证明什么、不能证明什么")
    signal_ids = {s.signal_id for s in store.list_signals(ctx.product_id)}
    warned: List[str] = []
    for seg in args.get("segments") or []:
        if not isinstance(seg, dict):
            raise ValueError("segments 必须为对象列表")
        refs = seg.get("evidence_refs") or []
        unresolved = [r for r in refs if r not in signal_ids]
        if unresolved:
            # 软处理而非硬拒绝：丢弃不可解析的引用，该分段强制降为 unverified。
            # 证据完整性规则不变：evidenced 必须全部可解析；不可解析 ≠ 伪造证据通过。
            seg["evidence_refs"] = [r for r in refs if r in signal_ids]
            seg["certainty"] = "unverified"
            warned.append(f"分段「{seg.get('name', '?')}」有 {len(unresolved)} 条引用无法解析，已降级为 unverified")
        if seg.get("certainty") == "evidenced" and not seg.get("evidence_refs"):
            seg["certainty"] = "unverified"
            warned.append(f"分段「{seg.get('name', '?')}」无有效证据引用，已降级为 unverified")
    report = UserSegmentReport.model_validate({
        **args,
        "product_id": ctx.product_id,
        "report_id": args.get("report_id") or f"sr_{uuid.uuid4().hex[:8]}",
        "created_by": "agent",
        "created_by_session": ctx.session_id,
        "data_nature": _ctx_data_nature(ctx),
    })
    store.upsert_segment_report(report)
    return {"report_id": report.report_id, "segments": len(report.segments),
            "warnings": warned,
            "note": "报告不代表已确认的目标用户画像；certainty 低的群体需先补数据"}


def _query_segments(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    reports = [r.model_dump() for r in store.list_segment_reports(ctx.product_id)]
    return {"total": len(reports), "reports": reports[-int(args.get("limit", 5)):]}


def _crawl_external(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    # L2：新增外部数据采集。本次仅登记任务，不自动执行爬虫。
    return {
        "accepted": True,
        "note": "采集需求已登记。若目标是单个 B 站视频，请改用 crawl_bilibili_comments（同样需 L2 授权）。",
        "args": args,
    }


def _crawl_bilibili_comments(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    """L2 受控小规模采集：单个 B 站视频评论（节奏受控、不绕登录）。"""
    from .crawl_tool import run_bilibili_comment_crawl

    result = run_bilibili_comment_crawl(
        ctx.product_id,
        target=str(args.get("video") or ""),
        max_comments=int(args.get("max_comments") or 50),
        reason=str(args.get("reason") or ""),
    )
    status = result.get("status")
    if status == "login_required":
        raise ToolDenied(result["message"])
    if status != "ok":
        raise ValueError(result.get("message", "采集失败"))
    return result


def _send_external_reply(ctx: ToolContext, args: Dict[str, Any]) -> Any:
    # L3：对外触达。Agent 永远不获得此工具的授权（见 registry 注册 perms=L3）。
    raise ToolDenied("对外发送必须走现有回复审核面板并人工逐条批准")


# --- registry ----------------------------------------------------------------


def _spec(name, description, properties, required=(), permission=L1, max_calls=3, timeout=30):
    return ToolSpec(
        name=name,
        description=description,
        args_schema={"type": "object", "properties": properties, "required": list(required)},
        permission=permission,
        max_calls_per_session=max_calls,
        timeout_seconds=timeout,
    )


def build_registry() -> Dict[str, tuple[ToolSpec, Callable]]:
    reg: Dict[str, tuple[ToolSpec, Callable]] = {}

    def reg_tool(spec, fn):
        reg[spec.name] = (spec, fn)

    reg_tool(_spec("list_analysis_runs", "列出已有评论分析任务（run），了解可用数据", {}), _list_analysis_runs)
    reg_tool(_spec("get_run_summary", "查看某个 run 的规模、项目与产物摘要",
                   {"run_id": {"type": "string"}}, ("run_id",)), _get_run_summary)
    reg_tool(_spec("get_run_top_needs", "代码级聚合某 run 的高频需求/问题与证据引用（不耗模型）",
                   {"run_id": {"type": "string"}, "limit": {"type": "integer"}}, ("run_id",)), _get_run_top_needs)
    reg_tool(_spec("import_signals_from_run", "把某 run 的分析结果转换为统一用户信号（限内部使用）",
                   {"run_id": {"type": "string"}, "limit": {"type": "integer"}}, ("run_id",),
                   max_calls=2, timeout=120), _import_signals_from_run)
    reg_tool(_spec("signal_dataset_summary", "数据全景：库里有哪些数据集/各多少条信号（零成本，建议调研第一步）",
                   {}, (), max_calls=2), _signal_dataset_summary)
    reg_tool(_spec("query_signals", "检索本产品的统一用户信号（支持 keyword 和 dataset_ref 过滤）",
                   {"source_type": {"type": "string"}, "keyword": {"type": "string"},
                    "dataset_ref": {"type": "string"}, "limit": {"type": "integer"}}, max_calls=10), _query_signals)
    reg_tool(_spec("query_assets", "检索内容资产库（含授权状态）",
                   {"topic": {"type": "string"}, "limit": {"type": "integer"}}), _query_assets)
    reg_tool(_spec("upsert_asset", "登记/更新一条内容资产（含授权状态 license_status）",
                   {"asset_id": {"type": "string"}, "title": {"type": "string"},
                    "summary": {"type": "string"}, "uri": {"type": "string"},
                    "asset_type": {"type": "string"}, "topics": {"type": "array", "items": {"type": "string"}},
                    "license_status": {"type": "string", "enum": ["owned", "licensed", "unknown"]}},
                   ("asset_id", "title")), _upsert_asset)
    reg_tool(_spec("match_assets_to_needs", "把高频需求与可用素材做确定性匹配，并标出未授权素材",
                   {"limit": {"type": "integer"}}), _match_assets_to_needs)
    reg_tool(_spec("create_opportunity", "登记一条增长机会（必须给出 verdict_rationale，不得只有分数）",
                   {"target_segment": {"type": "string"}, "problem": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "linked_value": {"type": "string"}, "growth_mechanism": {"type": "string"},
                    "production_need": {"type": "string"},
                    "usable_assets": {"type": "array", "items": {"type": "string"}},
                    "recommended_action": {"type": "string"}, "risks": {"type": "array", "items": {"type": "string"}},
                    "verdict": {"type": "string", "enum": ["recommend", "hold", "reject", "needs_data"]},
                    "verdict_rationale": {"type": "string"}, "confidence": {"type": "number"},
                    "uncertainty_level": {"type": "string", "enum": ["fact", "inference", "hypothesis", "guess"]},
                    "metrics_to_verify": {"type": "array", "items": {"type": "string"}}},
                   ("problem", "verdict", "verdict_rationale")), _create_opportunity)
    reg_tool(_spec("create_experiment", "登记一个增长实验（假设/素材/渠道/目标指标）",
                   {"opportunity_id": {"type": "string"}, "brief_id": {"type": "string"},
                    "goal": {"type": "string"},
                    "audience": {"type": "string"}, "hypothesis": {"type": "string"},
                    "asset_ids": {"type": "array", "items": {"type": "string"}},
                    "channels": {"type": "array", "items": {"type": "string"}},
                    "target_metrics": {"type": "array", "items": {"type": "string"}},
                    "attribution_limits": {"type": "string"}},
                   ("goal", "hypothesis")), _create_experiment)
    reg_tool(_spec("compute_experiment_metrics", "汇总某实验的指标观察（区分传播/导流/产品/效率）",
                   {"experiment_id": {"type": "string"}}), _compute_experiment_metrics)
    reg_tool(_spec("record_learning", "写入结构化增长经验或记录人工反馈原因",
                   {"experiment_id": {"type": "string"}, "what_tested": {"type": "string"},
                    "outcome": {"type": "string"}, "evidence_strength": {"type": "string"},
                    "next_adjustments": {"type": "array", "items": {"type": "string"}},
                    "human_feedback": {"type": "object"}},
                   ("what_tested",), max_calls=5), _record_learning)
    reg_tool(_spec("create_segment_report", "登记潜在用户研究报告（找用户类目标的产出物，区别于内容机会）。"
                   "segments 每项需含: name, core_needs[], evidence_refs[](必须是已存在的 signal_id), "
                   "platforms[](仅数据证实的平台), product_fit(matched/weak/mismatch), product_fit_reason, "
                   "reach_methods[], hypothesized_channels[](仅为推测渠道), certainty(evidenced/inferred/unverified)",
                   {"goal": {"type": "string"},
                    "segments": {"type": "array", "items": {"type": "object"}},
                    "data_limitations": {"type": "string"},
                    "recommended_next": {"type": "array", "items": {"type": "string"}},
                    "not_recommended": {"type": "array", "items": {"type": "string"}}},
                   ("goal", "segments", "data_limitations"), max_calls=3), _create_segment_report)
    reg_tool(_spec("query_segments", "查看已有潜在用户研究报告",
                   {"limit": {"type": "integer"}}), _query_segments)
    reg_tool(_spec("recall_learnings", "检索历史经验与人工反馈（默认排除 mock 演示记录）",
                   {"keyword": {"type": "string"}, "limit": {"type": "integer"},
                    "include_mock": {"type": "boolean"}}), _recall_learnings)
    reg_tool(_spec("import_assets", "批量导入内容素材（JSON 列表）。授权缺失自动标 unknown",
                   {"assets": {"type": "array", "items": {"type": "object"}},
                    "source_label": {"type": "string"},
                    "data_nature": {"type": "string", "enum": ["real", "demo", "unknown"]},
                    "note": {"type": "string"}}, ("assets",),
                   max_calls=3, timeout=60), _import_assets)
    reg_tool(_spec("create_content_brief", "生成内容任务书草稿（须引用真实已授权素材；草稿需人工批准）",
                   {"title": {"type": "string"}, "audience": {"type": "string"},
                    "problem": {"type": "string"},
                    "asset_ids": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "channels": {"type": "array", "items": {"type": "string"}},
                    "hook": {"type": "string"},
                    "value_props": {"type": "array", "items": {"type": "string"}},
                    "visit_reason": {"type": "string"},
                    "review_requirements": {"type": "string"},
                    "validation_metrics": {"type": "array", "items": {"type": "string"}},
                    "opportunity_id": {"type": "string"}, "priority": {"type": "integer"}},
                   ("title", "problem", "rationale", "hook", "visit_reason"), max_calls=5),
             _create_content_brief)
    reg_tool(_spec("record_publish_results", "登记一条发布记录与指标（未获取的指标填 null=Unknown，禁止填 0）",
                   {"experiment_id": {"type": "string"}, "channel": {"type": "string"},
                    "account": {"type": "string"}, "url": {"type": "string"},
                    "published_at": {"type": "string"},
                    "metrics": {"type": "object"},
                    "period_start": {"type": "string"}, "period_end": {"type": "string"},
                    "stats_method": {"type": "string"}, "attribution_note": {"type": "string"},
                    "source": {"type": "string"}, "verified": {"type": "boolean"}},
                   ("experiment_id", "channel", "metrics"), max_calls=10, timeout=60),
             _record_publish_results)
    reg_tool(_spec("review_experiments", "实验复盘：代码级事实汇总（传播/导流/产品分层 + Unknown 标记 + 归因警告）",
                   {"experiment_id": {"type": "string"}}, (), max_calls=3, timeout=60),
             _review_experiments)
    reg_tool(_spec("crawl_external", "【需任务授权】登记未来采集需求（只是登记，不执行）",
                   {"platform": {"type": "string"}, "target": {"type": "string"}, "reason": {"type": "string"}},
                   ("platform", "target"), permission=L2), _crawl_external)
    reg_tool(_spec("crawl_bilibili_comments", "【需任务授权】采集单个 B 站视频的评论（小規模：默认 50 条、硬顶 100、受频率控制；评论作为 raw 信号导入）",
                   {"video": {"type": "string"},
                    "max_comments": {"type": "integer"},
                    "reason": {"type": "string"}},
                   ("video", "reason"), permission=L2, max_calls=1, timeout=360),
             _crawl_bilibili_comments)
    reg_tool(_spec("send_external_reply", "【人工专属】对外发送评论/私信 —— Agent 不可调用",
                   {"to": {"type": "string"}, "content": {"type": "string"}},
                   ("to", "content"), permission=L3, max_calls=0), _send_external_reply)
    return reg


REGISTRY = build_registry()


def validate_args(spec: ToolSpec, args: Dict[str, Any]) -> Optional[str]:
    if not isinstance(args, dict):
        return "参数必须是 JSON 对象"
    for key in spec.args_schema.get("required", []):
        if key not in args or args[key] in (None, ""):
            return f"缺少必填参数: {key}"
    return None


def execute_tool(name: str, args: Dict[str, Any], ctx: ToolContext, call_counts: Dict[str, int]) -> ToolResult:
    entry = REGISTRY.get(name)
    if entry is None:
        return ToolResult(status="error", error=f"未知工具: {name}")
    spec, handler = entry

    status, error = "ok", ""
    detail = ""
    # permission gate —— 模型无法绕过
    if spec.permission == L3:
        status, error = "denied", "L3 操作必须人工在对应面板批准，Agent 无权执行"
    elif spec.permission == L2 and name not in ctx.l2_grants:
        status, error = "denied", f"需要本次任务的 L2 授权（授权范围不含 {name}）"
    elif call_counts.get(name, 0) >= spec.max_calls_per_session:
        status, error = "denied", (f"安全上限：该工具本会话最多查 {spec.max_calls_per_session} 次（防重复烧钱）。"
                                   "请基于已获得的信息给出结论，或换其他工具/参数。")
    else:
        err = validate_args(spec, args)
        if err:
            status, error = "error", err
        else:
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(handler, ctx, args)
                    data = fut.result(timeout=spec.timeout_seconds)
                call_counts[name] = call_counts.get(name, 0) + 1
                _audit(ctx, name, args, "L1" if spec.permission == L1 else spec.permission, "ok",
                       output_refs=_extract_refs(data))
                return ToolResult(status="ok", data=data)
            except FuturesTimeout:
                status, error = "error", f"工具超时（>{spec.timeout_seconds}s）"
            except ToolDenied as exc:
                status, error = "denied", str(exc)
            except Exception as exc:  # safe exit, keep partial results
                status, error = "error", f"{type(exc).__name__}: {exc}"
    detail = error
    _audit(ctx, name, args, spec.permission, status, detail=detail)
    return ToolResult(status=status, error=error)


def _extract_refs(data: Any) -> List[str]:
    refs: List[str] = []
    if isinstance(data, dict):
        for key in ("opportunity_id", "experiment_id", "learning_id", "asset_id", "brief_id"):
            if key in data and isinstance(data[key], str):
                refs.append(data[key])
        for key in ("signal_ids",):
            for v in data.get(key) or []:
                refs.append(str(v))
    return refs[:20]


def _audit(ctx: ToolContext, action: str, args: Dict[str, Any], permission: str, status: str,
           detail: str = "", output_refs: Optional[List[str]] = None) -> None:
    summary = {k: (str(v)[:120]) for k, v in (args or {}).items()}
    store.record_audit(AuditRecord(
        audit_id=f"au_{uuid.uuid4().hex[:10]}",
        product_id=ctx.product_id,
        session_id=ctx.session_id,
        actor="agent",
        action=action,
        input_summary=str(summary)[:400],
        output_refs=output_refs or [],
        permission_level=permission,
        status=status,
        detail=detail[:200],
        created_at=utc_now_iso(),
    ))
