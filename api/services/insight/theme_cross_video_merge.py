"""Deterministic cross-video merge candidates for hybrid themes."""

from __future__ import annotations

from typing import Iterable, List, Tuple

import numpy as np


HIGH_CONFIDENCE_SIMILARITY = 0.90
AMBIGUOUS_SIMILARITY = 0.82


def merge_candidates(centroids: dict[str, Iterable[float]]) -> tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """Return high-confidence automatic edges and ambiguous review edges."""
    ids = sorted(centroids)
    automatic, ambiguous = [], []
    for index, left in enumerate(ids):
        a = np.asarray(list(centroids[left]), dtype=np.float32)
        for right in ids[index + 1 :]:
            b = np.asarray(list(centroids[right]), dtype=np.float32)
            similarity = float(a @ b / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-12))
            if similarity >= HIGH_CONFIDENCE_SIMILARITY:
                automatic.append((left, right))
            elif similarity >= AMBIGUOUS_SIMILARITY:
                ambiguous.append((left, right))
    return automatic, ambiguous
