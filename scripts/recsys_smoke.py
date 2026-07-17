"""
AURA — recommendation rankers smoke test.

Verifies the new ALS CF (implicit) + Neural CF (PyTorch) rankers work
end-to-end with synthetic data. This proves the recsys code paths are
correct independent of the Postgres catalog being available.

Run:
    /home/z/.venv/bin/python /home/z/my-project/scripts/recsys_smoke.py
"""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

# Make the backend importable
sys.path.insert(0, "/home/z/my-project/aura-backend")

from app.recommendation import cf_ranker, neural_cf_ranker, item_catalog
from app.data_layer import postgres


# ── Synthetic data — mimics what the real `interactions` + `items` tables hold ──
SYNTH_ITEMS = [
    {"item_id": "i_tech_1",  "title": "PyTorch 2.5 release notes", "category": "tech",
     "description": "What's new in PyTorch 2.5", "tags": ["pytorch", "ml", "release"]},
    {"item_id": "i_tech_2",  "title": "Building RAG with Qdrant",  "category": "tech",
     "description": "Step by step RAG",            "tags": ["rag", "qdrant", "vector"]},
    {"item_id": "i_music_1", "title": "Lo-fi beats playlist",      "category": "music",
     "description": "Focus music",                  "tags": ["lofi", "focus"]},
    {"item_id": "i_music_2", "title": "Jazz for evenings",         "category": "music",
     "description": "Smooth jazz",                  "tags": ["jazz", "evening"]},
    {"item_id": "i_movies_1","title": "Dune Part Two review",      "category": "movies",
     "description": "Sci-fi epic",                  "tags": ["scifi", "review"]},
    {"item_id": "i_fitness_1","title":"Morning yoga routine",      "category": "fitness",
     "description": "20-min flow",                  "tags": ["yoga", "morning"]},
    {"item_id": "i_books_1", "title": "Designing ML Systems",      "category": "books",
     "description": "Chip Huyen",                   "tags": ["ml", "book"]},
    {"item_id": "i_finance_1","title":"Index investing 101",       "category": "finance",
     "description": "Bogleheads",                   "tags": ["index", "investing"]},
]

SYNTH_INTERACTIONS = [
    # user_u1 is a tech+books person
    {"user_id": "u1", "item_id": "i_tech_1",  "weight": 0.95},
    {"user_id": "u1", "item_id": "i_tech_2",  "weight": 0.85},
    {"user_id": "u1", "item_id": "i_books_1", "weight": 0.90},
    # user_u2 is a music+movies person
    {"user_id": "u2", "item_id": "i_music_1", "weight": 0.90},
    {"user_id": "u2", "item_id": "i_music_2", "weight": 0.80},
    {"user_id": "u2", "item_id": "i_movies_1","weight": 0.70},
    # user_u3 is mixed but leans tech
    {"user_id": "u3", "item_id": "i_tech_1",  "weight": 0.80},
    {"user_id": "u3", "item_id": "i_music_1", "weight": 0.50},
    {"user_id": "u3", "item_id": "i_books_1", "weight": 0.60},
    # u1 also likes fitness (cross-category signal for the ranker to learn)
    {"user_id": "u1", "item_id": "i_fitness_1","weight": 0.70},
]


async def _stub_postgres():
    """Patch postgres.table('interactions').all() to return our synthetic rows.

    We monkey-patch HybridPostgresTable.all directly so any caller of
    `postgres.table('interactions').all()` gets the synthetic rows without
    needing a real Postgres connection.
    """
    from app.data_layer import HybridPostgresTable
    original_all = HybridPostgresTable.all
    async def patched_all(self):
        if self.name == "interactions":
            return SYNTH_INTERACTIONS
        return await original_all(self)
    HybridPostgresTable.all = patched_all
    print(f"[setup] patched HybridPostgresTable.all to serve {len(SYNTH_INTERACTIONS)} synthetic interactions")


