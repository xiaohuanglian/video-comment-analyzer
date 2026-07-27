"""Per-video deterministic local clustering for the hybrid theme pipeline."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, List, Sequence

import numpy as np

from .theme_signal_preprocess import PreparedThemeSignal


def dynamic_min_cluster_size(count: int) -> int:
    if count < 500:
        return 5
    if count < 2000:
        return 8
    if count <= 6000:
        return 12
    return 15


def cluster_video_signals(
    video_id: str,
    signals: Sequence[PreparedThemeSignal],
    embeddings: np.ndarray,
    *,
    min_samples: int = 3,
) -> Dict:
    """PCA + HDBSCAN. Small samples intentionally remain unclustered."""
    if len(signals) != len(embeddings):
        raise ValueError("embedding 数量与准备信号数量不一致")
    if len(signals) < dynamic_min_cluster_size(len(signals)):
        labels = np.full(len(signals), -1, dtype=int)
    else:
        try:
            from sklearn.decomposition import PCA
            import hdbscan
        except ImportError as exc:
            raise RuntimeError(
                "Hybrid 本地聚类需要 embedding 依赖。请执行：uv sync --extra embedding"
            ) from exc
        dimensions = min(50, len(signals) - 1, embeddings.shape[1])
        reduced = PCA(n_components=dimensions, random_state=42).fit_transform(embeddings)
        labels = hdbscan.HDBSCAN(
            min_cluster_size=dynamic_min_cluster_size(len(signals)),
            min_samples=min_samples,
            cluster_selection_method="eom",
            allow_single_cluster=False,
        ).fit_predict(reduced)

    members: Dict[int, List[int]] = defaultdict(list)
    for index, label in enumerate(labels.tolist()):
        if label >= 0:
            members[label].append(index)
    clusters = []
    for label, indexes in sorted(members.items()):
        vector = embeddings[indexes]
        centroid = np.average(
            vector,
            axis=0,
            weights=np.asarray([max(1, signals[i].frequency) for i in indexes]),
        )
        centroid /= max(np.linalg.norm(centroid), 1e-12)
        similarity = vector @ centroid
        order = sorted(indexes, key=lambda i: float(embeddings[i] @ centroid), reverse=True)
        representative = order[:2]
        frequency_top = max(indexes, key=lambda i: signals[i].frequency)
        if frequency_top not in representative:
            representative.append(frequency_top)
        clusters.append(
            {
                "cluster_id": f"{video_id}_c{label:03d}",
                "member_indexes": indexes,
                "signal_ids": [sid for i in indexes for sid in signals[i].signal_ids],
                "record_ids": list(dict.fromkeys(rid for i in indexes for rid in signals[i].record_ids)),
                "representative_indexes": representative[:5],
                "signal_count": len(indexes),
                "weighted_frequency": sum(signals[i].frequency for i in indexes),
                "user_count": len(set().union(*(signals[i].user_keys for i in indexes))),
                "signal_type_distribution": dict(Counter(signals[i].signal_type for i in indexes)),
                "cohesion_score": round(float(np.mean(similarity)), 4),
                "centroid": centroid.astype(np.float32).tolist(),
            }
        )
    return {
        "video_id": video_id,
        "cluster_config": {"min_cluster_size": dynamic_min_cluster_size(len(signals)), "min_samples": min_samples},
        "clusters": clusters,
        "unclustered_indexes": [i for i, label in enumerate(labels.tolist()) if label < 0],
    }
