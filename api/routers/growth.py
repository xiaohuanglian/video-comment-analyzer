# -*- coding: utf-8 -*-
"""Growth Engine REST API (Phase 1 store + Phase 2 orchestrator entry)."""

from __future__ import annotations

import csv
import io
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.growth import demo_data, seeds, store
from ..services.growth.models import (
    BriefStatus,
    ContentAsset,
    ContentBrief,
    GrowthExperiment,
    GrowthOpportunity,
    LearningRecord,
    MetricsObservation,
    ProductProfile,
    Signal,
)
from ..services.growth.orchestrator import (
    Orchestrator,
    SessionConfig,
    get_orchestrator,
    list_sessions,
    load_session,
)

router = APIRouter(prefix="/growth", tags=["growth"])


# --- products ----------------------------------------------------------------


@router.get("/products")
def get_products() -> Dict[str, Any]:
    products = {p.product_id: p for p in store.list_products()}
    for pid, seed in seeds.BUILTIN_PRODUCTS.items():
        products.setdefault(pid, seed)
    return {"products": [p.model_dump() for p in sorted(products.values(), key=lambda p: p.product_id)]}


@router.post("/products")
def post_product(profile: ProductProfile) -> Dict[str, Any]:
    try:
        saved = store.upsert_product(profile.model_copy(update={"is_builtin": False}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return saved.model_dump()


@router.post("/products/seed")
def post_seed_products() -> Dict[str, Any]:
    created = []
    for seed in seeds.BUILTIN_PRODUCTS.values():
        if store.get_product(seed.product_id) is None:
            store.upsert_product(seed.model_copy(update={"is_builtin": False}))
            created.append(seed.product_id)
    return {"created": created}


def _require_product(product_id: str) -> None:
    if store.get_product(product_id) is None and product_id in seeds.BUILTIN_PRODUCTS:
        store.upsert_product(seeds.BUILTIN_PRODUCTS[product_id].model_copy(update={"is_builtin": False}))
    elif store.get_product(product_id) is None:
        raise HTTPException(status_code=404, detail=f"产品不存在: {product_id}")


# --- domain data -------------------------------------------------------------


@router.get("/products/{product_id}/signals")
def get_signals(product_id: str, limit: int = 100) -> Dict[str, Any]:
    _require_product(product_id)
    return {"signals": [s.model_dump() for s in store.list_signals(product_id, limit=limit)]}


@router.post("/products/{product_id}/signals")
def post_signals(product_id: str, signals: List[Signal]) -> Dict[str, Any]:
    _require_product(product_id)
    for s in signals:
        if s.product_id != product_id:
            raise HTTPException(status_code=400, detail="signal.product_id 与路径不一致")
    return {"imported": store.add_signals(signals)}


@router.get("/products/{product_id}/assets")
def get_assets(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"assets": [a.model_dump() for a in store.list_assets(product_id)]}


@router.post("/products/{product_id}/assets")
def post_asset(product_id: str, asset: ContentAsset) -> Dict[str, Any]:
    _require_product(product_id)
    if asset.product_id != product_id:
        raise HTTPException(status_code=400, detail="asset.product_id 与路径不一致")
    return store.upsert_asset(asset).model_dump()


@router.get("/products/{product_id}/segments")
def get_segments(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"reports": [r.model_dump() for r in store.list_segment_reports(product_id)]}


@router.get("/products/{product_id}/opportunities")
def get_opportunities(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"opportunities": [o.model_dump() for o in store.list_opportunities(product_id)]}


@router.post("/products/{product_id}/audience/analyze")
def analyze_audience(product_id: str, sync: bool = True) -> Dict[str, Any]:
    """受众智能层（画像×生命周期×AVS）：跑 B 站采集数据的聚类级分析，可选写回引擎。"""
    from api.services.growth import audience

    _require_product(product_id)
    rows, video_map, dataset_ref = audience.load_bili_comments()
    if not rows:
        raise HTTPException(status_code=400, detail="data/comments 下没有采集数据，先跑一轮 B 站采集")
    report = audience.analyze_comments(rows, video_map)
    result: Dict[str, Any] = {"report": report, "dataset_ref": dataset_ref, "total_rows": len(rows)}
    if sync:
        result["sync"] = audience.sync_to_engine(report, product_id, dataset_ref=dataset_ref)
    return result


@router.post("/products/{product_id}/opportunities")
def post_opportunity(product_id: str, opp: GrowthOpportunity) -> Dict[str, Any]:
    _require_product(product_id)
    if opp.product_id != product_id:
        raise HTTPException(status_code=400, detail="opportunity.product_id 与路径不一致")
    return store.upsert_opportunity(opp).model_dump()


@router.get("/products/{product_id}/experiments")
def get_experiments(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"experiments": [e.model_dump() for e in store.list_experiments(product_id)]}


@router.post("/products/{product_id}/experiments")
def post_experiment(product_id: str, exp: GrowthExperiment) -> Dict[str, Any]:
    _require_product(product_id)
    if exp.product_id != product_id:
        raise HTTPException(status_code=400, detail="experiment.product_id 与路径不一致")
    return store.upsert_experiment(exp).model_dump()


@router.post("/products/{product_id}/observations")
def post_observations(product_id: str, observations: List[MetricsObservation]) -> Dict[str, Any]:
    _require_product(product_id)
    for o in observations:
        if o.product_id != product_id:
            raise HTTPException(status_code=400, detail="observation.product_id 与路径不一致")
    return {"imported": store.add_observations(observations)}


@router.get("/products/{product_id}/learnings")
def get_learnings(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"learnings": [r.model_dump() for r in store.list_learnings(product_id)]}


@router.post("/products/{product_id}/learnings")
def post_learning(product_id: str, rec: LearningRecord) -> Dict[str, Any]:
    _require_product(product_id)
    if rec.product_id != product_id:
        raise HTTPException(status_code=400, detail="learning.product_id 与路径不一致")
    return store.upsert_learning(rec).model_dump()


@router.get("/products/{product_id}/audit")
def get_audit(product_id: str, limit: int = 100) -> Dict[str, Any]:
    _require_product(product_id)
    return {"audit": [a.model_dump() for a in store.list_audit(product_id, limit=limit)]}


# --- content briefs（内容任务书：Agent 起草，人工审批） -----------------------


@router.get("/products/{product_id}/briefs")
def get_briefs(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"briefs": [b.model_dump() for b in store.list_briefs(product_id)]}


class BriefReviewRequest(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    note: str = ""


@router.post("/products/{product_id}/briefs/{brief_id}/review")
def post_brief_review(product_id: str, brief_id: str, body: BriefReviewRequest) -> Dict[str, Any]:
    """人工审批入口：只有批准后任务书才能建立增长实验。"""
    _require_product(product_id)
    briefs = {b.brief_id: b for b in store.list_briefs(product_id)}
    brief = briefs.get(brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="任务书不存在")
    brief.status = BriefStatus.APPROVED if body.action == "approve" else BriefStatus.REJECTED
    brief.review_note = body.note
    return store.upsert_brief(brief).model_dump()


# --- assets csv/json 导入 -------------------------------------------------------


class AssetImportRequest(BaseModel):
    assets: Optional[List[Dict[str, Any]]] = None  # JSON 列表
    csv_text: Optional[str] = None  # 或直接粘贴 CSV


@router.post("/products/{product_id}/assets/import")
def post_assets_import(product_id: str, body: AssetImportRequest) -> Dict[str, Any]:
    _require_product(product_id)
    from ..services.growth.tools import ToolContext, execute_tool

    rows = body.assets or []
    if body.csv_text:
        reader = csv.DictReader(io.StringIO(body.csv_text))
        for row in reader:
            cleaned = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if cleaned.get("topics"):
                cleaned["topics"] = [t for t in cleaned["topics"].replace(";", ",").split(",") if t]
            if cleaned.get("published_channels"):
                cleaned["published_channels"] = [
                    t for t in cleaned["published_channels"].replace(";", ",").split(",") if t
                ]
            rows.append(cleaned)
    if not rows:
        raise HTTPException(status_code=400, detail="请提供 assets JSON 或 csv_text")
    result = execute_tool("import_assets", {"assets": rows},
                          ToolContext(product_id=product_id, session_id="api_import"), {})
    if result.status != "ok":
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


class PublishResultRequest(BaseModel):
    experiment_id: str
    channel: str
    account: str = ""
    url: str = ""
    published_at: str = ""
    metrics: Dict[str, Any] = Field(default_factory=dict)  # 未获取的指标不要传，或传 null
    period_start: str = ""
    period_end: str = ""
    stats_method: str = ""
    attribution_note: str = ""
    source: str = "manual_import"
    verified: bool = False


@router.post("/products/{product_id}/tools/record_publish")
def post_record_publish(product_id: str, body: PublishResultRequest) -> Dict[str, Any]:
    """人工登记发布结果（与 Agent 工具同一条安全通道，审计 actor=agent 由工具层区分不了，
    这里 session_id=api_manual 以示人工录入）。"""
    _require_product(product_id)
    from ..services.growth.tools import ToolContext, execute_tool

    result = execute_tool(
        "record_publish_results", body.model_dump(),
        ToolContext(product_id=product_id, session_id="api_manual"), {},
    )
    if result.status != "ok":
        raise HTTPException(status_code=400, detail=result.error)
    return result.data


# --- 演示数据 -------------------------------------------------------------------


@router.post("/demo/seed")
def post_demo_seed() -> Dict[str, Any]:
    """写入明确标记的 DEMO 数据集（youvibe_demo），幂等。"""
    return demo_data.seed_demo_dataset()


@router.get("/products/{product_id}/export")
def get_export(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return store.export_product(product_id)


@router.post("/import")
def post_import(payload: Dict[str, Any], overwrite: bool = False) -> Dict[str, Any]:
    try:
        return store.import_product(payload, overwrite=overwrite)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --- 模型连接设置（服务端持久化） -------------------------------------------------


class ModelSettingsRequest(BaseModel):
    base_url: str = ""
    model_name: str = ""
    api_key: str = ""  # 空 = 保留原有 key


@router.get("/settings/model")
def get_model_settings() -> Dict[str, Any]:
    from ..services.growth import model_settings

    return model_settings.masked_view()


@router.post("/settings/model")
def post_model_settings(body: ModelSettingsRequest) -> Dict[str, Any]:
    from ..services.growth import model_settings

    stored = model_settings.load_model_settings()
    api_key = body.api_key.strip() or stored.get("api_key", "")
    payload = model_settings.save_model_settings(
        body.base_url or stored.get("base_url", ""),
        body.model_name or stored.get("model_name", ""),
        api_key,
    )
    return model_settings.masked_view(payload)


@router.delete("/settings/model")
def delete_model_settings() -> Dict[str, Any]:
    from ..services.growth import model_settings

    model_settings.clear_model_settings()
    return {"ok": True}


@router.post("/settings/model/test")
def post_model_settings_test(body: Optional[ModelSettingsRequest] = None) -> Dict[str, Any]:
    """服务端连接测试：避免浏览器跨域；也顺带验证 function calling 兼容。"""
    from ..services.growth import model_settings
    from ..services.insight.llm_analyzer import build_openai_client

    creds = model_settings.resolve_credentials(
        (body.api_key if body else "") or "",
        (body.base_url if body else "") or "",
        (body.model_name if body else "") or "",
    )
    if not creds["api_key"]:
        return {"ok": False, "error": "未配置 API Key"}
    client = build_openai_client(creds["base_url"] or "https://api.deepseek.com", creds["api_key"])
    import time as _t

    t0 = _t.monotonic()
    try:
        completion = client.chat.completions.create(
            model=creds["model_name"] or "deepseek-v4-flash",
            messages=[{"role": "user", "content": "回复 ok"}],
            max_tokens=8,
            extra_body={"thinking": {"type": "disabled"}},
            timeout=30,
        )
        content = completion.choices[0].message.content or ""
        return {"ok": True, "latency_s": round(_t.monotonic() - t0, 1),
                "model_reply": content[:30], "base_url": creds["base_url"],
                "note": "function calling 兼容性会在首次真实任务时最终确认"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


# --- agent sessions ----------------------------------------------------------


class RunAgentRequest(BaseModel):
    product_id: str
    goal: str = Field(min_length=2)
    api_key: str = ""  # optional; 空则走 mock（明确标注）
    use_mock: bool = True
    base_url: str = ""
    model_name: str = ""
    input_price: float = 0.001
    output_price: float = 0.002
    budget_limit_cny: float = 2.0
    max_iterations: int = Field(default=8, ge=1, le=30)
    l2_grants: List[str] = Field(default_factory=list)


def _resolve_run_credentials(body: RunAgentRequest) -> Dict[str, str]:
    from ..services.growth import model_settings

    return model_settings.resolve_credentials(body.api_key, body.base_url, body.model_name)


@router.post("/agent/run")
def post_agent_run(body: RunAgentRequest) -> Dict[str, Any]:
    _require_product(body.product_id)
    creds = _resolve_run_credentials(body)
    config_kwargs = body.model_dump(exclude={"api_key"})
    config_kwargs["use_mock"] = body.use_mock or not creds["api_key"]
    if creds["base_url"]:
        config_kwargs["base_url"] = creds["base_url"]
    if creds["model_name"]:
        config_kwargs["model_name"] = creds["model_name"]
    config = SessionConfig(**config_kwargs)
    orch = Orchestrator(config, api_key=creds["api_key"])
    session = orch.run()  # 同步执行：受 max_iterations / 预算约束的小任务
    return session.model_dump()


@router.post("/agent/run_async")
def post_agent_run_async(body: RunAgentRequest) -> Dict[str, Any]:
    _require_product(body.product_id)
    creds = _resolve_run_credentials(body)
    config = SessionConfig(**{k: v for k, v in body.model_dump(exclude={"api_key"}).items()})
    config.use_mock = body.use_mock or not creds["api_key"]
    if creds["base_url"]:
        config.base_url = creds["base_url"]
    if creds["model_name"]:
        config.model_name = creds["model_name"]
    orch = Orchestrator(config, api_key=creds["api_key"])
    thread = threading.Thread(target=orch.run, name=f"growth-agent-{orch.session.session_id}", daemon=True)
    thread.start()
    return {"session_id": orch.session.session_id, "status": "running", "mock": config.use_mock}


class FollowupRequest(BaseModel):
    message: str = Field(min_length=2)
    api_key: str = ""
    use_mock: bool = True
    base_url: str = ""
    model_name: str = ""


def _build_followup_context(product_id: str, parent) -> str:
    """压缩上下文：目标、结论、当前相关对象与人工决策——不重复发全量聊天。"""
    opps = store.list_opportunities(product_id)
    briefs = store.list_briefs(product_id)
    my_opps = [o for o in opps if o.created_by_session == parent.session_id][-5:]
    my_briefs = [b for b in briefs if b.created_by_session == parent.session_id][-5:]
    parts = [
        f"原目标: {parent.config.goal}",
        f"上轮结论(截断): {(parent.final_answer or parent.stop_reason or '')[:300]}",
    ]
    if my_opps:
        parts.append("本任务的机会: " + "; ".join(
            f"{o.opportunity_id}「{o.problem[:20]}」状态={o.status}" for o in my_opps))
    if my_briefs:
        parts.append("本任务的任务书: " + "; ".join(
            f"{b.brief_id}「{b.title[:16]}」状态={b.status.value}" for b in my_briefs))
    return "\n".join(parts)


@router.post("/agent/sessions/{session_id}/followup")
def post_agent_followup(product_id: str, session_id: str, body: FollowupRequest) -> Dict[str, Any]:
    """连续对话：围绕同一任务继续工作（复用证据，不重头再来）。"""
    _require_product(product_id)
    parent = load_session(product_id, session_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="父会话不存在")
    from ..services.growth import model_settings

    creds = model_settings.resolve_credentials(body.api_key, body.base_url, body.model_name)
    config = SessionConfig(
        product_id=product_id,
        goal=body.message,
        use_mock=body.use_mock or not creds["api_key"],
        base_url=creds["base_url"] or parent.config.base_url,
        model_name=creds["model_name"] or parent.config.model_name,
        parent_session_id=session_id,
        extra_context=_build_followup_context(product_id, parent),
    )
    orch = Orchestrator(config, api_key=creds["api_key"])
    thread = threading.Thread(target=orch.run, name=f"growth-followup-{orch.session.session_id}", daemon=True)
    thread.start()
    return {"session_id": orch.session.session_id, "parent_session_id": session_id,
            "status": "running", "mock": config.use_mock}


@router.get("/agent/sessions")
def get_agent_sessions(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"sessions": [s.model_dump(exclude={"messages"}) for s in list_sessions(product_id)]}


@router.get("/agent/sessions/{session_id}")
def get_agent_session(product_id: str, session_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    live = get_orchestrator(session_id)
    if live is not None:
        return live.session.model_dump()
    s = load_session(product_id, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return s.model_dump()


@router.get("/agent/sessions/{session_id}/summary")
def get_agent_session_summary(product_id: str, session_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    from ..services.growth.orchestrator import build_session_summary

    return build_session_summary(product_id, session_id)


# --- 质量评估 -------------------------------------------------------------------


class EvalRunRequest(BaseModel):
    use_mock: bool = True
    api_key: str = ""
    base_url: str = ""
    model_name: str = ""
    max_tasks: int = Field(default=10, ge=1, le=10)


@router.post("/products/{product_id}/eval/run")
def post_eval_run(product_id: str, body: EvalRunRequest) -> Dict[str, Any]:
    _require_product(product_id)
    from ..services.growth.evaluate import run_evaluation

    return run_evaluation(
        product_id, use_mock=body.use_mock or not body.api_key,
        api_key=body.api_key, base_url=body.base_url,
        model_name=body.model_name, max_tasks=body.max_tasks,
    )


@router.post("/products/{product_id}/eval/scoresheet")
def post_eval_scoresheet(product_id: str, body: EvalRunRequest) -> Dict[str, Any]:
    _require_product(product_id)
    from ..services.growth.evaluate import export_scoresheet_csv, run_evaluation

    report = run_evaluation(
        product_id, use_mock=body.use_mock or not body.api_key,
        api_key=body.api_key, base_url=body.base_url,
        model_name=body.model_name, max_tasks=body.max_tasks,
    )
    return {"csv": export_scoresheet_csv(report), "mode": report["mode"],
            "auto_check_passed": report["auto_check_passed"]}


@router.get("/products/{product_id}/eval/integrity")
def get_eval_integrity(product_id: str) -> Dict[str, Any]:
    """只跑自动证据校验，不调用模型。"""
    _require_product(product_id)
    from ..services.growth.evaluate import verify_record_integrity

    violations = verify_record_integrity(product_id)
    return {"violations": violations, "passed": len(violations) == 0}


@router.get("/products/{product_id}/import_batches")
def get_import_batches(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"batches": store.list_import_batches(product_id)}


@router.post("/agent/sessions/{session_id}/stop")
def post_agent_stop(product_id: str, session_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    orch = get_orchestrator(session_id)
    if orch is None:
        raise HTTPException(status_code=404, detail="会话不在运行中")
    orch.request_cancel()
    return {"ok": True}


# --- 冻结协议 + 漏斗诊断 + 晋升协议（P0/P1，2026-10-14）-----------------------


@router.post("/products/{product_id}/experiments/{experiment_id}/variants/{variant_id}/freeze")
def post_freeze_prediction(product_id: str, experiment_id: str, variant_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """冻结预测（发布前必须）：创意包 + 区间预测 + 赌注 → payload_hash 盖章，此后不可改。"""
    from api.services.growth import prediction_freeze as pf

    _require_product(product_id)
    try:
        return {"frozen": pf.freeze_predictions(product_id, experiment_id, variant_id, body.get("payload") or {})}
    except pf.FreezeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/products/{product_id}/experiments/{experiment_id}/variants/{variant_id}/bind-published-asset")
def post_bind_asset(product_id: str, experiment_id: str, variant_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """发布时绑定实际资产：creative_asset_hash（成品哈希）+ account_state_version + publish_time。"""
    from api.services.growth import prediction_freeze as pf

    _require_product(product_id)
    try:
        return {"binding": pf.bind_published_asset(product_id, experiment_id, variant_id, body)}
    except pf.FreezeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/products/{product_id}/experiments/{experiment_id}/integrity")
def get_integrity(product_id: str, experiment_id: str) -> Dict[str, Any]:
    """完整性校验：重算哈希，篡改样本降级为参考（不入校准池）。"""
    from api.services.growth import prediction_freeze as pf

    _require_product(product_id)
    return pf.verify_integrity(product_id, experiment_id)


@router.post("/products/{product_id}/experiments/{experiment_id}/diagnose")
def post_diagnose(product_id: str, experiment_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """漏斗诊断：actual 观测 + 冻结预测 → 分层停诊 + topic/creative 分离判定。"""
    from api.services.growth import funnel

    _require_product(product_id)
    exp = next((e for e in store.list_experiments(product_id) if e.experiment_id == experiment_id), None)
    if not exp:
        raise HTTPException(status_code=404, detail=f"实验 {experiment_id} 不存在")
    variant_id = body.get("variant_id")
    frozen_pred = None
    for v in exp.content_variants:
        if v.get("_frozen") and (not variant_id or v.get("variant_id") == variant_id):
            frozen_pred = v["_frozen"]["predictions"]
            break
    if frozen_pred is None:
        raise HTTPException(status_code=400, detail="该实验没有冻结预测——先 freeze 再 diagnose")
    observations = body.get("observations") or []
    if body.get("use_stored"):
        observations = [
            {"name": o.name, "value": o.value}
            for o in store.list_observations(product_id, experiment_id)
        ]
    return funnel.diagnose(observations, frozen_pred, own_baseline=body.get("own_baseline"))


@router.post("/products/{product_id}/hypotheses")
def post_hypothesis(product_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """注册假设（裁决5/6）：声明 learning_scope / evidence_requirement / discovery_window_end。"""
    from api.services.growth import promotion as pr
    from api.services.growth.models import LearningRecord

    _require_product(product_id)
    body = {**body, "product_id": product_id, "stage": "hypothesis"}
    try:
        lr = pr.register_hypothesis(LearningRecord(**body))
        return {"learning": lr.model_dump()}
    except pr.PromotionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/products/{product_id}/hypotheses/{learning_id}/validate")
def post_validate_hypothesis(product_id: str, learning_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """holdout 验证：只收发现窗口之后的结果（in-sample 拒收）。"""
    from api.services.growth import promotion as pr

    _require_product(product_id)
    try:
        return pr.validate_hypothesis(product_id, learning_id, body.get("outcomes") or [])
    except pr.PromotionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/products/{product_id}/adjustment-check")
def post_adjustment_check(product_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """样本量纪律闸门（裁决7）：改模型前先问准不准。"""
    from api.services.growth import promotion as pr

    _require_product(product_id)
    try:
        return pr.check_adjustment_allowed(
            product_id, body.get("kind", ""), model_target=body.get("model_target", "")
        )
    except pr.PromotionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
