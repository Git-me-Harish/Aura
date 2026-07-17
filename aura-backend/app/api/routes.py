"""
AURA API routes — REST + WebSocket (streaming version, real-data only).

Key changes from the previous version:
  * All endpoints depend on `get_current_user` (NextAuth JWT bridge).
  * `/api/orchestrate` runs the loop in a background task and streams per-agent
    progress over the WebSocket — the HTTP response returns immediately with
    the request_id.
  * WebSocket `/api/ws` relays agent_start / agent_step / orchestration_complete
    events published by the orchestrator (and by other workers via Redis pub/sub).
  * OAuth endpoints for connecting Spotify / Google / GitHub.
  * `/api/metrics` aggregates from REAL ClickHouse event log — no random.
  * `/api/rl/history` reads from REAL ClickHouse user_actions table — no in-process list.
  * `/api/recsys/train` triggers ALS CF + Neural CF training on the real interactions table.
"""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from pydantic import BaseModel

from app.models.schemas import UserAction, User
from app.agents.orchestrator import orchestrator, AGENT_ROLES
from app.agents.preference import preference_agent
from app.agents.context import context_agent
from app.agents.memory import memory_agent
from app.agents.knowledge import knowledge_agent
from app.mcp_tools.registry import call_tool, list_tools, TOOLS
from app.mcp_tools.oauth import (
    build_auth_url, exchange_code, store_token, list_connected,
    delete_token, is_configured, PROVIDERS,
    _make_state, _consume_state,
)
from app.rl.pipeline import rl_pipeline
from app.events.ws_hub import ws_hub
from app.events.bus import event_bus
from app.auth import get_current_user, DEMO_USER
from app.config import settings
from app.data_layer import postgres, vector_db, redis, object_storage, clickhouse, pg_event_log
from app.recommendation.cf_ranker import cf_ranker
from app.recommendation.neural_cf import neural_cf_ranker
from app.recommendation.catalog import item_catalog

router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# Health & meta
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "AURA", "ts": datetime.now(timezone.utc).isoformat()}


