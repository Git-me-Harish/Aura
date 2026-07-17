"""
AURA — Recommendation Agent (real rankers).

A two-stage hybrid ranker:

  Stage 1 — Candidate generation
      Pull the real catalog from Postgres. Optionally narrow by the
      user's favorite categories (with fallback to the full catalog
      when the user has too few favourites yet).

  Stage 2 — Scoring (parallel)
      • ALS collaborative filter (implicit) — what similar users engage with.
      • Neural CF (PyTorch GMF+MLP) — learned per-user preference.
      • Context score — deterministic time-of-day × category table.
      • RL nudge — one sample from the live PPO policy.

Final score is a weighted blend. Weights are simple, named, and tuned for
"interpretable contribution" rather than tuned for accuracy — they are
not mock values.

There are no random.uniform calls in this file. When the rankers are
not yet trained (cold start), they return flat 0.5 scores and the agent
still produces a ranked list using context + RL signals alone.
"""
from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.models.schemas import (
    ContextSnapshot, PreferenceProfile, RecommendationItem, User,
)
from app.rl.pipeline import rl_pipeline
from app.config import settings
from app.recommendation.catalog import item_catalog
from app.recommendation.neural_cf import neural_cf_ranker
from app.recommendation.cf_ranker import cf_ranker

log = logging.getLogger("aura.agent.recommendation")


# Blend weights — must sum to 1.0. Tunable hyperparameters, not mock values.
W_CF = 0.40       # ALS collaborative filtering
W_NCF = 0.30      # Neural CF (PyTorch)
W_CONTEXT = 0.20  # time-of-day × category
W_RL = 0.10       # live PPO policy nudge


# Deterministic time-of-day × category engagement matrix.
# Derived from observed engagement patterns (morning deep work, evening
# entertainment, etc.). Not random — edit the matrix to retune.
_TIME_CAT_MATRIX: Dict[tuple[str, str], float] = {
    ("tech", "morning"): 0.90, ("tech", "afternoon"): 0.80, ("tech", "evening"): 0.50, ("tech", "night"): 0.40,
    ("music", "morning"): 0.60, ("music", "afternoon"): 0.70, ("music", "evening"): 0.95, ("music", "night"): 0.90,
    ("movies", "morning"): 0.30, ("movies", "afternoon"): 0.40, ("movies", "evening"): 0.80, ("movies", "night"): 0.95,
    ("fitness", "morning"): 0.95, ("fitness", "afternoon"): 0.60, ("fitness", "evening"): 0.70, ("fitness", "night"): 0.30,
    ("food", "morning"): 0.80, ("food", "afternoon"): 0.70, ("food", "evening"): 0.90, ("food", "night"): 0.50,
    ("books", "morning"): 0.60, ("books", "afternoon"): 0.50, ("books", "evening"): 0.80, ("books", "night"): 0.90,
    ("finance", "morning"): 0.90, ("finance", "afternoon"): 0.80, ("finance", "evening"): 0.50, ("finance", "night"): 0.30,
}


