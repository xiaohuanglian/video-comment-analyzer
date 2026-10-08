# -*- coding: utf-8 -*-
"""Product-isolated file storage for the growth domain.

Layout (never touches existing analysis-run data):

    data/growth/
      products.json                      # registry of ProductProfile
      <product_id>/
        signals.jsonl
        assets.json
        opportunities.json
        experiments.json
        observations.jsonl
        learnings.json
        audit.jsonl

Writes are atomic (tmp + os.replace), mirroring insight/storage.py.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Type, TypeVar

from pydantic import BaseModel

from ..insight.paths import DATA_DIR
from .models import (
    AuditRecord,
    ContentAsset,
    ContentBrief,
    GrowthExperiment,
    UserSegmentReport,
    GrowthOpportunity,
    LearningRecord,
    MetricsObservation,
    ProductProfile,
    Signal,
)

GROWTH_ROOT = DATA_DIR / "growth"
PRODUCTS_FILE = "products.json"

_locks_guard = threading.Lock()
_locks: Dict[str, threading.Lock] = {}


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve()) if path.parent.exists() else str(path)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def _write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False)
    with _lock_for(path):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def _product_dir(product_id: str) -> Path:
    pid = (product_id or "").strip()
    if not pid or pid in {".", ".."} or "/" in pid or "\\" in pid:
        raise ValueError(f"非法 product_id: {product_id!r}")
    return GROWTH_ROOT / pid


# --- product registry --------------------------------------------------------


def list_products() -> List[ProductProfile]:
    raw = _read_json(GROWTH_ROOT / PRODUCTS_FILE, {"profiles": []})
    entries = raw.get("profiles", raw) if isinstance(raw, dict) else raw
    out: List[ProductProfile] = []
    for item in entries or []:
        try:
            out.append(ProductProfile.model_validate(item))
        except Exception:
            continue
    return out


def get_product(product_id: str) -> Optional[ProductProfile]:
    for p in list_products():
        if p.product_id == product_id:
            return p
    return None


def upsert_product(profile: ProductProfile) -> ProductProfile:
    if not profile.product_id.strip():
        raise ValueError("product_id 不能为空")
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    profile = profile.model_copy(update={"updated_at": now, "created_at": profile.created_at or now})
    products = {p.product_id: p for p in list_products()}
    products[profile.product_id] = profile
    _write_json(
        GROWTH_ROOT / PRODUCTS_FILE,
        {"version": 1, "profiles": [p.model_dump() for p in products.values()]},
    )
    _product_dir(profile.product_id).mkdir(parents=True, exist_ok=True)
    return profile


# --- generic per-product collections -----------------------------------------

M = TypeVar("M", bound=BaseModel)


def _collection_path(product_id: str, name: str, jsonl: bool = False) -> Path:
    suffix = ".jsonl" if jsonl else ".json"
    return _product_dir(product_id) / f"{name}{suffix}"


def _load_collection(product_id: str, name: str, model: Type[M]) -> List[M]:
    raw = _read_json(_collection_path(product_id, name), [])
    out: List[M] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            out.append(model.model_validate(item))
        except Exception:
            continue
    return out


def _save_collection(product_id: str, name: str, items: List[BaseModel]) -> None:
    _write_json(_collection_path(product_id, name), [i.model_dump() for i in items])


def _upsert(items: List[M], item: M, key: Callable[[M], str]) -> List[M]:
    k = key(item)
    replaced = False
    out: List[M] = []
    for existing in items:
        if key(existing) == k:
            out.append(item)
            replaced = True
        else:
            out.append(existing)
    if not replaced:
        out.append(item)
    return out


# signals (append-only jsonl) -------------------------------------------------


def add_signals(signals: List[Signal]) -> int:
    grouped: Dict[str, List[Signal]] = {}
    for s in signals:
        grouped.setdefault(s.product_id, []).append(s)
    n = 0
    for pid, batch in grouped.items():
        get_product_or_raise(pid)
        path = _collection_path(pid, "signals", jsonl=True)
        for s in batch:
            _append_jsonl(path, s.model_dump())
            n += 1
    return n


def list_signals(product_id: str, limit: Optional[int] = None) -> List[Signal]:
    out: List[Signal] = []
    for raw in _iter_jsonl(_collection_path(product_id, "signals", jsonl=True)):
        try:
            out.append(Signal.model_validate(raw))
        except Exception:
            continue
        if limit and len(out) >= limit:
            break
    return out


# assets / opportunities / experiments / learnings (json collections) ---------


def list_assets(product_id: str) -> List[ContentAsset]:
    return _load_collection(product_id, "assets", ContentAsset)


def upsert_asset(asset: ContentAsset) -> ContentAsset:
    get_product_or_raise(asset.product_id)
    items = _upsert(list_assets(asset.product_id), asset, lambda a: a.asset_id)
    _save_collection(asset.product_id, "assets", items)
    return asset


def list_segment_reports(product_id: str) -> List[UserSegmentReport]:
    return _load_collection(product_id, "segment_reports", UserSegmentReport)


def upsert_segment_report(report: UserSegmentReport) -> UserSegmentReport:
    get_product_or_raise(report.product_id)
    items = _upsert(list_segment_reports(report.product_id), report, lambda r: r.report_id)
    _save_collection(report.product_id, "segment_reports", items)
    return report


def list_briefs(product_id: str) -> List[ContentBrief]:
    return _load_collection(product_id, "briefs", ContentBrief)


def upsert_brief(brief: ContentBrief) -> ContentBrief:
    get_product_or_raise(brief.product_id)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    brief = brief.model_copy(update={"updated_at": now, "created_at": brief.created_at or now})
    items = _upsert(list_briefs(brief.product_id), brief, lambda b: b.brief_id)
    _save_collection(brief.product_id, "briefs", items)
    return brief


def list_opportunities(product_id: str) -> List[GrowthOpportunity]:
    return _load_collection(product_id, "opportunities", GrowthOpportunity)


def upsert_opportunity(opp: GrowthOpportunity) -> GrowthOpportunity:
    get_product_or_raise(opp.product_id)
    items = _upsert(list_opportunities(opp.product_id), opp, lambda o: o.opportunity_id)
    _save_collection(opp.product_id, "opportunities", items)
    return opp


def list_experiments(product_id: str) -> List[GrowthExperiment]:
    return _load_collection(product_id, "experiments", GrowthExperiment)


def upsert_experiment(exp: GrowthExperiment) -> GrowthExperiment:
    get_product_or_raise(exp.product_id)
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    exp = exp.model_copy(update={"updated_at": now, "created_at": exp.created_at or now})
    items = _upsert(list_experiments(exp.product_id), exp, lambda e: e.experiment_id)
    _save_collection(exp.product_id, "experiments", items)
    return exp


def list_learnings(product_id: str) -> List[LearningRecord]:
    return _load_collection(product_id, "learnings", LearningRecord)


def upsert_learning(rec: LearningRecord) -> LearningRecord:
    get_product_or_raise(rec.product_id)
    items = _upsert(list_learnings(rec.product_id), rec, lambda r: r.learning_id)
    _save_collection(rec.product_id, "learnings", items)
    return rec


# observations (append-only jsonl) --------------------------------------------


def add_observations(obs: List[MetricsObservation]) -> int:
    grouped: Dict[str, List[MetricsObservation]] = {}
    for o in obs:
        grouped.setdefault(o.product_id, []).append(o)
    n = 0
    for pid, batch in grouped.items():
        get_product_or_raise(pid)
        path = _collection_path(pid, "observations", jsonl=True)
        for o in batch:
            _append_jsonl(path, o.model_dump())
            n += 1
    return n


def list_observations(product_id: str, experiment_id: str = "") -> List[MetricsObservation]:
    out: List[MetricsObservation] = []
    for raw in _iter_jsonl(_collection_path(product_id, "observations", jsonl=True)):
        try:
            o = MetricsObservation.model_validate(raw)
        except Exception:
            continue
        if experiment_id and o.experiment_id != experiment_id:
            continue
        out.append(o)
    return out


# audit -----------------------------------------------------------------------


def record_audit(rec: AuditRecord) -> None:
    _append_jsonl(_collection_path(rec.product_id, "audit", jsonl=True), rec.model_dump())


def list_audit(product_id: str, limit: Optional[int] = None) -> List[AuditRecord]:
    out: List[AuditRecord] = []
    for raw in _iter_jsonl(_collection_path(product_id, "audit", jsonl=True)):
        try:
            out.append(AuditRecord.model_validate(raw))
        except Exception:
            continue
    if limit:
        return out[-limit:]
    return out


# import batches（数据导入批次溯源） ----------------------------------------------


def record_import_batch(product_id: str, batch: Dict[str, Any]) -> None:
    """登记一次数据导入：来源、条数、数据性质（real/demo/unknown）、备注。

    用途：区分真实/模拟/未知数据，防止污染正式经验库时无法追溯。
    """
    get_product_or_raise(product_id)
    from datetime import datetime, timezone

    entry = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        **batch,
    }
    _append_jsonl(_collection_path(product_id, "import_batches", jsonl=True), entry)


def list_import_batches(product_id: str) -> List[Dict[str, Any]]:
    return list(_iter_jsonl(_collection_path(product_id, "import_batches", jsonl=True)))


# misc ------------------------------------------------------------------------


def get_product_or_raise(product_id: str) -> ProductProfile:
    p = get_product(product_id)
    if p is None:
        raise KeyError(f"产品不存在: {product_id}")
    return p


def export_product(product_id: str) -> Dict[str, Any]:
    """Full export of one product's growth data (no other product is touched)."""
    get_product_or_raise(product_id)
    return {
        "version": 1,
        "product": get_product(product_id).model_dump(),
        "signals": [s.model_dump() for s in list_signals(product_id)],
        "assets": [a.model_dump() for a in list_assets(product_id)],
        "opportunities": [o.model_dump() for o in list_opportunities(product_id)],
        "briefs": [b.model_dump() for b in list_briefs(product_id)],
        "experiments": [e.model_dump() for e in list_experiments(product_id)],
        "observations": [o.model_dump() for o in list_observations(product_id)],
        "learnings": [r.model_dump() for r in list_learnings(product_id)],
    }


