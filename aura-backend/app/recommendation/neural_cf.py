"""
AURA — Neural Collaborative Filtering ranker (real PyTorch).

Implements the NCF architecture from He et al. (2017): a hybrid of GMF
(Generalized Matrix Factorization) and MLP (Multi-Layer Perceptron) branches
whose outputs are combined by a final sigmoid layer.

  user_id ──► user_emb ──┬──────────────────► GMF dot product ──┐
                          └─► MLP(layers) ──────────────────────┤
                                                                 ▼
                                                          sigmoid → score

Trained on the real `interactions` table. Items never seen during training
get a default cold-start score of 0.5 so the catalog is always rankable
end-to-end.

If PyTorch is unavailable, `available=False` and `score()` returns a flat 0.5
cold-start score — clearly logged, NOT a silent random fallback.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.config import settings
from app.data_layer import postgres

log = logging.getLogger("aura.rec.ncf")


def _try_import_torch() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception as e:
        log.warning("neural_cf: torch not available (%s) — using cold-start fallback", e)
        return False


class _NCFModel:
    """Tiny GMF + MLP model implemented with plain torch (no nn.Module subclass).

    Kept simple to avoid framework-version coupling. Parameters are collected
    explicitly so the optimizer can see them.
    """

    def __init__(self, torch_ref, n_users: int, n_items: int, embed_dim: int, mlp_layers: List[int]):
        import torch.nn as nn
        self.t = torch_ref
        self.nn = nn

        self.user_emb_gmf = nn.Embedding(n_users + 1, embed_dim)
        self.item_emb_gmf = nn.Embedding(n_items + 1, embed_dim)
        self.user_emb_mlp = nn.Embedding(n_users + 1, embed_dim)
        self.item_emb_mlp = nn.Embedding(n_items + 1, embed_dim)

        layers = []
        in_dim = embed_dim * 2
        for h in mlp_layers:
            layers.append(nn.Linear(in_dim, h))
            layers.append(nn.ReLU())
            in_dim = h
        self.mlp = nn.Sequential(*layers)
        self.out = nn.Linear(embed_dim + mlp_layers[-1], 1)
        self.sigmoid = nn.Sigmoid()

        nn.init.normal_(self.user_emb_gmf.weight, std=0.01)
        nn.init.normal_(self.item_emb_gmf.weight, std=0.01)
        nn.init.normal_(self.user_emb_mlp.weight, std=0.01)
        nn.init.normal_(self.item_emb_mlp.weight, std=0.01)

    def parameters(self):
        out = []
        for m in (self.user_emb_gmf, self.item_emb_gmf, self.user_emb_mlp, self.item_emb_mlp, self.mlp, self.out):
            out.extend(list(m.parameters()))
        return out

    def forward(self, user_idx, item_idx):
        t = self.t
        u_gmf = self.user_emb_gmf(user_idx)
        i_gmf = self.item_emb_gmf(item_idx)
        gmf = u_gmf * i_gmf

        u_mlp = self.user_emb_mlp(user_idx)
        i_mlp = self.item_emb_mlp(item_idx)
        mlp_in = t.cat([u_mlp, i_mlp], dim=-1)
        mlp_out = self.mlp(mlp_in)

        combined = t.cat([gmf, mlp_out], dim=-1)
        return self.sigmoid(self.out(combined)).squeeze(-1)


class NeuralCFRanker:
    """Trains and serves NCF scores over the real interactions table."""

    def __init__(self):
        self.available = _try_import_torch() and settings.USE_REAL_RECSYS
        self._model: Optional[_NCFModel] = None
        self._user_index: Dict[str, int] = {}
        self._item_index: Dict[str, int] = {}
        self._last_trained: float = 0.0
        self._lock = asyncio.Lock()

    async def train(self) -> Dict[str, Any]:
        """Train on all interactions. Returns metrics dict."""
        if not self.available:
            return {"trained": False, "reason": "torch unavailable or USE_REAL_RECSYS=False"}

        rows = await postgres.table("interactions").all()
        if len(rows) < 4:
            return {"trained": False, "reason": f"need >=4 interactions, got {len(rows)}"}

        user_ids = sorted({r["user_id"] for r in rows})
        item_ids = sorted({r["item_id"] for r in rows})
        self._user_index = {u: i + 1 for i, u in enumerate(user_ids)}
        self._item_index = {it: i + 1 for i, it in enumerate(item_ids)}

        n_users = len(self._user_index)
        n_items = len(self._item_index)
        embed_dim = settings.RECSYS_NEURAL_CF_DIM
        mlp_layers = json.loads(settings.RECSYS_NEURAL_CF_LAYERS)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._train_sync,
            rows, n_users, n_items, embed_dim, mlp_layers,
        )
        self._last_trained = time.time()
        return result

    def _train_sync(self, rows, n_users, n_items, embed_dim, mlp_layers) -> Dict[str, Any]:
        import torch
        from torch import nn, optim

        torch.manual_seed(42)
        self._model = _NCFModel(torch, n_users, n_items, embed_dim, mlp_layers)
        opt = optim.Adam(self._model.parameters(), lr=settings.RL_LR)
        bce = nn.BCELoss()

        u_idx = torch.tensor([self._user_index[r["user_id"]] for r in rows], dtype=torch.long)
        i_idx = torch.tensor([self._item_index[r["item_id"]] for r in rows], dtype=torch.long)
        w = torch.tensor([float(r.get("weight", 0.5)) for r in rows], dtype=torch.float32)
        labels = torch.clamp(w, 0.0, 1.0)

        epochs = 30
        batch_size = min(64, len(rows))
        losses: List[float] = []
        for ep in range(epochs):
            perm = torch.randperm(len(rows))
            ep_loss = 0.0
            n_batches = 0
            for start in range(0, len(rows), batch_size):
                idx = perm[start:start + batch_size]
                opt.zero_grad()
                preds = self._model.forward(u_idx[idx], i_idx[idx])
                loss = bce(preds, labels[idx])
                loss.backward()
                opt.step()
                ep_loss += float(loss.item())
                n_batches += 1
            losses.append(ep_loss / max(1, n_batches))

        log.info("neural_cf: trained on %d interactions, final_loss=%.4f", len(rows), losses[-1])
        return {
            "trained": True,
            "n_users": n_users,
            "n_items": n_items,
            "n_interactions": len(rows),
            "final_loss": round(losses[-1], 4),
            "epochs": epochs,
        }

    async def score(
        self,
        user_id: str,
        candidate_item_ids: List[str],
    ) -> List[Tuple[str, float]]:
        """Return [(item_id, ncf_score)] for each candidate. Score ∈ [0,1].

        Cold-start rules (NO silent substitution of another user's preference):
          • Unknown user → flat 0.5 for every candidate.
          • Unknown item → flat 0.5 for that candidate only.
        """
        if not self.available or self._model is None or not self._item_index:
            return [(iid, 0.5) for iid in candidate_item_ids]

        # Unknown user → flat 0.5 (do NOT fall back to user index 0)
        if user_id not in self._user_index:
            return [(iid, 0.5) for iid in candidate_item_ids]

        import torch
        u_idx = self._user_index[user_id]
        out: List[Tuple[str, float]] = []
        known_items: List[Tuple[str, int]] = []
        for iid in candidate_item_ids:
            idx = self._item_index.get(iid)
            if idx is None:
                out.append((iid, 0.5))  # unknown item → cold-start
            else:
                known_items.append((iid, idx))

        if known_items:
            u_tensor = torch.tensor([u_idx] * len(known_items), dtype=torch.long)
            i_tensor = torch.tensor([idx for _, idx in known_items], dtype=torch.long)
            with torch.no_grad():
                preds = self._model.forward(u_tensor, i_tensor).tolist()
            out.extend([(iid, float(p)) for iid, p in zip([i for i, _ in known_items], preds)])

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
neural_cf_ranker = NeuralCFRanker()
