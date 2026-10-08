# -*- coding: utf-8 -*-
"""Growth Engine REST API (Phase 1 store + Phase 2 orchestrator entry)."""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.growth import seeds, store
from ..services.growth.models import (
    ContentAsset,
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


@router.get("/products/{product_id}/opportunities")
def get_opportunities(product_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    return {"opportunities": [o.model_dump() for o in store.list_opportunities(product_id)]}


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


@router.post("/agent/run")
def post_agent_run(body: RunAgentRequest) -> Dict[str, Any]:
    _require_product(body.product_id)
    config_kwargs = body.model_dump(exclude={"api_key"})
    config_kwargs["use_mock"] = body.use_mock or not body.api_key
    config = SessionConfig(**{k: v for k, v in config_kwargs.items() if v not in ("",) or k != "base_url"})
    orch = Orchestrator(config, api_key=body.api_key)
    session = orch.run()  # 同步执行：受 max_iterations / 预算约束的小任务
    return session.model_dump()


@router.post("/agent/run_async")
def post_agent_run_async(body: RunAgentRequest) -> Dict[str, Any]:
    _require_product(body.product_id)
    config = SessionConfig(**{k: v for k, v in body.model_dump(exclude={"api_key"}).items()})
    config.use_mock = body.use_mock or not body.api_key
    orch = Orchestrator(config, api_key=body.api_key)
    thread = threading.Thread(target=orch.run, name=f"growth-agent-{orch.session.session_id}", daemon=True)
    thread.start()
    return {"session_id": orch.session.session_id, "status": "running", "mock": config.use_mock}


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


@router.post("/agent/sessions/{session_id}/stop")
def post_agent_stop(product_id: str, session_id: str) -> Dict[str, Any]:
    _require_product(product_id)
    orch = get_orchestrator(session_id)
    if orch is None:
        raise HTTPException(status_code=404, detail="会话不在运行中")
    orch.request_cancel()
    return {"ok": True}
