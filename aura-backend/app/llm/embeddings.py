"""
AURA — embeddings layer.

Uses `sentence-transformers` to load BGE-small-en-v1.5 (384-dim, ~130MB, CPU-
friendly) locally. This is fully free — no API key, no network call.

Graceful degradation:
  * If sentence-transformers is not installed OR the model fails to load,
    fall back to a deterministic hash-based pseudo-embedding (same behaviour
    as the original mock `_seed_embedding`).

The model is loaded lazily on first call so the backend starts fast.
"""
from __future__ import annotations
import hashlib
import logging
import threading
from typing import List, Optional

import numpy as np

from app.config import settings

log = logging.getLogger("aura.llm.embed")


class _Embedder:
    def __init__(self, model_name: str, dim: int):
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self._lock = threading.Lock()
        self._tried = False

    def _load(self):
        if self._tried:
            return
        with self._lock:
            if self._tried:
                return
            self._tried = True
            try:
                import os
                import socket

                # Pre-flight: can we actually reach huggingface.co? DNS resolve
                # is not enough — also try a 2s TCP connect. If either fails,
                # skip the model load entirely (HF's default retry policy is 5x
                # with exponential backoff = ~40s blocking).
                if not os.environ.get("HF_HUB_OFFLINE"):
                    try:
                        s = socket.create_connection(("huggingface.co", 443), timeout=2.0)
                        s.close()
                    except Exception:
                        log.warning(
                            "embeddings: huggingface.co unreachable — using hash pseudo-embeddings "
                            "(set HF_HUB_OFFLINE=1 to suppress this probe, or pre-download the model)"
                        )
                        self._model = None
                        return

                from sentence_transformers import SentenceTransformer  # type: ignore
                os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "10")
                self._model = SentenceTransformer(self.model_name, device="cpu")
                _ = self._model.encode(["warmup"], show_progress_bar=False)
                log.info("embeddings: loaded '%s'", self.model_name)
            except Exception as e:
                log.warning(
                    "embeddings: '%s' failed to load (%s) — using hash pseudo-embeddings",
                    self.model_name, e,
                )
                self._model = None

    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode a batch of texts into normalized vectors of length `dim`."""
        self._load()
        if self._model is not None:
            try:
                vecs = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
                out = []
                for v in vecs:
                    if len(v) != self.dim:
                        # pad or truncate to match configured dim
                        if len(v) > self.dim:
                            v = v[: self.dim]
                        else:
                            v = list(v) + [0.0] * (self.dim - len(v))
                    out.append([round(float(x), 5) for x in v])
                return out
            except Exception as e:
                log.warning("embeddings: encode failed (%s) — using hash fallback", e)
        # Fallback: deterministic pseudo-embedding
        return [self._hash_embed(t) for t in texts]

    def encode_one(self, text: str) -> List[float]:
        return self.encode([text])[0]

    def _hash_embed(self, text: str) -> List[float]:
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16) % (2**32)
        rng = np.random.default_rng(seed)
        return [round(float(x), 5) for x in rng.normal(0, 1, self.dim)]


# Singleton — lazy-loaded
_embedder: Optional[_Embedder] = None


def get_embedder() -> _Embedder:
    global _embedder
    if _embedder is None:
        _embedder = _Embedder(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIM)
    return _embedder


# ──────────────────────────────────────────────────────────────────────────────
# Public API — drop-in replacement for the legacy `_seed_embedding`
# ──────────────────────────────────────────────────────────────────────────────
def embed_text(text: str) -> List[float]:
    return get_embedder().encode_one(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    return get_embedder().encode(texts)


# Back-compat: legacy callers called `_seed_embedding(text, dim=384)`
def _seed_embedding(text: str, dim: int = 384) -> List[float]:
    # If configured dim matches dim, use the real embedder; else use hash fallback
    if dim == settings.EMBEDDING_DIM:
        return embed_text(text)
    # Otherwise produce a hash-based pseudo-embedding at the requested dim
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16) % (2**32)
    rng = np.random.default_rng(seed)
    return [round(float(x), 5) for x in rng.normal(0, 1, dim)]