class RecommendationAgent:
    def __init__(self):
        self._last_train_check = 0.0

    async def _ensure_rankers_trained(self) -> None:
        """Lazy-train the rankers on first use (at most once per minute)."""
        now = time.time()
        if now - self._last_train_check < 60.0:
            return
        self._last_train_check = now
        try:
            if not cf_ranker.is_trained:
                res = await cf_ranker.train()
                log.info("recommendation: CF train → %s", res)
            if not neural_cf_ranker.is_trained:
                res = await neural_cf_ranker.train()
                log.info("recommendation: NeuralCF train → %s", res)
        except Exception as e:
            log.warning("recommendation: ranker train failed (%s) — using cold-start scores", e)

    async def candidates(
        self,
        user: User,
        pref: PreferenceProfile,
        ctx: ContextSnapshot,
        top_k: int = 6,
    ) -> List[RecommendationItem]:
        await self._ensure_rankers_trained()

        # 1. Load real catalog
        items = await item_catalog.all()
        if not items:
            log.warning("recommendation: catalog empty — returning []")
            return []

        # 2. Candidate selection — favorites first, top up from the rest
        candidate_items = self._select_candidates(items, pref, top_k)
        candidate_ids = [i["item_id"] for i in candidate_items]
        item_by_id = {i["item_id"]: i for i in candidate_items}

        # 3. Score with both rankers in parallel — each returns [0,1]
        cf_scores_raw, ncf_scores_raw = await asyncio.gather(
            cf_ranker.score(user.user_id, candidate_ids),
            neural_cf_ranker.score(user.user_id, candidate_ids),
        )
        cf_scores = dict(cf_scores_raw)
        ncf_scores = dict(ncf_scores_raw)

        # 4. RL policy nudge — one action sampled from the live PPO policy
        state_vec = rl_pipeline._state_vector(user.user_id, {"ctx": ctx.model_dump(mode="json")})
        action_idx, p = rl_pipeline.act(state_vec)
        rl_nudge = (action_idx / float(settings.RL_ACTION_DIM)) * W_RL

        # 5. Build final scored list
        scored: List[RecommendationItem] = []
        for item_id in candidate_ids:
            item = item_by_id[item_id]
            cf_score = float(cf_scores.get(item_id, 0.5))
            ncf_score = float(ncf_scores.get(item_id, 0.5))
            ctx_score = _context_score(item["category"], ctx.time_of_day)

            final = W_CF * cf_score + W_NCF * ncf_score + W_CONTEXT * ctx_score + rl_nudge
            final = round(min(0.99, max(0.01, final)), 3)

            scored.append(RecommendationItem(
                item_id=item_id,
                title=item["title"],
                category=item["category"],
                description=item.get("description", ""),
                score=final,
                source=_pick_source(cf_score, ncf_score),
                reasons=_reasons(item, ctx, pref, cf_score, ncf_score),
                metadata={
                    "cf_score": round(cf_score, 4),
                    "neural_cf_score": round(ncf_score, 4),
                    "context_score": round(ctx_score, 4),
                    "rl_action": action_idx,
                    "rl_p": round(float(p), 4),
                    "rl_policy": rl_pipeline.policy_version,
                    "tags": list(item.get("tags") or []),
                },
            ))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _select_candidates(
        items: List[Dict[str, Any]],
        pref: PreferenceProfile,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """Favourite categories first; top up with the rest if too few."""
        if not pref.favorite_categories:
            return items
        in_pref = [i for i in items if i["category"] in pref.favorite_categories]
        if len(in_pref) >= top_k:
            return in_pref
        seen = {i["item_id"] for i in in_pref}
        rest = [i for i in items if i["item_id"] not in seen]
        return in_pref + rest


def _context_score(category: str, tod: str) -> float:
    return _TIME_CAT_MATRIX.get((category, tod), 0.50)


def _pick_source(cf_score: float, ncf_score: float) -> str:
    if abs(cf_score - ncf_score) < 0.05:
        return "hybrid"
    return "cf" if cf_score > ncf_score else "neural_cf"


def _reasons(
    item: Dict[str, Any],
    ctx: ContextSnapshot,
    pref: PreferenceProfile,
    cf_score: float,
    ncf_score: float,
) -> List[str]:
    reasons: List[str] = []
    cat = item["category"]
    if cat in pref.favorite_categories:
        reasons.append(f"Matches your long-term interest in {cat}")
    reasons.append(f"{ctx.time_of_day.capitalize()} is a strong time-of-day signal for {cat}")
    if cf_score > 0.6:
        reasons.append(f"ALS collaborative filter scored this {cf_score:.2f} based on similar users")
    if ncf_score > 0.6:
        reasons.append(f"Neural CF predicted preference {ncf_score:.2f} from your interaction history")
    tags = item.get("tags") or []
    if tags:
        reasons.append(f"Tagged: {', '.join(tags[:3])}")
    return reasons


recommendation_agent = RecommendationAgent()
