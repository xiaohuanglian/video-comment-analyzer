"""Hybrid local-embedding open-theme pipeline."""

from __future__ import annotations

import json
import hashlib
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .theme_embeddings import SentenceTransformersBackend, load_or_encode
from .theme_local_clustering import cluster_video_signals
from .theme_quality import validate_theme_document
from .theme_signal_preprocess import group_prepared_by_source, prepare_theme_signals
from .theme_schemas import ThemeRecord, ThemeStats, ThemesDocument


PIPELINE_VERSION = "hybrid_cluster_v1"


def _write_json(path: Path, payload: Any) -> None:
    from .storage import _write_json

    _write_json(path, payload)


def _fallback_label(signals) -> tuple[str, str]:
    terms = Counter()
    for signal in signals:
        for token in signal.normalized_text.split():
            if len(token) >= 2:
                terms[token] += signal.frequency
    top = [term for term, _ in terms.most_common(2)]
    name = "／".join(top) if top else "待复核开放主题"
    return name[:20], f"围绕「{name[:40]}」的用户新信号聚类"


def run_hybrid_theme_pipeline(
    run_id: str,
    *,
    config,
    pipeline_dir: Path,
    use_mock: bool = False,
) -> ThemesDocument:
    """Run deterministic full-coverage clustering; labels deliberately short."""
    from .storage import load_results

    started = time.monotonic()
    results = load_results(run_id)
    prepared = prepare_theme_signals(results)
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    prepared_path = pipeline_dir / "signals_prepared.jsonl"
    prepared_path.write_text(
        "".join(json.dumps(item.model_dump(), ensure_ascii=False) + "\n" for item in prepared),
        encoding="utf-8",
    )
    by_source = group_prepared_by_source(prepared)
    if use_mock:
        import numpy as np

        class MockBackend:
            model_name = "mock"

            def encode(self, texts):
                # Stable test-only pseudo vectors, no ML dependency.
                matrix = np.zeros((len(texts), 8), dtype=np.float32)
                for row, text in enumerate(texts):
                    for char in text:
                        matrix[row, ord(char) % 8] += 1
                norm = np.linalg.norm(matrix, axis=1, keepdims=True)
                return matrix / np.maximum(norm, 1e-12)

        backend = MockBackend()
    else:
        backend = SentenceTransformersBackend(
            config.theme_embedding_model,
            device=config.theme_embedding_device,
            batch_size=config.theme_embedding_batch_size,
        )

    records: List[ThemeRecord] = []
    unclustered = []
    per_source_theme_ids: Dict[str, List[str]] = {}
    cache_hits = cache_misses = 0
    for source_file, items in by_source.items():
        embeddings, cache = load_or_encode(
            pipeline_dir, [item.normalized_text for item in items], backend
        )
        cache_hits += cache["hits"]
        cache_misses += cache["misses"]
        video_id = f"v{hashlib.sha1(source_file.encode('utf-8')).hexdigest()[:8]}"
        clustered = cluster_video_signals(
            video_id, items, embeddings, min_samples=config.theme_cluster_min_samples
        )
        _write_json(pipeline_dir / "video_clusters" / f"{video_id}.json", clustered)
        for index in clustered["unclustered_indexes"]:
            unclustered.append({**items[index].model_dump(), "reason": "density_noise"})
        for cluster in clustered["clusters"]:
            member_signals = [items[i] for i in cluster["member_indexes"]]
            name, definition = _fallback_label(member_signals)
            reps = [items[i] for i in cluster["representative_indexes"]]
            records.append(
                ThemeRecord(
                    theme_id=cluster["cluster_id"],
                    theme_name=name,
                    theme_type=max(
                        cluster["signal_type_distribution"],
                        key=cluster["signal_type_distribution"].get,
                    ),
                    definition=definition,
                    included_signal_ids=cluster["signal_ids"],
                    record_ids=cluster["record_ids"],
                    confidence=cluster["cohesion_score"],
                    representative_quotes=[
                        (item.sample_quotes or [item.original_text])[0] for item in reps
                    ],
                    stats=ThemeStats(
                        comment_count=cluster["weighted_frequency"],
                        unique_user_count=cluster["user_count"],
                        source_file_count=1,
                        video_count=1,
                    ),
                )
            )
            per_source_theme_ids.setdefault(source_file, []).append(cluster["cluster_id"])
    _write_json(pipeline_dir / "unclustered_signals.jsonl", unclustered)
    known_signal_ids = {sid for item in prepared for sid in item.signal_ids}
    known_record_ids = {rid for item in prepared for rid in item.record_ids}
    document = ThemesDocument(
        engine=PIPELINE_VERSION,
        prompt_version=PIPELINE_VERSION,
        model_name=getattr(backend, "model_name", ""),
        created_at=datetime.now(timezone.utc).isoformat(),
        raw_signal_count=len(prepared),
        themes=sorted(records, key=lambda item: -item.stats.comment_count),
        cluster_metadata={
            "embedding_model": getattr(backend, "model_name", ""),
            "embedding_cache_hits": cache_hits,
            "embedding_cache_misses": cache_misses,
            "unclustered_signal_count": len(unclustered),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "per_source_theme_ids": per_source_theme_ids,
        },
        quality_metrics={
            "prepared_signal_count": len(prepared),
            "clustered_signal_count": sum(len(item.included_signal_ids) for item in records),
            "unclustered_signal_count": len(unclustered),
        },
        warnings=["主题标签暂使用确定性关键词 fallback，待启用短 LLM 命名。"],
    )
    quality = validate_theme_document(document, known_signal_ids, known_record_ids)
    document.quality_metrics.update(quality)
    document.warnings.extend(quality["warnings"])
    _write_json(pipeline_dir / "themes_hybrid.json", document.model_dump(mode="json"))
    return document