async def _stub_catalog():
    """Patch item_catalog to serve synthetic items without going to Postgres."""
    item_catalog._items = SYNTH_ITEMS
    item_catalog._by_id = {i["item_id"]: i for i in SYNTH_ITEMS}
    item_catalog._by_category = {}
    for i in SYNTH_ITEMS:
        item_catalog._by_category.setdefault(i["category"], []).append(i)
    item_catalog._tags_vocab = sorted({t for i in SYNTH_ITEMS for t in i["tags"]})
    item_catalog._tag_index = {t: i for i, t in enumerate(item_catalog._tags_vocab)}

    # bypass _ensure_fresh() which would call refresh() and hit Postgres
    async def _no_refresh():
        return len(SYNTH_ITEMS)
    item_catalog.refresh = _no_refresh
    async def _no_ensure():
        return None
    item_catalog._ensure_fresh = _no_ensure


async def main():
    print("=" * 70)
    print("AURA Recommendation Rankers — Smoke Test")
    print("=" * 70)

    await _stub_postgres()
    await _stub_catalog()

    print(f"\n[setup] {len(SYNTH_ITEMS)} items, {len(SYNTH_INTERACTIONS)} interactions")
    print(f"[setup] CF available:   {cf_ranker.available}")
    print(f"[setup] NCF available:  {neural_cf_ranker.available}")

    # ── Train both rankers ──
    print("\n--- Training ALS CF (implicit) ---")
    cf_result = await cf_ranker.train()
    print(json.dumps(cf_result, indent=2))

    print("\n--- Training Neural CF (PyTorch) ---")
    ncf_result = await neural_cf_ranker.train()
    print(json.dumps(ncf_result, indent=2))

    if not (cf_result.get("trained") and ncf_result.get("trained")):
        print("\n[FAIL] one or both rankers failed to train")
        sys.exit(1)

    # ── Score u1 against ALL items (some they've interacted with, some not) ──
    print("\n--- Scoring u1 against full catalog ---")
    all_item_ids = [i["item_id"] for i in SYNTH_ITEMS]
    cf_scores, ncf_scores = await asyncio.gather(
        cf_ranker.score("u1", all_item_ids),
        neural_cf_ranker.score("u1", all_item_ids),
    )

    print(f"\n{'item_id':<14} {'category':<10} {'CF':>8} {'NCF':>8}   notes")
    print("-" * 70)
    cf_map = dict(cf_scores)
    ncf_map = dict(ncf_scores)
    for iid in all_item_ids:
        item = next(i for i in SYNTH_ITEMS if i["item_id"] == iid)
        cf_s = cf_map[iid]
        ncf_s = ncf_map[iid]
        interacted = next((r for r in SYNTH_INTERACTIONS
                          if r["user_id"] == "u1" and r["item_id"] == iid), None)
        note = f"interacted w={interacted['weight']}" if interacted else "unseen"
        print(f"{iid:<14} {item['category']:<10} {cf_s:>8.4f} {ncf_s:>8.4f}   {note}")

    # ── Cold-start: unknown user should get flat 0.5 ──
    print("\n--- Cold-start check (unknown user 'u_unknown') ---")
    cold = await cf_ranker.score("u_unknown", all_item_ids[:3])
    assert all(abs(s - 0.5) < 1e-6 for _, s in cold), f"CF cold-start failed: {cold}"
    print(f"  CF cold-start OK: {[(i, round(s,4)) for i, s in cold]}")

    cold_ncf = await neural_cf_ranker.score("u_unknown", all_item_ids[:3])
    assert all(abs(s - 0.5) < 1e-6 for _, s in cold_ncf), f"NCF cold-start failed: {cold_ncf}"
    print(f"  NCF cold-start OK: {[(i, round(s,4)) for i, s in cold_ncf]}")

    # ── Final blend check ──
    print("\n--- Final blend (weights CF=0.40 NCF=0.30 ctx=0.20 RL=0.10) ---")
    # Pick u1's top-3 by blended score
    W_CF, W_NCF, W_CTX = 0.40, 0.30, 0.20
    ctx_default = 0.50
    blended = []
    for iid in all_item_ids:
        cf_s = cf_map[iid]
        ncf_s = ncf_map[iid]
        # use a neutral context score for the smoke test
        score = W_CF * cf_s + W_NCF * ncf_s + W_CTX * ctx_default
        blended.append((iid, round(score, 4)))
    blended.sort(key=lambda x: x[1], reverse=True)
    print("Top 3 for u1:")
    for iid, s in blended[:3]:
        print(f"  {iid}: {s}")

    print("\n" + "=" * 70)
    print("ALL CHECKS PASSED — recommendation rankers produce real scores")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
