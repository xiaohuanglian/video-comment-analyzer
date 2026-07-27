# -*- coding: utf-8 -*-
"""Per-video .insight partitions for multi-source runs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable, List, Set

from .paths import INSIGHT_SUBDIR
from .run_locations import (
    canonical_storage_rel,
    csv_parent_dirs,
    is_multi_video_config,
    register_run,
    run_dir_for_id,
    source_files_for_parent,
)
from .statistics import build_statistics


def _data_dir() -> Path:
    # Prefer storage.DATA_DIR so tests can monkeypatch it.
    from . import storage

    return storage.DATA_DIR


def ensure_canonical_run_location(run_id: str) -> Path:
    """Move multi-video runs off a video folder into data/.insight_runs/{run_id}."""
    from .storage import load_config, save_config

    config = load_config(run_id)
    if not is_multi_video_config(config):
        return run_dir_for_id(run_id)

    data_dir = _data_dir()
    target_rel = canonical_storage_rel(config)
    target = (data_dir / target_rel).resolve()
    current = run_dir_for_id(run_id).resolve()
    if current == target:
        if config.storage_dir != target_rel:
            config = config.model_copy(update={"storage_dir": target_rel})
            register_run(config)
            save_config(run_id, config)
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    if current.exists() and not target.exists():
        shutil.move(str(current), str(target))
    elif current.exists() and target.exists():
        for item in current.iterdir():
            dest = target / item.name
            if dest.exists():
                continue
            shutil.move(str(item), str(dest))
        shutil.rmtree(current, ignore_errors=True)

    config = config.model_copy(update={"storage_dir": target_rel})
    register_run(config)
    save_config(run_id, config)
    return target


def _remove_alias_path(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists() and path.is_dir() and not any(path.iterdir()):
        path.rmdir()


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _filter_jsonl(path: Path, source_files: Set[str], *, source_key: str = "source") -> List[dict]:
    if not path.exists():
        return []
    rows: List[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        source = payload.get(source_key) or {}
        source_file = str(source.get("source_file") or "")
        if source_file in source_files:
            rows.append(payload)
    return rows


def _copy_if_exists(src: Path, dest: Path) -> None:
    if src.exists() and src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def partition_run_storage(run_id: str) -> None:
    """Write each video folder its own scoped .insight/{run_id} (no cross-video symlinks)."""
    from .storage import (
        _write_json,
        load_config,
        load_evidence_cards,
        load_progress,
        load_results,
        load_semantic_review,
        load_source_records,
        load_themes,
    )

    config = load_config(run_id)
    if not is_multi_video_config(config):
        return

    canonical = ensure_canonical_run_location(run_id)
    config = load_config(run_id)
    canonical_rel = (
        config.storage_dir
        or canonical.relative_to(_data_dir().resolve()).as_posix()
    )
    records = load_source_records(run_id)
    results = load_results(run_id)
    cards = load_evidence_cards(run_id)
    progress = load_progress(run_id)

    copy_names = (
        "research_analysis.json",
        "conclusion_review.json",
        "candidates.json",
        "outreach.json",
        "research_performance.json",
        "extract_performance.json",
        "trial_sample.json",
    )

    for parent in csv_parent_dirs(config):
        source_files = source_files_for_parent(config, parent)
        if not source_files:
            continue

        partition_dir = parent / INSIGHT_SUBDIR / run_id
        _remove_alias_path(partition_dir)
        partition_dir.mkdir(parents=True, exist_ok=True)

        _write_json(
            partition_dir / "run_root.json",
            {
                "run_id": run_id,
                "canonical_storage_dir": canonical_rel,
                "source_files": sorted(source_files),
            },
        )

        scoped_records = [record for record in records if record.source_file in source_files]
        with (partition_dir / "source_records.jsonl").open("w", encoding="utf-8") as handle:
            for record in scoped_records:
                handle.write(record.model_dump_json() + "\n")

        scoped_results = [
            row
            for row in results
            if str((row.get("source") or {}).get("source_file") or "") in source_files
        ]
        _write_jsonl(partition_dir / "results.jsonl", scoped_results)

        scoped_cards = [
            row
            for row in cards
            if str((row.get("source") or {}).get("source_file") or "") in source_files
        ]
        _write_jsonl(partition_dir / "evidence_cards.jsonl", scoped_cards)

        partition_config = config.model_dump()
        partition_config["storage_dir"] = canonical_rel
        partition_config["partition_source_files"] = sorted(source_files)
        _write_json(partition_dir / "config.json", partition_config)

        scoped_progress = progress.model_copy(
            update={
                "total_records": len(scoped_records),
                "completed": len(scoped_results),
            }
        )
        scoped_progress.skipped = max(
            0,
            scoped_progress.total_records - scoped_progress.completed - scoped_progress.failed,
        )
        _write_json(partition_dir / "progress.json", scoped_progress.model_dump())

        scoped_summary = build_statistics(scoped_results, total_records=len(scoped_records))
        _write_json(partition_dir / "summary.json", scoped_summary)

        for name in copy_names:
            _copy_if_exists(canonical / name, partition_dir / name)

        # Open themes must stay per-video: never copy the mixed canonical themes.json.
        themes_doc = load_themes(run_id)
        semantic_payload = load_semantic_review(run_id)
        per_source_ids = semantic_payload.get("per_source_open_theme_ids") or {}
        allowed_theme_ids = {
            theme_id
            for source_file in source_files
            for theme_id in per_source_ids.get(source_file, [])
        }
        if themes_doc.themes and allowed_theme_ids:
            scoped_themes = themes_doc.model_copy(deep=True)
            scoped_themes.themes = [
                theme for theme in scoped_themes.themes if theme.theme_id in allowed_theme_ids
            ]
            scoped_themes.raw_signal_count = sum(
                1
                for row in scoped_results
                for signal in ((row.get("analysis") or {}).get("new_signals") or [])
                if isinstance(signal, dict)
            )
            _write_json(partition_dir / "themes.json", scoped_themes.model_dump())
        elif (canonical / "themes.json").exists() and not themes_doc.themes:
            _copy_if_exists(canonical / "themes.json", partition_dir / "themes.json")

        if semantic_payload:
            scoped_semantic = dict(semantic_payload)
            scoped_semantic["per_source_open_theme_ids"] = {
                source_file: list(per_source_ids.get(source_file) or [])
                for source_file in source_files
            }
            per_source_open = semantic_payload.get("per_source_open_themes") or {}
            matched_open = [
                per_source_open[source_file]
                for source_file in source_files
                if source_file in per_source_open
            ]
            if matched_open:
                if len(matched_open) == 1:
                    scoped_semantic["open_themes"] = matched_open[0]
                else:
                    scoped_semantic["open_themes"] = {
                        "passed": all(item.get("passed", True) for item in matched_open),
                        "claims": [
                            claim
                            for item in matched_open
                            for claim in (item.get("claims") or [])
                        ],
                        "reviews": [
                            review
                            for item in matched_open
                            for review in (item.get("reviews") or [])
                        ],
                        "removed_claim_ids": [
                            claim_id
                            for item in matched_open
                            for claim_id in (item.get("removed_claim_ids") or [])
                        ],
                        "downgraded_claim_ids": [
                            claim_id
                            for item in matched_open
                            for claim_id in (item.get("downgraded_claim_ids") or [])
                        ],
                    }
            elif allowed_theme_ids and isinstance(scoped_semantic.get("open_themes"), dict):
                open_themes = dict(scoped_semantic["open_themes"])
                open_themes["reviews"] = [
                    review
                    for review in (open_themes.get("reviews") or [])
                    if str(review.get("claim_id") or "").removeprefix("open_theme:")
                    in allowed_theme_ids
                ]
                scoped_semantic["open_themes"] = open_themes
            scoped_semantic["per_source_open_themes"] = {
                source_file: per_source_open[source_file]
                for source_file in source_files
                if source_file in per_source_open
            }
            # Keep research semantic scoped when available.
            if "per_source" in scoped_semantic:
                scoped_semantic["per_source"] = {
                    source_file: (scoped_semantic.get("per_source") or {}).get(source_file)
                    for source_file in source_files
                    if (scoped_semantic.get("per_source") or {}).get(source_file) is not None
                }
            _write_json(partition_dir / "semantic_review.json", scoped_semantic)

        if progress.status == "completed":
            try:
                from .export import (
                    _scoped_open_themes,
                    _scoped_qual_stats,
                    _scoped_research_payload,
                )
                from .readable_report import build_readable_report

                research, partition_records, partition_cards = _scoped_research_payload(
                    run_id, source_files
                )
                report_md = build_readable_report(
                    research=research,
                    records=partition_records,
                    card_rows=partition_cards,
                    run_id=f"{config.name} · {parent.name}",
                    open_themes=_scoped_open_themes(run_id, source_files=source_files),
                    qual_stats=_scoped_qual_stats(
                        run_id,
                        source_files=source_files,
                        total_records=len(partition_records),
                    ),
                )
                (partition_dir / "research_report.md").write_text(report_md, encoding="utf-8")
            except Exception:
                pass

        # Remove stale cross-video symlinks under this video folder.
        for sibling in (parent / INSIGHT_SUBDIR).glob("*"):
            if sibling == partition_dir:
                continue
            if sibling.is_symlink():
                sibling.unlink()
