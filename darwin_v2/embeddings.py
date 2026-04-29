"""Stable local semantic prompt embeddings.

The public interface intentionally matches the original hash implementation:
``HashEmbeddingModel.embed`` returns ``list[float]`` and the cosine helpers
operate on those lists. Internally this now uses sentence-transformers
``all-MiniLM-L6-v2`` for semantic novelty pressure.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
from typing import Any

from darwin_v2.config import DarwinConfig


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_DIMENSION = 384
_MODEL_LOCK = threading.Lock()
_MODEL: Any | None = None


def _load_model() -> Any:
    """Lazy-load the local sentence-transformers model once per process."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL

        random.seed(0)
        try:
            import numpy as np

            np.random.seed(0)
        except Exception:
            pass
        try:
            import torch

            torch.manual_seed(0)
            torch.set_num_threads(1)
        except Exception:
            pass

        from sentence_transformers import SentenceTransformer

        try:
            _MODEL = SentenceTransformer(MODEL_NAME, local_files_only=True)
        except Exception:
            _MODEL = SentenceTransformer(MODEL_NAME)
        return _MODEL


class HashEmbeddingModel:
    """Compatibility wrapper around MiniLM semantic embeddings."""

    def __init__(self, config: DarwinConfig | None = None) -> None:
        self.config = config or DarwinConfig()
        self.dim = MODEL_DIMENSION
        self.cache_dir = self.config.embedding_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"{digest}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())["embedding"]

        model = _load_model()
        embedding = model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vec = [float(value) for value in embedding.tolist()]

        cache_file.write_text(
            json.dumps(
                {
                    "sha256": digest,
                    "model": MODEL_NAME,
                    "dimension": len(vec),
                    "embedding": vec,
                },
                indent=2,
            )
        )
        return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def cosine_distance(a: list[float], b: list[float]) -> float:
    return 1.0 - cosine_similarity(a, b)
