"""
AURA — WebSocket broadcast hub with real Redis pub/sub fan-out.

When AURA runs behind a load balancer with multiple FastAPI workers (or even
multiple replicas), each worker only sees its own WebSocket subscribers. To
broadcast an event to ALL connected clients across ALL workers, every worker:

  1. PUBLISHES every local broadcast to the Redis channel `aura:ws`.
  2. SUBSCRIBES to `aura:ws` and relays received messages to its local
     WebSocket subscribers.

This way a message published by worker A reaches the clients connected to
workers B, C, etc. Redis pub/sub is fire-and-forget (no persistence) so
disconnected clients miss messages — that's acceptable for live UI animation.

If Redis is unavailable, the hub falls back to local-only broadcast (single-
worker mode). There is NO in-memory cross-worker bridge — that would require
a shared bus anyway, which is exactly what Redis is providing.

Message types:
  - {"type": "hello", ...}                         — on connect
  - {"type": "agent_start",  "agent": "...", ...}  — before an agent runs
  - {"type": "agent_step",   "agent": "...", ...}  — after an agent completes
  - {"type": "orchestration_complete", "result": {...}}  — final result
  - {"type": "rl_update",    "rl": {...}}          — RL metrics updated
  - {"type": "tick", ...}                          — periodic 3s liveness ping
"""
from __future__ import annotations
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.data_layer import redis as redis_facade
from app.config import settings

log = logging.getLogger("aura.ws.hub")


WS_CHANNEL = "aura:ws"


class WSHub:
    """In-process WebSocket fan-out + Redis pub/sub bridge for multi-worker."""

    def __init__(self):
        self._subscribers: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._pubsub_task: Optional[asyncio.Task] = None
        self._running = False

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._subscribers.add(ws)
        await ws.send_text(json.dumps({
            "type": "hello",
            "service": "AURA",
            "ts": datetime.now(timezone.utc).isoformat(),
        }))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.discard(ws)

    async def broadcast(self, msg: Dict[str, Any]) -> int:
        """Send to all locally connected WS clients. Returns number reached."""
        text = json.dumps(msg, default=str)
        reached = 0
        dead: List[WebSocket] = []
        for ws in list(self._subscribers):
            try:
                await ws.send_text(text)
                reached += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)
        return reached

    async def publish(self, msg: Dict[str, Any]) -> None:
        """Broadcast locally AND publish to Redis for multi-worker fan-out.

        Other workers pick the message up via the pubsub subscriber task and
        relay it to their own WS subscribers.
        """
        # Local broadcast first (lowest latency for same-worker clients)
        await self.broadcast(msg)
        # Then fan out to other workers via Redis pub/sub
        try:
            await redis_facade.publish(WS_CHANNEL, json.dumps(msg, default=str))
        except Exception as e:
            log.debug("ws: redis publish failed (%s) — multi-worker fan-out skipped", e)

    async def start_pubsub_subscriber(self) -> None:
        """Start the Redis pubsub listener that relays messages from other workers.

        Safe to call multiple times — only starts one task.
        """
        if self._running:
            return
        if not redis_facade.available:
            log.warning("ws: Redis unavailable — running in single-worker mode (no cross-worker fan-out)")
            return
        self._running = True
        self._pubsub_task = asyncio.create_task(self._pubsub_loop())
        log.info("ws: Redis pubsub subscriber started on channel %s", WS_CHANNEL)

    async def stop_pubsub_subscriber(self) -> None:
        self._running = False
        if self._pubsub_task is not None:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except (asyncio.CancelledError, Exception):
                pass
            self._pubsub_task = None

    async def _pubsub_loop(self) -> None:
        """Listen on `aura:ws` and relay received messages to local WS clients.

        Uses the shared `real_redis` client (which auto-routes to fakeredis
        in dev), so the loop works in every environment that has any Redis
        backend available.
        """
        from app.data_layer.redis_client import real_redis
        pubsub = None
        try:
            pubsub = await real_redis.pubsub()
            if pubsub is None:
                log.warning("ws: real_redis.pubsub() returned None — pubsub loop exiting")
                return
            await pubsub.subscribe(WS_CHANNEL)
            log.info("ws: subscribed to Redis channel %s (mode=%s)", WS_CHANNEL, real_redis.mode)
            while self._running:
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    log.warning("ws: pubsub get_message error (%s) — reconnecting in 1s", e)
                    await asyncio.sleep(1.0)
                    continue
                if msg is None:
                    continue
                if msg.get("type") != "message":
                    continue
                data = msg.get("data")
                if not isinstance(data, str):
                    continue
                # Relay to local WS clients (do NOT re-publish to Redis — would loop)
                try:
                    await self.broadcast(json.loads(data))
                except Exception as e:
                    log.debug("ws: relay broadcast failed: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("ws: pubsub loop crashed (%s) — multi-worker fan-out disabled", e)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(WS_CHANNEL)
                    await pubsub.close()
                except Exception:
                    pass

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Singleton
ws_hub = WSHub()


# ──────────────────────────────────────────────────────────────────────────────
# Convenience helpers — used by the orchestrator
# ──────────────────────────────────────────────────────────────────────────────
async def emit_agent_start(agent: str, request_id: str, input_summary: str = "") -> None:
    await ws_hub.publish({
        "type": "agent_start",
        "agent": agent,
        "request_id": request_id,
        "input_summary": input_summary,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


async def emit_agent_step(agent: str, request_id: str, duration_ms: int, output_summary: str = "", artifacts: Optional[Dict[str, Any]] = None) -> None:
    await ws_hub.publish({
        "type": "agent_step",
        "agent": agent,
        "request_id": request_id,
        "duration_ms": duration_ms,
        "output_summary": output_summary,
        "artifacts": artifacts or {},
        "ts": datetime.now(timezone.utc).isoformat(),
    })


async def emit_orchestration_complete(request_id: str, result: Dict[str, Any]) -> None:
    await ws_hub.publish({
        "type": "orchestration_complete",
        "request_id": request_id,
        "result": result,
        "ts": datetime.now(timezone.utc).isoformat(),
    })


async def emit_rl_update(rl_metrics: Dict[str, Any]) -> None:
    await ws_hub.publish({
        "type": "rl_update",
        "rl": rl_metrics,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