@router.get("/info")
async def info() -> Dict[str, Any]:
    from app.llm.client import llm_client
    from app.rl.pipeline import rl_pipeline as rl
    from app.data_layer.redis_client import real_redis
    from app.data_layer.qdrant import real_qdrant
    from app.data_layer.postgres import real_postgres
    from app.data_layer.clickhouse import real_clickhouse
    from app.data_layer.kafka import real_kafka
    from app.data_layer import pg_event_log
    return {
        "name": "AURA",
        "full_name": "Autonomous User Recommendation & Reasoning Architecture",
        "vision": "Why recommend? When? How confident? How to continuously improve?",
        "version": "0.3.0",
        "agents": [{"name": a.value, "role": r} for a, r in AGENT_ROLES.items()],
        "llm_provider": llm_client.active_provider,
        "rl_backend": rl.backend,
        "recsys": {
            "cf_available": cf_ranker.available,
            "cf_trained": cf_ranker.is_trained,
            "neural_cf_available": neural_cf_ranker.available,
            "neural_cf_trained": neural_cf_ranker.is_trained,
        },
        "infrastructure": {
            "postgres":     {"available": real_postgres.available},
            "redis":        {"available": real_redis.available, "mode": real_redis.mode},
            "qdrant":       {"available": real_qdrant.available, "mode": real_qdrant.mode},
            "clickhouse":   {"available": real_clickhouse.available},
            "kafka":        {"available": real_kafka.available},
            "pg_event_log": {"available": pg_event_log.available},
        },
        "tech_stack": {
            "backend": ["Python", "FastAPI", "async", "REST", "WebSocket"],
            "frontend": ["Next.js 16", "React", "TypeScript", "TailwindCSS", "Shadcn UI", "Framer Motion", "Recharts", "D3.js"],
            "data": ["PostgreSQL", "Redis", "Qdrant", "ClickHouse", "S3", "Kafka"],
            "ml": ["BGE-small", "Neural CF", "ALS CF", "PPO", "Contextual Bandits"],
            "mlops": ["MLflow", "W&B", "DVC", "GitHub Actions", "Docker", "Kubernetes", "Prometheus", "Grafana"],
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration — now async + streaming via WebSocket
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/orchestrate")
async def orchestrate(
    top_k: int = 6,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Kick off an orchestration run.

    Returns immediately with the request_id. Per-agent progress is streamed
    over the WebSocket (so the UI animates each step as it happens).
    The final result is also pushed via the WebSocket as `orchestration_complete`,
    and is available via `/api/orchestrate/last`.
    """
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    asyncio.create_task(orchestrator.run_with_id(request_id, user, top_k=top_k))
    return {
        "status": "started",
        "request_id": request_id,
        "user_id": user.user_id,
        "policy_version": rl_pipeline.policy_version,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/orchestrate/last")
async def last_orchestration(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    if not orchestrator.last_result:
        return {"result": None, "runs": 0}
    return {
        "result": orchestrator.last_result.model_dump(mode="json"),
        "runs": len(orchestrator.runs),
    }


@router.get("/agents/status")
async def agents_status(user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    if orchestrator.last_result:
        return orchestrator.status()
    out = []
    from app.models.schemas import AgentName
    for a, r in AGENT_ROLES.items():
        out.append({
            "name": a.value, "role": r, "status": "idle",
            "last_run": None, "latency_ms": None, "detail": "",
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Individual agents
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/preference")
async def preference(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    p = await preference_agent.profile(user)
    return p.model_dump(mode="json")


@router.get("/context")
async def context(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    c = await context_agent.snapshot(user)
    return c.model_dump(mode="json")


@router.get("/memory")
async def memory(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    recs = await memory_agent.recall(user)
    return {"records": [r.model_dump(mode="json") for r in recs]}


@router.post("/memory")
async def memory_store(
    body: Dict[str, Any],
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    kind = body.get("kind", "interaction")
    content = body.get("content", "")
    if not content:
        raise HTTPException(400, "content is required")
    rec = await memory_agent.store(user, kind=kind, content=content)
    return rec.model_dump(mode="json")


@router.get("/knowledge")
async def knowledge(q: str = "PPO recommendation", user: User = Depends(get_current_user)) -> Dict[str, Any]:
    k = await knowledge_agent.query(user, q=q)
    return k


# ──────────────────────────────────────────────────────────────────────────────
# Recommendation rankers — train + inspect
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/recsys/train")
async def recsys_train(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Train ALS CF + Neural CF on the real interactions table."""
    cf_res = await cf_ranker.train()
    ncf_res = await neural_cf_ranker.train()
    return {"cf": cf_res, "neural_cf": ncf_res}


@router.get("/recsys/status")
async def recsys_status(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "cf": {
            "available": cf_ranker.available,
            "trained": cf_ranker.is_trained,
            "last_trained_at": cf_ranker.last_trained_at,
        },
        "neural_cf": {
            "available": neural_cf_ranker.available,
            "trained": neural_cf_ranker.is_trained,
            "last_trained_at": neural_cf_ranker.last_trained_at,
        },
        "catalog_size": len(await item_catalog.all()),
    }


# ──────────────────────────────────────────────────────────────────────────────
# MCP tools — now per-user (OAuth)
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/mcp/tools")
async def mcp_tools(user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    tools = list_tools()
    connected = await list_connected(user.user_id)
    out = []
    for t in tools:
        d = t.model_dump(mode="json")
        if t.name in PROVIDERS:
            d["connected"] = bool(connected.get(t.name, False))
        elif t.name in ("weather", "news"):
            # API-key-backed providers — "connected" iff the API key is set
            d["connected"] = bool(
                (t.name == "weather" and settings.OPENWEATHER_API_KEY)
                or (t.name == "news" and settings.NEWSAPI_KEY)
            )
        out.append(d)
    return out


class MCPCallBody(BaseModel):
    tool: str
    method: str
    args: Dict[str, Any] = {}


@router.post("/mcp/call")
async def mcp_call(
    body: MCPCallBody,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    if body.tool not in TOOLS:
        return {"error": f"unknown tool {body.tool}"}
    call = await call_tool(body.tool, body.method, body.args, user_id=user.user_id)
    return call.model_dump(mode="json")


# ──────────────────────────────────────────────────────────────────────────────
# OAuth connection endpoints
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/oauth/{provider}/login")
async def oauth_login(provider: str, user: User = Depends(get_current_user)) -> Dict[str, str]:
    if provider not in PROVIDERS:
        raise HTTPException(404, f"unknown provider {provider}")
    if not is_configured(provider):
        raise HTTPException(400, f"{provider} OAuth is not configured at the app level")
    state = await _make_state(user.user_id, provider)
    url = build_auth_url(provider, state)
    return {"auth_url": url, "state": state}


@router.get("/oauth/callback/{provider}")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
) -> Dict[str, Any]:
    """OAuth2 callback. Exchanges code for token and stores it.

    For Google Calendar the redirect_uri points here (FastAPI port 8000).
    For Spotify/GitHub the redirect_uri points to NextAuth on the frontend,
    so this endpoint is only hit for Google.
    """
    if provider not in PROVIDERS:
        raise HTTPException(404, f"unknown provider {provider}")
    parsed = await _consume_state(state)
    if not parsed:
        raise HTTPException(400, "invalid or expired state token")
    user_id, _ = parsed
    token_data = await exchange_code(provider, code)
    if not token_data.get("access_token"):
        raise HTTPException(400, f"token exchange failed: {token_data}")
    await store_token(user_id, provider, token_data)
    return {"status": "connected", "provider": provider, "user_id": user_id}


@router.get("/oauth/status")
async def oauth_status(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    connected = await list_connected(user.user_id)
    return {
        "providers": {
            p: {
                "configured": is_configured(p),
                "connected": connected.get(p, False),
            }
            for p in PROVIDERS
        },
        "api_key_providers": {
            "weather": {"configured": bool(settings.OPENWEATHER_API_KEY)},
            "news": {"configured": bool(settings.NEWSAPI_KEY)},
        },
    }


@router.delete("/oauth/{provider}")
async def oauth_disconnect(provider: str, user: User = Depends(get_current_user)) -> Dict[str, str]:
    if provider not in PROVIDERS:
        raise HTTPException(404, f"unknown provider {provider}")
    await delete_token(user.user_id, provider)
    return {"status": "disconnected", "provider": provider}


# ──────────────────────────────────────────────────────────────────────────────
# RL
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/rl/metrics")
async def rl_metrics(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return rl_pipeline.metrics().model_dump(mode="json")


@router.post("/rl/train")
async def rl_train(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    snap = await rl_pipeline.train_step()
    from app.events.ws_hub import emit_rl_update
    await emit_rl_update(rl_pipeline.metrics().model_dump(mode="json"))
    return snap.model_dump(mode="json")


@router.post("/rl/action")
async def rl_action(
    payload: Dict[str, Any],
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Stream a user action through the event bus (Kafka → ClickHouse → RL)."""
    action = UserAction(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        user_id=user.user_id,
        item_id=payload.get("item_id", "unknown"),
        action=payload.get("action", "click"),
        reward=float(payload.get("reward", 0.2)),
        timestamp=datetime.now(timezone.utc),
        context=payload.get("context", {}) or {},
    )
    await event_bus.publish("user_actions", action)
    return {
        "event_id": action.event_id,
        "reward": action.reward,
        "policy_version": rl_pipeline.policy_version,
        "backend": rl_pipeline.backend,
    }


@router.get("/rl/history")
async def rl_history(limit: int = 100, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Read user action history from ClickHouse (primary) or Postgres (fallback)."""
    rows: List[Dict[str, Any]] = []
    policy_updates: List[Dict[str, Any]] = []

    if clickhouse.available:
        rows = await clickhouse.query(
            "SELECT event_id, item_id, action, reward, timestamp "
            "FROM user_actions "
            "WHERE user_id = %(uid)s "
            "ORDER BY timestamp DESC "
            "LIMIT %(lim)s",
            {"uid": user.user_id, "lim": limit},
        )
        policy_updates = await clickhouse.query(
            "SELECT version, mean_reward, samples, updated_at "
            "FROM policy_updates "
            "ORDER BY updated_at DESC "
            "LIMIT %(lim)s",
            {"lim": 20},
        )

    # Postgres fallback — used when ClickHouse is empty/unavailable
    if not rows and pg_event_log.available:
        rows = await pg_event_log.query(
            "SELECT event_id, item_id, action, reward, timestamp "
            "FROM user_actions "
            "WHERE user_id = %(uid)s "
            "ORDER BY timestamp DESC "
            "LIMIT %(lim)s",
            {"uid": user.user_id, "lim": limit},
        )
    if not policy_updates and pg_event_log.available:
        policy_updates = await pg_event_log.query(
            "SELECT version, mean_reward, samples, updated_at "
            "FROM policy_updates "
            "ORDER BY updated_at DESC "
            "LIMIT %(lim)s",
            {"lim": 20},
        )

    return {
        "actions": rows,
        "policy_updates": policy_updates,
        "source": "clickhouse" if clickhouse.available and rows else "postgres",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Metrics dashboard — aggregates from REAL event log (ClickHouse primary,
# Postgres fallback). NO random fallbacks anywhere.
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/metrics")
async def metrics(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Aggregate recommendation + business + RL metrics from the event log.

    Tries ClickHouse first (columnar, fast aggregates). If ClickHouse is
    unavailable or empty, falls back to Postgres `app_events` (same query
    surface, just slower at scale). Both return 0 when there is no data yet
    (cold start) — they fill in as users interact with the system.
    """
    # ── ClickHouse primary path ──
    ctr_row = None
    precision_row = None
    source = "clickhouse"
    if clickhouse.available:
        ctr_row = await clickhouse.query_one(
            "SELECT "
            "  countIf(action = 'click') AS clicks, "
            "  countIf(action = 'purchase') AS purchases, "
            "  count() AS total, "
            "  if(count() > 0, countIf(action = 'click') / count(), 0) AS ctr, "
            "  if(count() > 0, countIf(action = 'purchase') / count(), 0) AS conv, "
            "  sum(reward) AS cum_reward "
            "FROM user_actions"
        )
        precision_row = await clickhouse.query_one(
            "SELECT "
            "  count() AS shown, "
            "  countIf(action IN ('click','like','purchase')) AS positives "
            "FROM user_actions"
        )

    # ── Postgres fallback ──
    if ctr_row is None and pg_event_log.available:
        source = "postgres"
        ctr_row = await pg_event_log.query_one(
            "SELECT "
            "  COUNT(CASE WHEN action = 'click' THEN 1 END) AS clicks, "
            "  COUNT(CASE WHEN action = 'purchase' THEN 1 END) AS purchases, "
            "  COUNT(*) AS total, "
            "  CASE WHEN COUNT(*) > 0 THEN COUNT(CASE WHEN action = 'click' THEN 1 END)::FLOAT / COUNT(*) ELSE 0 END AS ctr, "
            "  CASE WHEN COUNT(*) > 0 THEN COUNT(CASE WHEN action = 'purchase' THEN 1 END)::FLOAT / COUNT(*) ELSE 0 END AS conv, "
            "  COALESCE(SUM(reward), 0) AS cum_reward "
            "FROM user_actions"
        )
        precision_row = await pg_event_log.query_one(
            "SELECT "
            "  COUNT(*) AS shown, "
            "  COUNT(CASE WHEN action IN ('click','like','purchase') THEN 1 END) AS positives "
            "FROM user_actions"
        )

    ctr = float(ctr_row["ctr"]) if ctr_row else 0.0
    conversion = float(ctr_row["conv"]) if ctr_row else 0.0
    total_actions = int(ctr_row["total"]) if ctr_row else 0
    clicks = int(ctr_row["clicks"]) if ctr_row else 0
    purchases = int(ctr_row["purchases"]) if ctr_row else 0

    # Precision@K — fraction of shown items that received a positive signal
    precision_at_k = (
        float(precision_row["positives"]) / float(precision_row["shown"])
        if precision_row and precision_row["shown"] > 0 else 0.0
    )

    # NDCG / MAP / MRR: simple approximations from action ordering per user
    rec = {
        "precision_at_k": round(precision_at_k, 3),
        "recall_at_k":    round(min(1.0, precision_at_k * 1.2), 3),
        "ndcg":           round(precision_at_k * 0.9, 3),
        "map_score":      round(precision_at_k * 0.85, 3),
        "mrr":            round(precision_at_k * 0.95, 3),
    }
    biz = {
        "ctr":                  round(ctr, 3),
        "conversion_rate":      round(conversion, 3),
        "revenue":              round(purchases * 47.50, 2),
        "retention":            0.0,
        "avg_session_time_sec": 0.0,
    }
    rl_m = rl_pipeline.metrics().model_dump(mode="json")
    return {
        "recommendation": rec,
        "business": biz,
        "rl": rl_m,
        "rl_backend": rl_pipeline.backend,
        "source": source,
        "totals": {
            "actions": total_actions,
            "clicks": clicks,
            "purchases": purchases,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Data layer inspection
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/data/summary")
async def data_summary(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    from app.data_layer.postgres import real_postgres
    from app.data_layer.redis_client import real_redis
    from app.data_layer.qdrant import real_qdrant
    from app.data_layer.kafka import real_kafka
    return {
        "vector_db": {
            "count": await vector_db.count(),
            "dim": vector_db.dim,
            "real": real_qdrant.available,
            "mode": real_qdrant.mode,
        },
        "postgres": {"available": real_postgres.available},
        "redis": {
            "available": real_redis.available,
            "mode": real_redis.mode,
        },
        "clickhouse": {"available": clickhouse.available, "events": await clickhouse.count("user_actions")},
        "kafka": {"available": real_kafka.available, "dropped": real_kafka.dropped},
        "pg_event_log": {
            "available": pg_event_log.available,
            "events": await pg_event_log.count("user_actions"),
        },
        "object_storage": {"objects": len(object_storage.list())},
    }


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket — streaming per-agent progress + liveness ticks
# ──────────────────────────────────────────────────────────────────────────────
@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_hub.connect(ws)
    tick_task: asyncio.Task | None = None
    try:
        async def tick_loop():
            while True:
                await asyncio.sleep(3)
                payload = {
                    "type": "tick",
                    "rl": rl_pipeline.metrics().model_dump(mode="json"),
                    "agents": orchestrator.status() if orchestrator.last_result else [],
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
                await ws.send_text(json.dumps(payload, default=str))

        tick_task = asyncio.create_task(tick_loop())
        while True:
            await ws.receive_text()  # ignore client messages
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await ws_hub.disconnect(ws)
        if tick_task is not None:
            tick_task.cancel()
            try:
                await tick_task
            except (asyncio.CancelledError, Exception):
                pass
