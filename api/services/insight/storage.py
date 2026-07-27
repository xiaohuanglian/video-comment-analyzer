# -*- coding: utf-8 -*-
"""File-backed storage for analysis runs."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .paths import DATA_DIR, RUNS_ROOT
from .pricing import normalize_model_settings
from .run_locations import load_run_index, register_run, relative_storage_dir, run_dir_for_id
from .schemas import CommentAnalysisResult, RunConfig, RunProgress, SourceRecord

APP_DIR = Path(__file__).resolve().parents[3]

_write_locks_guard = threading.Lock()
_write_locks: Dict[str, threading.Lock] = {}


def _run_dir(run_id: str) -> Path:
    return run_dir_for_id(run_id)


def _path_lock(path: Path) -> threading.Lock:
    key = str(path.resolve()) if path.parent.exists() else str(path)
    with _write_locks_guard:
        lock = _write_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _write_locks[key] = lock
        return lock


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically; safe under concurrent writers for the same path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(path):
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
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    _atomic_write_text(path, text)


def _read_json(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Concurrent writers can briefly produce concatenated JSON ("Extra data").
        if "Extra data" in str(exc):
            obj, _ = json.JSONDecoder().raw_decode(text)
            return obj
        raise


def create_run(config: RunConfig, records: List[SourceRecord]) -> None:
    storage_rel = config.storage_dir or relative_storage_dir(config)
    config = config.model_copy(update={"storage_dir": storage_rel})
    run_dir = DATA_DIR / storage_rel
    run_dir.mkdir(parents=True, exist_ok=True)
    register_run(config)
    _write_json(run_dir / "config.json", config.model_dump())
    _write_json(
        run_dir / "progress.json",
        RunProgress(status="ready", total_records=len(records)).model_dump(),
    )
    with (run_dir / "source_records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
    (run_dir / "results.jsonl").write_text("", encoding="utf-8")
    (run_dir / "evidence_cards.jsonl").write_text("", encoding="utf-8")
    for name in (
        "themes.json",
        "candidates.json",
        "outreach.json",
        "summary.json",
        "trial_sample.json",
        "research_analysis.json",
        "conclusion_review.json",
    ):
        target = run_dir / name
        if name == "summary.json":
            _write_json(target, {"generated_at": None})
        elif name in {"research_analysis.json", "conclusion_review.json"}:
            _write_json(target, {})
        else:
            _write_json(target, {})


def load_config(run_id: str) -> RunConfig:
    return RunConfig.model_validate(_read_json(_run_dir(run_id) / "config.json"))


def save_config(run_id: str, config: RunConfig) -> None:
    _write_json(_run_dir(run_id) / "config.json", config.model_dump())


def ensure_run_config(config: RunConfig) -> RunConfig:
    normalized = normalize_model_settings(
        model_name=config.model_name,
        base_url=config.base_url,
        input_price=config.input_price,
        output_price=config.output_price,
        currency=config.currency,
    )
    return config.model_copy(
        update={
            "model_name": normalized["model_name"],
            "base_url": normalized["base_url"],
            "input_price": normalized["input_price"],
            "output_price": normalized["output_price"],
            "currency": normalized["currency"],
        }
    )


def load_progress(run_id: str) -> RunProgress:
    progress = RunProgress.model_validate(_read_json(_run_dir(run_id) / "progress.json"))
    if progress.actual_cost <= 0 and progress.estimated_cost > 0:
        progress.actual_cost = progress.estimated_cost
    return progress


def save_progress(run_id: str, progress: RunProgress) -> None:
    _write_json(_run_dir(run_id) / "progress.json", progress.model_dump())


def sync_progress_from_results(run_id: str) -> RunProgress:
    """Reconcile completed count from results.jsonl (e.g. after forced stop)."""
    progress = load_progress(run_id)
    done_ids = completed_record_ids(run_id)
    done_count = len(done_ids)
    changed = False
    if done_count > progress.completed:
        progress.completed = done_count
        changed = True
    # Drop stale failures that already have successful results.
    if progress.failed_record_ids:
        stale = [rid for rid in progress.failed_record_ids if rid in done_ids]
        if stale:
            stale_set = set(stale)
            progress.failed_record_ids = [
                rid for rid in progress.failed_record_ids if rid not in stale_set
            ]
            for rid in stale:
                progress.failed_errors.pop(rid, None)
            progress.failed = len(progress.failed_record_ids)
            changed = True
    skipped = max(0, progress.total_records - progress.completed - progress.failed)
    if skipped != progress.skipped:
        progress.skipped = skipped
        changed = True
    # Avoid rewriting progress.json on every 5s poll while the worker is also writing.
    if changed:
        save_progress(run_id, progress)
    return progress


def prune_stale_failures(progress: RunProgress, done_ids: Set[str]) -> bool:
    """Remove failed IDs that already have results. Returns True if mutated."""
    if not progress.failed_record_ids or not done_ids:
        return False
    stale = [rid for rid in progress.failed_record_ids if rid in done_ids]
    if not stale:
        return False
    stale_set = set(stale)
    progress.failed_record_ids = [
        rid for rid in progress.failed_record_ids if rid not in stale_set
    ]
    for rid in stale:
        progress.failed_errors.pop(rid, None)
    progress.failed = len(progress.failed_record_ids)
    return True


def remove_results_for_records(run_id: str, record_ids: Set[str]) -> int:
    """Drop existing result rows for the given record_ids so they can be re-analyzed."""
    if not record_ids:
        return 0
    path = _run_dir(run_id) / "results.jsonl"
    if not path.exists():
        return 0
    kept: List[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        rid = payload.get("record_id") or payload.get("analysis", {}).get("record_id")
        if rid in record_ids:
            removed += 1
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


def remove_evidence_for_records(run_id: str, record_ids: Set[str]) -> int:
    """Drop evidence cards for record_ids so force_reanalyze can truly re-extract."""
    if not record_ids:
        return 0
    path = _run_dir(run_id) / "evidence_cards.jsonl"
    if not path.exists():
        return 0
    kept: List[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        rid = payload.get("record_id") or (payload.get("card") or {}).get("record_id")
        if rid in record_ids:
            removed += 1
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed


def load_source_records(run_id: str) -> List[SourceRecord]:
    path = _run_dir(run_id) / "source_records.jsonl"
    records: List[SourceRecord] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(SourceRecord.model_validate_json(line))
    return records


def completed_record_ids(run_id: str) -> Set[str]:
    path = _run_dir(run_id) / "results.jsonl"
    done: Set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        record_id = payload.get("record_id") or payload.get("analysis", {}).get("record_id")
        if record_id:
            done.add(record_id)
    return done


def append_result(
    run_id: str,
    source: SourceRecord,
    analysis: CommentAnalysisResult,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    path = _run_dir(run_id) / "results.jsonl"
    payload = {
        "record_id": analysis.record_id,
        "source": source.model_dump(),
        "analysis": analysis.model_dump(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_results(run_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = _run_dir(run_id) / "results.jsonl"
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def save_summary(run_id: str, summary: Dict[str, object]) -> None:
    _write_json(_run_dir(run_id) / "summary.json", summary)


def load_summary(run_id: str) -> Dict[str, Any]:
    path = _run_dir(run_id) / "summary.json"
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_trial_sample(run_id: str, payload: Dict[str, Any]) -> None:
    _write_json(_run_dir(run_id) / "trial_sample.json", payload)


_DOCUMENT_LOAD_ERRORS: Dict[str, str] = {}


def _load_document(path: Path, model_cls):
    """Load a JSON document; on corruption return empty model and record an error."""
    key = str(path)
    if not path.exists():
        _DOCUMENT_LOAD_ERRORS.pop(key, None)
        return model_cls()
    try:
        data = _read_json(path)
    except (json.JSONDecodeError, OSError) as exc:
        _DOCUMENT_LOAD_ERRORS[key] = f"{path.name} 损坏或无法读取: {exc}"
        return model_cls()
    if not isinstance(data, dict):
        _DOCUMENT_LOAD_ERRORS[key] = f"{path.name} 格式无效（非对象）"
        return model_cls()
    try:
        doc = model_cls.model_validate(data)
        _DOCUMENT_LOAD_ERRORS.pop(key, None)
        return doc
    except Exception as exc:
        _DOCUMENT_LOAD_ERRORS[key] = f"{path.name} 校验失败: {exc}"
        return model_cls()


def document_load_error(path: Path) -> Optional[str]:
    return _DOCUMENT_LOAD_ERRORS.get(str(path))


def load_themes(run_id: str):
    from .theme_schemas import ThemesDocument

    return _load_document(_run_dir(run_id) / "themes.json", ThemesDocument)


def save_themes(run_id: str, doc) -> None:
    _write_json(_run_dir(run_id) / "themes.json", doc.model_dump())
    _DOCUMENT_LOAD_ERRORS.pop(str(_run_dir(run_id) / "themes.json"), None)


def save_open_theme_artifacts(run_id: str, doc, semantic_payload: Dict[str, Any]) -> None:
    """Commit themes and their semantic review from one atomic source of truth."""
    bundle = {
        "version": 1,
        "themes": doc.model_dump(mode="json"),
        "semantic_review": semantic_payload,
    }
    _write_json(_run_dir(run_id) / "open_theme_bundle.json", bundle)
    # Compatibility projections for existing reporting and export readers.
    save_themes(run_id, doc)
    save_semantic_review(run_id, semantic_payload)


def load_open_theme_artifacts(run_id: str) -> Optional[Dict[str, Any]]:
    path = _run_dir(run_id) / "open_theme_bundle.json"
    if not path.exists():
        return None
    try:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("themes"), dict) or not isinstance(
            payload.get("semantic_review"), dict
        ):
            return None
        return payload
    except (json.JSONDecodeError, OSError):
        return None


def load_candidates(run_id: str):
    from .candidate_schemas import CandidatesDocument

    return _load_document(_run_dir(run_id) / "candidates.json", CandidatesDocument)


def save_candidates(run_id: str, doc) -> None:
    _write_json(_run_dir(run_id) / "candidates.json", doc.model_dump())
    _DOCUMENT_LOAD_ERRORS.pop(str(_run_dir(run_id) / "candidates.json"), None)


def load_outreach(run_id: str):
    from .candidate_schemas import OutreachDocument

    return _load_document(_run_dir(run_id) / "outreach.json", OutreachDocument)


def save_outreach(run_id: str, doc) -> None:
    _write_json(_run_dir(run_id) / "outreach.json", doc.model_dump())
    _DOCUMENT_LOAD_ERRORS.pop(str(_run_dir(run_id) / "outreach.json"), None)


def load_document_warnings(run_id: str) -> Dict[str, str]:
    """Probe themes/candidates/outreach and return any load errors."""
    load_themes(run_id)
    load_candidates(run_id)
    load_outreach(run_id)
    run_dir = _run_dir(run_id)
    warnings: Dict[str, str] = {}
    for name in ("themes.json", "candidates.json", "outreach.json"):
        err = document_load_error(run_dir / name)
        if err:
            warnings[name] = err
    return warnings


def load_trial_sample(run_id: str) -> Dict[str, Any]:
    path = _run_dir(run_id) / "trial_sample.json"
    if not path.exists():
        return {}
    return _read_json(path)


def reset_failed_records(run_id: str, record_ids: Optional[List[str]] = None) -> RunProgress:
    progress = load_progress(run_id)
    targets = set(record_ids or progress.failed_record_ids)
    progress.failed_record_ids = [rid for rid in progress.failed_record_ids if rid not in targets]
    progress.failed_errors = {rid: msg for rid, msg in progress.failed_errors.items() if rid not in targets}
    progress.failed = len(progress.failed_record_ids)
    progress.skipped = max(0, progress.total_records - progress.completed - progress.failed)
    save_progress(run_id, progress)
    return progress


def list_runs() -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    def _append(run_id: str) -> None:
        if run_id in seen:
            return
        try:
            config = load_config(run_id)
            progress = load_progress(run_id)
        except (FileNotFoundError, OSError, ValueError):
            return
        seen.add(run_id)
        runs.append(
            {
                "run_id": config.run_id,
                "name": config.name,
                "created_at": config.created_at,
                "status": progress.status,
                "total_records": progress.total_records,
                "completed": progress.completed,
                "storage_dir": config.storage_dir,
            }
        )

    for run_id in load_run_index():
        _append(run_id)

    if RUNS_ROOT.exists():
        for run_dir in sorted(RUNS_ROOT.iterdir(), reverse=True):
            if run_dir.is_dir() and (run_dir / "config.json").exists():
                _append(run_dir.name)

    runs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return runs


# --- evidence_items_v1 artifacts ---


def completed_evidence_record_ids(run_id: str) -> Set[str]:
    path = _run_dir(run_id) / "evidence_cards.jsonl"
    done: Set[str] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        rid = payload.get("record_id") or (payload.get("card") or {}).get("record_id")
        if rid:
            done.add(rid)
    return done


def append_evidence_card(
    run_id: str,
    source: SourceRecord,
    card,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    from_cache: bool = False,
) -> None:
    path = _run_dir(run_id) / "evidence_cards.jsonl"
    payload = {
        "record_id": card.record_id,
        "source": source.model_dump(),
        "card": card.model_dump(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "from_cache": from_cache,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def replace_evidence_cards(run_id: str, rows: List[Dict[str, Any]]) -> None:
    """Atomically rewrite evidence_cards.jsonl (dedupe-friendly finalization)."""
    path = _run_dir(run_id) / "evidence_cards.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _path_lock(path):
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


def load_evidence_cards(run_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = _run_dir(run_id) / "evidence_cards.jsonl"
    if not path.exists():
        return []
    # Keep last row per record_id to tolerate accidental double-appends
    by_id: Dict[str, Dict[str, Any]] = {}
    ordered: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        rid = payload.get("record_id") or (payload.get("card") or {}).get("record_id")
        if not rid:
            continue
        if rid not in by_id:
            ordered.append(rid)
        by_id[rid] = payload
    rows = [by_id[rid] for rid in ordered]
    if limit:
        rows = rows[:limit]
    return rows


def results_for_candidates(run_id: str) -> List[Dict[str, Any]]:
    """Merge legacy results.jsonl with evidence_cards.jsonl for third-column build."""
    from .evidence_adapter import merge_projected_analysis, outreach_analysis_from_card

    results = load_results(run_id)
    by_id: Dict[str, Dict[str, Any]] = {}
    ordered: List[str] = []
    for row in results:
        rid = str(row.get("record_id") or "")
        if not rid:
            continue
        if rid not in by_id:
            ordered.append(rid)
        by_id[rid] = row

    for card_row in load_evidence_cards(run_id):
        rid = str(card_row.get("record_id") or "")
        if not rid:
            continue
        card = card_row.get("card") or {}
        projected = outreach_analysis_from_card(card)
        if rid in by_id:
            existing = dict(by_id[rid])
            analysis = merge_projected_analysis(existing.get("analysis") or {}, projected)
            analysis["paid_help"] = bool(analysis.get("paid_help") or projected.get("paid_help"))
            existing["analysis"] = analysis
            existing["card"] = card
            by_id[rid] = existing
        else:
            ordered.append(rid)
            by_id[rid] = {
                "record_id": rid,
                "source": card_row.get("source") or {},
                "card": card,
                "analysis": projected,
                "analyzed_at": card_row.get("analyzed_at") or "",
            }
    return [by_id[rid] for rid in ordered]


def save_research_analysis(run_id: str, payload: Dict[str, Any]) -> None:
    _write_json(_run_dir(run_id) / "research_analysis.json", payload)


def load_research_analysis(run_id: str) -> Dict[str, Any]:
    path = _run_dir(run_id) / "research_analysis.json"
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_conclusion_review(run_id: str, payload: Dict[str, Any]) -> None:
    _write_json(_run_dir(run_id) / "conclusion_review.json", payload)


def load_conclusion_review(run_id: str) -> Dict[str, Any]:
    path = _run_dir(run_id) / "conclusion_review.json"
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_semantic_review(run_id: str, payload: Dict[str, Any]) -> None:
    _write_json(_run_dir(run_id) / "semantic_review.json", payload)


def load_semantic_review(run_id: str) -> Dict[str, Any]:
    path = _run_dir(run_id) / "semantic_review.json"
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_research_report(run_id: str, markdown: str) -> None:
    (_run_dir(run_id) / "research_report.md").write_text(markdown or "", encoding="utf-8")


def load_research_report(run_id: str) -> str:
    path = _run_dir(run_id) / "research_report.md"
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""
