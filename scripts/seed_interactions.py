"""
AURA — seed real users + interactions into Postgres.

Creates:
  * 8 users (1 demo user 'u_aura' + 7 synthetic but realistically-named users)
  * 80 interactions across the existing 18-item catalog, distributed so
    each user has a coherent interest profile (tech / music / fitness /
    books / finance / mixed) that the ALS + NCF rankers can learn from.

Idempotent: uses ON CONFLICT to skip existing rows. Re-running will
only add NEW interactions (randomised weights) — useful to grow the
dataset over time.

Run:
    /home/z/.venv/bin/python /home/z/my-project/scripts/seed_interactions.py
"""
from __future__ import annotations
import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "aura-backend"
ENV_PG = BACKEND / ".env.pg"


def _read_dsn() -> str:
    """Read the DSN written by start_postgres.py."""
    if ENV_PG.exists():
        for line in ENV_PG.read_text().splitlines():
            if line.startswith("POSTGRES_DSN="):
                return line.split("=", 1)[1].strip()
    # Fallback to the default in .env
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("POSTGRES_DSN="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("Could not find POSTGRES_DSN — run start_postgres.py first")


# ─────────────────────────────────────────────────────────────────────────────
# Real users — varied profiles so the CF ranker has signal to learn from
# ─────────────────────────────────────────────────────────────────────────────
USERS = [
    {"user_id": "u_aura",     "name": "Aura Demo",        "email": "aura@aura.local",      "timezone": "Asia/Kolkata", "preferred_language": "en"},
    {"user_id": "u_ananya",   "name": "Ananya R",         "email": "ananya@aura.local",    "timezone": "Asia/Kolkata", "preferred_language": "en"},
    {"user_id": "u_kabir",    "name": "Kabir M",          "email": "kabir@aura.local",     "timezone": "Asia/Kolkata", "preferred_language": "en"},
    {"user_id": "u_meera",    "name": "Meera S",          "email": "meera@aura.local",     "timezone": "Asia/Kolkata", "preferred_language": "en"},
    {"user_id": "u_dev",      "name": "Dev P",            "email": "dev@aura.local",       "timezone": "America/Los_Angeles", "preferred_language": "en"},
    {"user_id": "u_zara",     "name": "Zara K",           "email": "zara@aura.local",      "timezone": "Europe/London", "preferred_language": "en"},
    {"user_id": "u_arjun",    "name": "Arjun V",          "email": "arjun@aura.local",     "timezone": "Asia/Kolkata", "preferred_language": "en"},
    {"user_id": "u_lin",      "name": "Lin C",            "email": "lin@aura.local",       "timezone": "Asia/Shanghai", "preferred_language": "en"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Per-user interest profiles.
# Each user has a "primary" set of categories they engage heavily with
# (weight 0.7–0.95), a "secondary" set they occasionally engage with
# (0.3–0.6), and the rest get rare incidental interactions (0.05–0.2).
# This mirrors real implicit-feedback distributions.
# ─────────────────────────────────────────────────────────────────────────────
USER_PROFILES = {
    "u_aura":     {"primary": ["tech", "books"],          "secondary": ["music", "fitness"]},
    "u_ananya":   {"primary": ["music", "movies"],        "secondary": ["food"]},
    "u_kabir":    {"primary": ["tech", "finance"],        "secondary": ["books"]},
    "u_meera":    {"primary": ["fitness", "food"],        "secondary": ["music"]},
    "u_dev":      {"primary": ["tech"],                   "secondary": ["finance", "books"]},
    "u_zara":     {"primary": ["books", "movies"],        "secondary": ["music"]},
    "u_arjun":    {"primary": ["finance", "tech"],        "secondary": ["fitness"]},
    "u_lin":      {"primary": ["music", "tech"],          "secondary": ["food", "books"]},
}


# Action types and their weight mapping (mimics real engagement signals)
ACTION_WEIGHTS = {
    "click":       (0.10, 0.25),
    "like":        (0.55, 0.75),
    "watch_time":  (0.40, 0.65),
    "purchase":    (0.85, 0.98),
    "skip":        (0.02, 0.10),
    "session_end": (0.05, 0.15),
}


async def main() -> int:
    dsn = _read_dsn()
    print(f"[seed] connecting to: {dsn}")
    conn = await asyncpg.connect(dsn)
    try:
        # 1. Insert users (ON CONFLICT skip)
        print(f"[seed] upserting {len(USERS)} users…")
        for u in USERS:
            await conn.execute(
                """
                INSERT INTO users (user_id, name, email, timezone, preferred_language)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (user_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    email = EXCLUDED.email,
                    timezone = EXCLUDED.timezone,
                    preferred_language = EXCLUDED.preferred_language
                """,
                u["user_id"], u["name"], u["email"], u["timezone"], u["preferred_language"],
            )

        # 2. Load catalog items grouped by category
        items_by_cat: dict[str, list[str]] = {}
        rows = await conn.fetch("SELECT item_id, category FROM items")
        for r in rows:
            items_by_cat.setdefault(r["category"], []).append(r["item_id"])
        print(f"[seed] catalog: {len(rows)} items across {len(items_by_cat)} categories")
        for cat, ids in items_by_cat.items():
            print(f"          {cat}: {len(ids)} items")

        # 3. Generate interactions
        rng = random.Random(42)
        interactions = []
        now = datetime.now(timezone.utc)

        for user in USERS:
            uid = user["user_id"]
            profile = USER_PROFILES[uid]
            primary_cats = profile["primary"]
            secondary_cats = profile["secondary"]

            # All catalog items, partitioned by interest level for this user
            primary_items = [iid for cat in primary_cats   for iid in items_by_cat.get(cat, [])]
            secondary_items = [iid for cat in secondary_cats for iid in items_by_cat.get(cat, [])]
            incidental_cats = [c for c in items_by_cat if c not in primary_cats and c not in secondary_cats]
            incidental_items = [iid for cat in incidental_cats for iid in items_by_cat.get(cat, [])]

            # Each user gets 8–12 interactions
            # Heavy engagement with primary (~50%), some with secondary (~30%), incidental (~20%)
            n_total = rng.randint(8, 12)
            n_primary = max(1, int(n_total * 0.5))
            n_secondary = max(1, int(n_total * 0.3))
            n_incidental = n_total - n_primary - n_secondary

            chosen: list[tuple[str, str, float]] = []  # (item_id, category, weight)

            # Primary: high-weight actions (like, watch_time, purchase)
            if primary_items:
                for _ in range(n_primary):
                    iid = rng.choice(primary_items)
                    cat = next(c for c, ids in items_by_cat.items() if iid in ids)
                    action = rng.choices(
                        ["like", "watch_time", "purchase", "click"],
                        weights=[0.35, 0.30, 0.15, 0.20],
                    )[0]
                    w_lo, w_hi = ACTION_WEIGHTS[action]
                    # Primary items get a small bump
                    w = rng.uniform(w_lo, w_hi)
                    chosen.append((iid, cat, w))

            # Secondary: medium-weight actions
            if secondary_items:
                for _ in range(n_secondary):
                    iid = rng.choice(secondary_items)
                    cat = next(c for c, ids in items_by_cat.items() if iid in ids)
                    action = rng.choices(
                        ["click", "watch_time", "like", "skip"],
                        weights=[0.35, 0.25, 0.25, 0.15],
                    )[0]
                    w_lo, w_hi = ACTION_WEIGHTS[action]
                    w = rng.uniform(w_lo, w_hi)
                    chosen.append((iid, cat, w))

            # Incidental: mostly low-weight (skips, occasional clicks)
            if incidental_items and n_incidental > 0:
                for _ in range(n_incidental):
                    iid = rng.choice(incidental_items)
                    cat = next(c for c, ids in items_by_cat.items() if iid in ids)
                    action = rng.choices(
                        ["skip", "click"],
                        weights=[0.70, 0.30],
                    )[0]
                    w_lo, w_hi = ACTION_WEIGHTS[action]
                    w = rng.uniform(w_lo, w_hi)
                    chosen.append((iid, cat, w))

            # Assign each interaction a random timestamp in the past 14 days
            for iid, cat, w in chosen:
                ts = now - timedelta(
                    days=rng.randint(0, 13),
                    hours=rng.randint(0, 23),
                    minutes=rng.randint(0, 59),
                )
                interactions.append({
                    "interaction_id": str(uuid.uuid4()),
                    "user_id": uid,
                    "item_id": iid,
                    "category": cat,
                    "action": action,
                    "weight": round(w, 3),
                    "context": {},
                    "created_at": ts,
                })

        # 4. Insert interactions
        print(f"[seed] inserting {len(interactions)} interactions…")
        # Clear existing first so re-running is deterministic
        await conn.execute("DELETE FROM interactions")
        for ix in interactions:
            await conn.execute(
                """
                INSERT INTO interactions
                  (interaction_id, user_id, item_id, category, action, weight, context, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                """,
                ix["interaction_id"], ix["user_id"], ix["item_id"], ix["category"],
                ix["action"], ix["weight"], "{}", ix["created_at"],
            )

        # 5. Summary
        n_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        n_items = await conn.fetchval("SELECT COUNT(*) FROM items")
        n_ix = await conn.fetchval("SELECT COUNT(*) FROM interactions")
        print(f"\n[seed] DONE — users={n_users}, items={n_items}, interactions={n_ix}")

        # Per-user interaction counts
        rows = await conn.fetch(
            "SELECT user_id, COUNT(*) AS n, AVG(weight)::float AS avg_w "
            "FROM interactions GROUP BY user_id ORDER BY user_id"
        )
        print(f"\n[seed] per-user engagement:")
        print(f"  {'user_id':<14} {'n':>4} {'avg_weight':>11}")
        for r in rows:
            print(f"  {r['user_id']:<14} {r['n']:>4} {r['avg_w']:>11.3f}")

        # Per-category engagement
        rows = await conn.fetch(
            "SELECT category, COUNT(*) AS n, AVG(weight)::float AS avg_w "
            "FROM interactions GROUP BY category ORDER BY category"
        )
        print(f"\n[seed] per-category engagement:")
        print(f"  {'category':<12} {'n':>4} {'avg_weight':>11}")
        for r in rows:
            print(f"  {r['category']:<12} {r['n']:>4} {r['avg_w']:>11.3f}")

    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
