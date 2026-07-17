"""
AURA event bus — durable Postgres log + optional Kafka + ClickHouse streaming.

Flow:
    POST /api/rl/action
        ↓
    event_bus.publish("user_actions", action)
        ↓
    1. pg_event_log.insert_one(...)  — ALWAYS (durable Postgres log)
    2. kafka.produce(...)            — when Kafka is up (multi-consumer fan-out)
    3. clickhouse.insert_one(...)    — when ClickHouse is up (analytical store)
    4. in-process subscribers        — RL ingest task (immediate, in-memory)

The Postgres log is the single source of truth in dev. In prod, ClickHouse
takes over analytical queries (columnar compression, distributed aggregates)
and Kafka serves the cross-service event stream — but the Postgres log
remains as a durable fallback so /api/metrics always has real numbers.

There are NO random fallbacks anywhere. If Postgres is down, the event is
truly lost (logged as error). If only Kafka/ClickHouse is down, the event
still lands in Postgres and surfaces through the metrics endpoints.
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from app.models.schemas import UserAction
from app.data_layer import clickhouse, kafka, pg_event_log
from app.config import settings

log = logging.getLogger("aura.events.bus")


def _now() -> datetime:
    return datetime.now(timezone.utc)


TopicHandler = Callable[[UserAction], Awaitable[None]]


class EventBus:
    """Durable Postgres + optional Kafka/ClickHouse event bus."""

    def __init__(self):
        self._subscribers: Dict[str, List[TopicHandler]] = {}
        self._consumer_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._running = False
        self.total_published = 0

    def subscribe(self, topic: str, handler: TopicHandler) -> None:
        self._subscribers.setdefault(topic, []).append(handler)

    async def publish(self, topic: str, action: UserAction) -> None:
        """Publish to Postgres (always) + Kafka + ClickHouse (when up) + in-process subs."""
        self.total_published += 1
        action_dict = action.model_dump(mode="json")
        ts_str = action.timestamp.isoformat() if isinstance(action.timestamp, datetime) else str(action.timestamp)

        row = {
            "event_id": action.event_id,
            "user_id": action.user_id,
            "item_id": action.item_id,
            "action": action.action,
            "reward": float(action.reward),
            "timestamp": ts_str,
            "context": json.dumps(action.context, default=str) if not isinstance(action.context, str) else action.context,
            "topic": topic,
            "partition_id": 0,
            "offset": 0,
        }

        # 1. Postgres — always (durable local log)
        try:
            await pg_event_log.insert_one("user_actions", row)
        except Exception as e:
            log.error("event_bus: pg_event_log insert failed (%s) — event not durable", e)

        # 2. Kafka produce (key=user_id for partition affinity) — when available
        if topic == "user_actions" and kafka.available:
            try:
                await kafka.produce(
                    settings.KAFKA_TOPIC_USER_ACTIONS,
                    {**action_dict, "topic": topic},
                    key=action.user_id,
                )
            except Exception as e:
                log.debug("event_bus: kafka produce failed (%s)", e)

        # 3. ClickHouse insert (parallel, fire-and-forget) — when available
        if clickhouse.available:
            asyncio.create_task(self._safe_ch_insert("user_actions", row))

        # 4. In-process subscribers (RL ingest always runs from here)
        for h in self._subscribers.get(topic, []):
            try:
                await h(action)
            except Exception as e:
                log.error("in-process subscriber error on topic %s: %s", topic, e)

    async def _safe_ch_insert(self, table: str, row: Dict[str, Any]) -> None:
        try:
            await clickhouse.insert_one(table, row)
        except Exception as e:
            log.debug("event_bus: clickhouse insert failed (%s)", e)

    async def start(self) -> None:
        """Start the Kafka consumer task that feeds the RL pipeline."""
        if self._running:
            return
        self._running = True
        if kafka.available:
            self._stop_event = asyncio.Event()
            self._consumer_task = asyncio.create_task(self._kafka_consumer_loop())
            log.info("event bus: Kafka consumer started (topic=%s, group=%s)",
                     settings.KAFKA_TOPIC_USER_ACTIONS, settings.KAFKA_CONSUMER_GROUP)
        else:
            log.info(
                "event bus: Kafka unavailable — using Postgres log + in-process "
                "subscribers. RL ingestion still works; events are durable via Postgres."
            )
        log.info("event bus started — %d in-process subscribers",
                 sum(len(h) for h in self._subscribers.values()))

    async def stop(self) -> None:
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except (asyncio.CancelledError, Exception):
                pass
            self._consumer_task = None

    async def _kafka_consumer_loop(self) -> None:
        """Consume from Kafka → dispatch to in-process subscribers (RL consumer)."""
        async def _handle(msg: Dict[str, Any]) -> None:
            try:
                action = UserAction(
                    event_id=msg.get("event_id", f"evt_{uuid.uuid4().hex[:8]}"),
                    user_id=msg["user_id"],
                    item_id=msg.get("item_id", "unknown"),
                    action=msg.get("action", "click"),
                    reward=float(msg.get("reward", 0.2)),
                    timestamp=datetime.fromisoformat(msg["timestamp"]) if "timestamp" in msg else _now(),
                    context=msg.get("context", {}) or {},
                )
            except Exception as e:
                log.error("event bus: failed to deserialize action %s: %s", msg, e)
                return
            for h in self._subscribers.get("user_actions", []):
                try:
                    await h(action)
                except Exception as e:
                    log.error("event bus: subscriber error: %s", e)

        await kafka.consume(
            settings.KAFKA_TOPIC_USER_ACTIONS,
            settings.KAFKA_CONSUMER_GROUP,
            _handle,
            stop_event=self._stop_event,
        )


event_bus = EventBus()


# Default consumer: feed the RL pipeline
async def _rl_consumer(action: UserAction) -> None:
    from app.rl.pipeline import rl_pipeline
    await rl_pipeline.ingest_action(action)
    # Broadcast the updated RL metrics to WS subscribers
    try:
        from app.events.ws_hub import emit_rl_update
        await emit_rl_update(rl_pipeline.metrics().model_dump(mode="json"))
    except Exception:
        pass


def register_default_consumers() -> None:
    event_bus.subscribe("user_actions", _rl_consumer)