def import_product(payload: Dict[str, Any], *, overwrite: bool = False) -> Dict[str, int]:
    """Import one product bundle. Existing ids are kept unless overwrite=True."""
    profile = ProductProfile.model_validate(payload.get("product") or {})
    if get_product(profile.product_id) is None:
        upsert_product(profile)
    elif overwrite:
        upsert_product(profile)
    counts = {"signals": 0, "assets": 0, "experiments": 0, "observations": 0, "learnings": 0, "briefs": 0}
    counts["signals"] = add_signals([Signal.model_validate(s) for s in payload.get("signals", [])])
    for raw in payload.get("assets", []):
        asset = ContentAsset.model_validate(raw)
        if overwrite or not any(a.asset_id == asset.asset_id for a in list_assets(profile.product_id)):
            upsert_asset(asset)
            counts["assets"] += 1
    for raw in payload.get("experiments", []):
        upsert_experiment(GrowthExperiment.model_validate(raw))
        counts["experiments"] += 1
    counts["observations"] = add_observations(
        [MetricsObservation.model_validate(o) for o in payload.get("observations", [])]
    )
    for raw in payload.get("learnings", []):
        upsert_learning(LearningRecord.model_validate(raw))
        counts["learnings"] += 1
    for raw in payload.get("briefs", []):
        upsert_brief(ContentBrief.model_validate(raw))
        counts["briefs"] += 1
    return counts
