"""
AURA — Collaborative Filtering ranker (ALS via `implicit`).

Why `implicit` instead of LightFM:
  * LightFM 1.17 has a broken `setup.py` on Python 3.12 (AttributeError
    on `__LIGHTFM_SETUP__`) — the package no longer builds from source.
  * `implicit` ships prebuilt wheels, has a simpler API, and gives us
    ALS (Alternating Least Squares) which is the de-facto industry
    baseline for implicit-feedback CF. Same purpose, less ceremony.

Loss: implicit ALS with confidence weighting on interaction weights.
Trains on the real `interactions` table. Cold-start (unseen user or
item) returns a flat 0.5 — clearly logged, NOT a random fallback.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.sparse import coo_matrix

from app.config import settings
from app.data_layer import postgres

log = logging.getLogger("aura.rec.cf")


def _try_import_implicit() -> bool:
    try:
        from implicit.als import AlternatingLeastSquares  # noqa: F401
        return True
    except Exception as e:
        log.warning("cf: implicit not available (%s) — using cold-start fallback", e)
        return False


class CFRanker:
    """ALS-based collaborative filter over the real interactions table."""

    def __init__(self):
        self.available = _try_import_implicit() and settings.USE_REAL_RECSYS
        self._model = None
        self._user_id_map: Dict[str, int] = {}
        self._item_id_map: Dict[str, int] = {}
        self._last_trained: float = 0.0
        self._lock = asyncio.Lock()

    async def train(self) -> Dict[str, Any]:
        if not self.available:
            return {"trained": False, "reason": "implicit unavailable or USE_REAL_RECSYS=False"}

        rows = await postgres.table("interactions").all()
        if len(rows) < 4:
            return {"trained": False, "reason": f"need >=4 interactions, got {len(rows)}"}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._train_sync, rows)
        self._last_trained = time.time()
        return result

    def _train_sync(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        from implicit.als import AlternatingLeastSquares
        from implicit.nearest_neighbours import bm25_weight

        # Build user/item vocab from real interactions
        user_ids = sorted({r["user_id"] for r in rows})
        item_ids = sorted({r["item_id"] for r in rows})
        self._user_id_map = {u: i for i, u in enumerate(user_ids)}
        self._item_id_map = {it: i for i, it in enumerate(item_ids)}

        n_users, n_items = len(user_ids), len(item_ids)

        # Build sparse user×item matrix; weight = positive signal (clamped >= 0)
        u_idx = [self._user_id_map[r["user_id"]] for r in rows]
        i_idx = [self._item_id_map[r["item_id"]] for r in rows]
        data = np.array(
            [max(0.0, float(r.get("weight", 0.5))) for r in rows],
            dtype=np.float32,
        )
        interactions = coo_matrix(
            (data, (u_idx, i_idx)), shape=(n_users, n_items), dtype=np.float32
        ).tocsr()

        # BM25-style confidence weighting — standard for implicit ALS
        weighted = bm25_weight(interactions, K1=100, B=0.8).tocsr()

        # Train ALS. implicit v0.7+ API: fit(user_items) — shape (n_users, n_items).
        self._model = AlternatingLeastSquares(
            factors=settings.RECSYS_CF_FACTORS,
            iterations=settings.RECSYS_CF_EPOCHS,
            regularization=0.01,
            use_cg=True,
            use_gpu=False,
            random_state=42,
        )
        self._model.fit(weighted)

        log.info("cf: ALS trained on %d interactions, %d users, %d items",
                 len(rows), n_users, n_items)
        return {
            "trained": True,
            "n_users": n_users,
            "n_items": n_items,
            "n_interactions": len(rows),
            "factors": settings.RECSYS_CF_FACTORS,
            "epochs": settings.RECSYS_CF_EPOCHS,
        }

    async def score(
        self,
        user_id: str,
        candidate_item_ids: List[str],
    ) -> List[Tuple[str, float]]:
        """Return [(item_id, score)] with scores in [0, 1].

        Cold-start (unknown user or item) returns 0.5 for that candidate.
        """
        if not self.available or self._model is None or user_id not in self._user_id_map:
            return [(iid, 0.5) for iid in candidate_item_ids]

        u_idx = self._user_id_map[user_id]
        # Map candidate items; unknown items get cold-start 0.5
        known: List[Tuple[str, int]] = []
        out: List[Tuple[str, float]] = []
        for iid in candidate_item_ids:
            idx = self._item_id_map.get(iid)
            if idx is None:
                out.append((iid, 0.5))
            else:
                known.append((iid, idx))

        if known:
            loop = asyncio.get_event_loop()
            user_factors = self._model.user_factors[u_idx]
            item_factors = self._model.item_factors[[idx for _, idx in known]]
            raw = item_factors @ user_factors
            # Sigmoid → [0, 1]; ALS dot products are unbounded
            scores = 1.0 / (1.0 + np.exp(-raw))
            out.extend([(iid, float(s)) for iid, s in zip([i for i, _ in known], scores)])

        # Preserve original candidate order
        order = {iid: i for i, iid in enumerate(candidate_item_ids)}
        out.sort(key=lambda x: order[x[0]])
        return out

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    @property
    def last_trained_at(self) -> float:
        return self._last_trained


# Singleton
cf_ranker = CFRanker()
