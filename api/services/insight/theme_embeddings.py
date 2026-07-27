"""Local embedding backend and resumable cache for hybrid theme clustering."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Iterable, List, Protocol, Sequence


class ThemeEmbeddingBackend(Protocol):
    model_name: str

    def encode(self, texts: Sequence[str]):
        """Return normalized float32 embeddings."""


def choose_device(requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


class SentenceTransformersBackend:
    def __init__(self, model_name: str, *, device: str = "auto", batch_size: int = 16):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Hybrid 主题管线需要本地 Embedding 依赖。请执行：uv sync --extra embedding"
            ) from exc
        self.model_name = model_name
        self.device = choose_device(device)
        self.batch_size = batch_size
        self._model = SentenceTransformer(model_name, device=self.device)

    def encode(self, texts: Sequence[str]):
        import numpy as np

        return np.asarray(
            self._model.encode(
                list(texts),
                batch_size=self.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )


def embedding_cache_key(model_name: str, text: str, version: str = "v1") -> str:
    payload = f"{model_name}|{version}|{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_or_encode(
    pipeline_dir: Path,
    texts: Sequence[str],
    backend: ThemeEmbeddingBackend,
    *,
    version: str = "v1",
):
    """Return embeddings in text order; append only cache misses with atomic writes."""
    import numpy as np

    pipeline_dir.mkdir(parents=True, exist_ok=True)
    index_path = pipeline_dir / "embedding_index.json"
    matrix_path = pipeline_dir / "embeddings.npy"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    matrix = np.load(matrix_path, mmap_mode="r") if matrix_path.exists() else None
    keys = [embedding_cache_key(backend.model_name, text, version) for text in texts]
    misses = [idx for idx, key in enumerate(keys) if key not in index]
    elapsed_start = time.monotonic()
    if misses:
        encoded = backend.encode([texts[idx] for idx in misses])
        existing = np.asarray(matrix, dtype=np.float32) if matrix is not None else np.empty((0, encoded.shape[1]), dtype=np.float32)
        merged = np.vstack([existing, encoded]).astype(np.float32, copy=False)
        start = len(existing)
        for offset, text_index in enumerate(misses):
            index[keys[text_index]] = start + offset
        tmp_matrix = matrix_path.with_suffix(".tmp.npy")
        np.save(tmp_matrix, merged)
        os.replace(tmp_matrix, matrix_path)
        tmp_index = index_path.with_suffix(".tmp")
        tmp_index.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_index, index_path)
        matrix = merged
    if matrix is None:
        return np.empty((0, 0), dtype=np.float32), {"hits": 0, "misses": 0, "elapsed_seconds": 0.0}
    return np.asarray([matrix[index[key]] for key in keys], dtype=np.float32), {
        "hits": len(texts) - len(misses),
        "misses": len(misses),
        "elapsed_seconds": round(time.monotonic() - elapsed_start, 3),
    }
