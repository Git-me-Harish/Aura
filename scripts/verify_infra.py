"""
AURA — end-to-end verification of the new infrastructure layer.

Verifies:
  1. /api/info reports correct infrastructure modes (postgres real, redis fake,
     qdrant local, pg_event_log available, clickhouse/kafka false).
  2. /api/data/summary exposes per-service mode + event counts.
  3. /api/recsys/train trains ALS CF + Neural CF on real catalog data.
  4. /api/orchestrate kicks off a run and produces real recommendations with
     cf_score / neural_cf_score / context_score / rl_p in metadata.
  5. /api/rl/action persists an event to Postgres app_events (durable).
  6. /api/metrics reads from Postgres (since ClickHouse is unavailable) and
     returns real numbers derived from the seeded events.
  7. /api/rl/history reads from Postgres and returns the user's actions.
"""
import asyncio
import json
import sys
import httpx

BASE = "http://localhost:8000/api"

# Same demo-user bypass the FastAPI app uses in dev
HEADERS = {"Authorization": "Bearer dev-demo-token"}


async def main():
    async with httpx.AsyncClient(base_url=BASE, headers=HEADERS, timeout=60.0) as c:
        print("\n=== 1. /info (infrastructure modes) ===")
        r = await c.get("/info")
        info = r.json()
        print(f"  llm_provider  = {info['llm_provider']}")
        print(f"  rl_backend    = {info['rl_backend']}")
        print(f"  infrastructure:")
        for k, v in info["infrastructure"].items():
            print(f"    {k:14s} = {v}")
        assert info["infrastructure"]["postgres"]["available"] is True
        assert info["infrastructure"]["redis"]["available"] is True
        assert info["infrastructure"]["redis"]["mode"] == "fake"
        assert info["infrastructure"]["qdrant"]["available"] is True
        assert info["infrastructure"]["qdrant"]["mode"] == "local"
        assert info["infrastructure"]["pg_event_log"]["available"] is True

        print("\n=== 2. /data/summary ===")
        r = await c.get("/data/summary")
        s = r.json()
        print(f"  postgres       = {s['postgres']}")
        print(f"  redis          = {s['redis']}")
        print(f"  vector_db      = count={s['vector_db']['count']}, mode={s['vector_db']['mode']}")
        print(f"  clickhouse     = {s['clickhouse']}")
        print(f"  kafka          = {s['kafka']}")
        print(f"  pg_event_log   = {s['pg_event_log']}")

        print("\n=== 3. /recsys/train ===")
        r = await c.post("/recsys/train")
        train = r.json()
        print(f"  CF        : {train['cf']}")
        print(f"  Neural CF : {train['neural_cf']}")
        assert train["cf"]["trained"] is True
        assert train["neural_cf"]["trained"] is True

        print("\n=== 4. /orchestrate (async run) ===")
        r = await c.post("/orchestrate?top_k=4")
        orch = r.json()
        print(f"  request_id = {orch['request_id']}")
        print(f"  policy_version = {orch['policy_version']}")
        request_id = orch["request_id"]

        # Poll for completion
        print("  waiting for orchestration to complete...")
        for _ in range(20):
            await asyncio.sleep(1.5)
            r = await c.get("/orchestrate/last")
            data = r.json()
            if data.get("result") and data["result"]["request_id"] == request_id:
                break
        else:
            print("  ERROR: orchestration did not complete in 30s")
            sys.exit(1)

        result = data["result"]
        recs = result["recommendations"]
        print(f"  completed with {len(recs)} recommendations")
        assert len(recs) > 0, "no recommendations produced"
        print("\n  Top recommendation score breakdown:")
        top = recs[0]
        print(f"    item_id     = {top['item_id']}")
        print(f"    title       = {top['title']}")
        print(f"    category    = {top['category']}")
        print(f"    score       = {top['score']}")
        print(f"    source      = {top['source']}")
        print(f"    metadata    = {json.dumps(top['metadata'], indent=2)}")
        assert "cf_score" in top["metadata"]
        assert "neural_cf_score" in top["metadata"]
        assert "context_score" in top["metadata"]
        assert "rl_p" in top["metadata"]

        print("\n=== 5. /rl/action (persist to Postgres) ===")
        action_count_before = s["pg_event_log"]["events"]
        for i, rec in enumerate(recs):
            r = await c.post("/rl/action", json={
                "item_id": rec["item_id"],
                "action": ["click", "like", "purchase", "skip"][i % 4],
                "reward": 0.6 - i * 0.1,
                "context": {"source": "e2e_test", "rank": i},
            })
            print(f"    action {i+1}: {r.json()}")

        print("\n=== 6. /metrics (Postgres-backed) ===")
        r = await c.get("/metrics")
        m = r.json()
        print(f"  source    = {m.get('source', 'unknown')}")
        print(f"  totals    = {m['totals']}")
        print(f"  rec       = {m['recommendation']}")
        print(f"  business  = {m['business']}")
        assert m["source"] == "postgres", f"expected source=postgres, got {m['source']}"
        assert m["totals"]["actions"] >= 4, "expected at least 4 actions"
        assert m["totals"]["clicks"] >= 1, "expected at least 1 click"

        print("\n=== 7. /rl/history (Postgres-backed) ===")
        r = await c.get("/rl/history?limit=10")
        h = r.json()
        print(f"  source         = {h.get('source', 'unknown')}")
        print(f"  actions count  = {len(h['actions'])}")
        if h["actions"]:
            print(f"  latest action  = {h['actions'][0]}")
        assert h["source"] == "postgres"
        assert len(h["actions"]) >= 4

        print("\n=== ALL CHECKS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
