"""Stable offline prompt embeddings.

This intentionally avoids API embeddings during evaluation. The vector is a
deterministic signed hashing projection over normalized tokens. It is not a
semantic embedding model, but it is stable, cached, and good enough for v2's
initial diversity pressure without adding network dependence.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from darwin_v2.config import DarwinConfig


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class HashEmbeddingModel:
    """Deterministic offline embedding wrapper."""

    def __init__(self, config: DarwinConfig | None = None) -> None:
        self.config = config or DarwinConfig()
        self.dim = self.config.embedding_dim
        self.cache_dir = self.config.embedding_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cache_file = self.cache_dir / f"{digest}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())["embedding"]

        vec = [0.0] * self.dim
        for token in TOKEN_RE.findall(text.lower()):
            h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(h[:4], "big") % self.dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        cache_file.write_text(json.dumps({"sha256": digest, "embedding": vec}, indent=2))
        return vec


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def cosine_distance(a: list[float], b: list[float]) -> float:
    return 1.0 - cosine_similarity(a, b)
