"""
AURA — Preference Agent (real embeddings + async Postgres, NO mock seed).

Learns user interests, habits, favourite categories and interaction patterns.

Production path:
  - Reads `interactions` table from Postgres (async) — only REAL user data.
  - Computes top categories by weighted frequency from actual interactions.
  - Encodes a long-term preference vector using the real BGE embedder.
  - Persists the profile to `preference_profiles` table + Qdrant.

No INTEREST_POOL, CATEGORY_POOL, PATTERN_POOL, or _seed_interactions. If a
new user has zero interactions, the agent returns an empty profile and the
Recommendation Agent falls back to category-agnostic ranking. There is NO
fabricated seed data.
"""
from __future__ import annotations
import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.models.schemas import PreferenceProfile, User
from app.data_layer import postgres, vector_db
from app.llm.embeddings import embed_text

log = logging.getLogger("aura.agent.preference")


def _now():
    return datetime.now(timezone.utc)


class PreferenceAgent:
    def __init__(self):
        self.users = postgres.table("users")
        self.interactions = postgres.table("interactions")
        self.profiles = postgres.table("preference_profiles")

    async def profile(self, user: User) -> PreferenceProfile:
        # Ensure user exists in our DB (mirrors NextAuth user)
        existing = await self.users.get(user.user_id)
        if existing is None:
            try:
                await self.users.insert(user.user_id, {
                    "user_id": user.user_id,
                    "name": user.name,
                    "email": f"{user.user_id}@aura.local",
                    "timezone": user.timezone,
                    "preferred_language": user.preferred_language,
                })
            except Exception as e:
                log.debug("could not upsert user %s: %s", user.user_id, e)

        # Load REAL interactions
        rows = await self.interactions.where(user_id=user.user_id)

        # Compute weighted category scores from real signal
        cat_scores: Counter = Counter()
        for r in rows:
            cat = r.get("category", "tech")
            w = float(r.get("weight", 0.5))
            cat_scores[cat] += w

        top_interests = [c for c, _ in cat_scores.most_common(5)]
        favorite_categories = list({r.get("category", "tech") for r in rows if r.get("category")})

        # Interaction patterns derived from REAL hour-of-day distribution
        interaction_patterns = self._derive_patterns(rows)

        # Long-term preference embedding (BGE on real text)
        if top_interests:
            profile_text = " ".join(top_interests + favorite_categories)
        else:
            profile_text = f"user {user.user_id} new account no interactions yet"
        long_term_vector = embed_text(profile_text)

        # Persist profile snapshot
        try:
            await self.profiles.insert(user.user_id, {
                "user_id": user.user_id,
                "top_interests": top_interests,
                "favorite_categories": favorite_categories,
                "interaction_patterns": interaction_patterns,
                "long_term_vector": long_term_vector[:32],
                "updated_at": _now(),
            })
        except Exception as e:
            log.info("preference_profiles: could not persist snapshot for %s: %s", user.user_id, e)

        # Also upsert into Qdrant for similarity lookups
        await vector_db.upsert(
            point_id=f"user_pref:{user.user_id}",
            vector=long_term_vector,
            payload={"user_id": user.user_id, "kind": "preference", "interests": top_interests},
        )

        return PreferenceProfile(
            top_interests=top_interests,
            favorite_categories=favorite_categories,
            interaction_patterns=interaction_patterns,
            long_term_vector=long_term_vector[:32],
            updated_at=_now(),
        )

    @staticmethod
    def _derive_patterns(rows: List[Dict[str, Any]]) -> Dict[str, float]:
        """Derive interaction patterns from real interaction timestamps.

        Returns a dict like {"morning_skim": 0.72, "deep_work_blocks": 0.55, ...}
        Computed deterministically from the hour-of-day distribution of the
        user's interactions. Returns {} for users with no interactions.
        """
        if not rows:
            return {}
        hours = []
        for r in rows:
            ts = r.get("created_at")
            if ts is None:
                continue
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                hours.append(ts.hour)
            except Exception:
                continue
        if not hours:
            return {}

        n = len(hours)
        morning = sum(1 for h in hours if 5 <= h < 12) / n
        afternoon = sum(1 for h in hours if 12 <= h < 17) / n
        evening = sum(1 for h in hours if 17 <= h < 21) / n
        night = sum(1 for h in hours if h >= 21 or h < 5) / n

        patterns = {
            "morning_engagement": round(morning, 3),
            "afternoon_engagement": round(afternoon, 3),
            "evening_engagement": round(evening, 3),
            "night_engagement": round(night, 3),
        }
        # Add deep_work_blocks signal — high morning+afternoon concentration
        patterns["deep_work_blocks"] = round(morning + afternoon, 3)
        patterns["evening_discovery"] = round(evening + night, 3)
        return patterns


preference_agent = PreferenceAgent()
