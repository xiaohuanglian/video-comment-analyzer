# -*- coding: utf-8 -*-
"""Resolve where insight runs and exported artifacts live on disk."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Set

from .paths import DATA_DIR, INSIGHT_SUBDIR
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
    """Primary CSV parent (first file)."""
    return csv_parent_dirs(config)[0]


def is_multi_video_config(config: RunConfig) -> bool:
    return len(csv_parent_dirs(config)) > 1


def canonical_storage_rel(config: RunConfig) -> str:
    if is_multi_video_config(config):
        return f".insight_runs/{config.run_id}"
    return (csv_parent_dir(config) / INSIGHT_SUBDIR / config.run_id).relative_to(_data_dir()).as_posix()


def source_files_for_parent(config: RunConfig, parent: Path) -> Set[str]:
    files: Set[str] = set()
    for rel in config.file_paths:
        try:
            csv_parent = resolve_under_data(rel).parent.resolve()
        except ValueError:
            csv_parent = (_data_dir() / rel).parent.resolve()
        if csv_parent == parent.resolve():
            files.add(rel)
    return files


def relative_storage_dir(config: RunConfig) -> str:
    return canonical_storage_rel(config)


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


def _normalize_file_paths(file_paths: list[str]) -> Set[str]:
    return {p.strip() for p in file_paths if p and p.strip()}


def find_resumable_run(file_paths: list[str]) -> str | None:
    """Return an incomplete run with the same source files (prefer canonical id without suffix)."""
    target = _normalize_file_paths(file_paths)
    if not target:
        return None
    from .storage import load_config, load_progress, list_runs

    candidates: list[str] = []
    for item in list_runs():
        run_id = str(item.get("run_id") or "")
        if not run_id:
            continue
        try:
            config = load_config(run_id)
            progress = load_progress(run_id)
        except (FileNotFoundError, OSError, ValueError):
            continue
        if _normalize_file_paths(list(config.file_paths)) != target:
            continue
        if progress.completed >= progress.total_records > 0:
            continue
        if progress.status == "completed" and not (progress.last_error or "").startswith("研究阶段"):
            continue
        candidates.append(run_id)
    if not candidates:
        return None
    return sorted(candidates, key=lambda rid: (("_" in rid and rid.rsplit("_", 1)[-1].isdigit()), rid))[0]


def run_exists_in_csv_dir(file_paths: list[str], candidate: str) -> bool:
    if (_legacy_runs_root() / candidate).exists():
        return True
    if (_data_dir() / ".insight_runs" / candidate).exists():
        return True
    if not file_paths:
        return False
    # Check every selected CSV parent for an existing .insight/{candidate}
    for rel in file_paths:
        try:
            csv_dir = resolve_under_data(rel).parent
        except ValueError:
            csv_dir = (_data_dir() / rel).parent
        partition = csv_dir / INSIGHT_SUBDIR / candidate
        if partition.exists() and not partition.is_symlink():
            return True
    return False


def safe_export_stem(name: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", (name or "分析").strip())
    return text[:60] or "分析"


def export_stem_for_parent(parent: Path) -> str:
    """Use video folder name + 评论分析 for exported artifact filenames."""
    return f"{safe_export_stem(parent.name)}_评论分析"


def export_artifact_paths(config: RunConfig) -> dict[str, Path]:
    """Primary export paths (first CSV parent). Multi-dir copies use export_artifact_targets."""
    parent = csv_parent_dir(config)
    stem = export_stem_for_parent(parent)
    return {
        "results_csv": parent / f"{stem}_分析结果.csv",
        "report_md": parent / f"{stem}_洞察报告.md",
        "candidates_csv": parent / f"{stem}_调研对象.csv",
        "outreach_csv": parent / f"{stem}_私信草稿.csv",
    }


def export_artifact_targets(config: RunConfig) -> list[dict[str, Path]]:
    """Export path sets for every unique CSV parent directory."""
    targets: list[dict[str, Path]] = []
    for parent in csv_parent_dirs(config):
        stem = export_stem_for_parent(parent)
        targets.append(
            {
                "results_csv": parent / f"{stem}_分析结果.csv",
                "report_md": parent / f"{stem}_洞察报告.md",
                "candidates_csv": parent / f"{stem}_调研对象.csv",
                "outreach_csv": parent / f"{stem}_私信草稿.csv",
            }
        )
    return targets
