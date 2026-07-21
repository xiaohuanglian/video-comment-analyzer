# -*- coding: utf-8 -*-
"""Resolve where insight runs and exported artifacts live on disk."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import INSIGHT_SUBDIR
from .schemas import RunConfig


def _data_dir() -> Path:
    # Prefer storage.DATA_DIR so tests can monkeypatch it
    from . import storage

    return storage.DATA_DIR


def _legacy_runs_root() -> Path:
    """Legacy runs live under data/analysis_runs/ (same as storage.RUNS_ROOT)."""
    from . import storage

    return storage.RUNS_ROOT


def _run_index_path() -> Path:
    return _data_dir() / ".insight_run_index.json"


def resolve_under_data(rel_path: str) -> Path:
    """Resolve a path relative to DATA_DIR; reject traversal outside it."""
    data_root = _data_dir().resolve()
    candidate = (data_root / rel_path).resolve()
    try:
        candidate.relative_to(data_root)
    except ValueError as exc:
        raise ValueError(f"非法路径（超出 data 目录）: {rel_path}") from exc
    return candidate


def csv_parent_dirs(config: RunConfig) -> list[Path]:
    """Unique parent directories for all source CSV paths (order preserved)."""
    if not config.file_paths:
        return [_data_dir()]
    parents: list[Path] = []
    seen: set[Path] = set()
    for rel in config.file_paths:
        try:
            parent = resolve_under_data(rel).parent
        except ValueError:
            parent = (_data_dir() / rel).parent
        if parent not in seen:
            seen.add(parent)
            parents.append(parent)
    return parents or [_data_dir()]


def csv_parent_dir(config: RunConfig) -> Path:
    """Primary CSV parent (first file); used for .insight/ storage."""
    return csv_parent_dirs(config)[0]


def relative_storage_dir(config: RunConfig) -> str:
    return (csv_parent_dir(config) / INSIGHT_SUBDIR / config.run_id).relative_to(_data_dir()).as_posix()


def run_dir_for_id(run_id: str, index: dict[str, str] | None = None) -> Path:
    mapping = index if index is not None else load_run_index()
    if run_id in mapping:
        return _data_dir() / mapping[run_id]
    legacy_path = _legacy_runs_root() / run_id
    if legacy_path.exists():
        return legacy_path
    raise FileNotFoundError(f"任务不存在: {run_id}")


def load_run_index() -> dict[str, str]:
    path = _run_index_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_run_index(index: dict[str, str]) -> None:
    path = _run_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def register_run(config: RunConfig) -> None:
    index = load_run_index()
    rel = config.storage_dir or relative_storage_dir(config)
    index[config.run_id] = rel
    save_run_index(index)


def run_exists_in_csv_dir(file_paths: list[str], candidate: str) -> bool:
    if (_legacy_runs_root() / candidate).exists():
        return True
    if not file_paths:
        return False
    # Check every selected CSV parent for an existing .insight/{candidate}
    for rel in file_paths:
        try:
            csv_dir = resolve_under_data(rel).parent
        except ValueError:
            csv_dir = (_data_dir() / rel).parent
        if (csv_dir / INSIGHT_SUBDIR / candidate).exists():
            return True
    return False


def safe_export_stem(name: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", (name or "分析").strip())
    return text[:60] or "分析"


def export_artifact_paths(config: RunConfig) -> dict[str, Path]:
    """Primary export paths (first CSV parent). Multi-dir copies use export_artifact_targets."""
    stem = safe_export_stem(config.name)
    parent = csv_parent_dir(config)
    return {
        "results_csv": parent / f"{stem}_分析结果.csv",
        "report_md": parent / f"{stem}_洞察报告.md",
        "candidates_csv": parent / f"{stem}_调研对象.csv",
        "outreach_csv": parent / f"{stem}_私信草稿.csv",
    }


def export_artifact_targets(config: RunConfig) -> list[dict[str, Path]]:
    """Export path sets for every unique CSV parent directory."""
    stem = safe_export_stem(config.name)
    targets: list[dict[str, Path]] = []
    for parent in csv_parent_dirs(config):
        targets.append(
            {
                "results_csv": parent / f"{stem}_分析结果.csv",
                "report_md": parent / f"{stem}_洞察报告.md",
                "candidates_csv": parent / f"{stem}_调研对象.csv",
                "outreach_csv": parent / f"{stem}_私信草稿.csv",
            }
        )
    return targets
