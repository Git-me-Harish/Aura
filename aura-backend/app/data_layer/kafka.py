"""
AURA — real Kafka event stream (aiokafka).

Replaces the in-memory `asyncio.Queue` event bus. Every user action is
produced to the `aura.user_actions` topic with partitioning by user_id so
that all events for a single user land on the same partition (preserves
per-user ordering). A background consumer in `events/bus.py` reads from
this topic and feeds the RL pipeline.

If `USE_REAL_KAFKA=False` OR the broker probe fails, the producer becomes
a no-op (logs a warning, increments a dropped counter). The consumer does
not start. The rest of the app MUST NOT fabricate events to substitute.
"""
from __future__ import annotations
import asyncio
import json
import logging
import socket
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from app.config import settings

log = logging.getLogger("aura.data.kafka")


def _broker_reachable(bootstrap: str, timeout: float = 2.0) -> bool:
    """Quick TCP probe to the first broker host:port in the bootstrap list."""
    try:
        host, port = bootstrap.split(",")[0].split(":")
        s = socket.create_connection((host, int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


class RealKafka:
    """Async Kafka producer (consumer is created on-demand in events/bus.py)."""

    def __init__(self):
        self._producer = None
        self.available = False
        self.dropped = 0

    async def connect(self) -> None:
        if self._producer is not None:
            return
        if not settings.USE_REAL_KAFKA:
            log.warning("kafka: USE_REAL_KAFKA=False — events will be dropped")
            return
        if not _broker_reachable(settings.KAFKA_BOOTSTRAP_SERVERS):
            log.warning(
                "kafka: broker %s unreachable — events will be dropped "
                "(start it via `docker compose up kafka`)",
                settings.KAFKA_BOOTSTRAP_SERVERS,
            )
            return
        try:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                enable_idempotence=True,
                acks="all",
                linger_ms=20,
                request_timeout_ms=10000,
            )
            await self._producer.start()
            self.available = True
            log.info("kafka: producer connected to %s", settings.KAFKA_BOOTSTRAP_SERVERS)
            # Best-effort topic provisioning
            await self._ensure_topics()
        except Exception as e:
            log.warning("kafka: producer unavailable (%s) — events will be dropped", e)
            self._producer = None
            self.available = False

    async def _ensure_topics(self) -> None:
        """Create the standard AURA topics if they don't exist."""
        try:
            from aiokafka.admin import AIOKafkaAdminClient
            from aiokafka.errors import TopicAlreadyExistsError
            admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
            await admin.start()
            try:
                topics = await admin.list_topics()
                new_topics = []
                for name in (settings.KAFKA_TOPIC_USER_ACTIONS, settings.KAFKA_TOPIC_WS_EVENTS):
                    if name not in topics:
                        new_topics.append(
                            type("Topic", (), {
                                "name": name,
                                "num_partitions": settings.KAFKA_TOPIC_PARTITIONS,
                                "replication_factor": settings.KAFKA_TOPIC_REPLICATION,
                                "replica_assignments": [],
                                "topic_configs": {},
                            })()
                        )
                if new_topics:
                    try:
                        await admin.create_topics(new_topics)
                        log.info("kafka: created topics %s", [t.name for t in new_topics])
                    except TopicAlreadyExistsError:
                        pass
            finally:
                await admin.close()
        except Exception as e:
            log.debug("kafka: topic provisioning skipped (%s)", e)

    async def disconnect(self) -> None:
        if self._producer is not None:
            try:
                await self._producer.stop()
            except Exception:
                pass
            self._producer = None
            self.available = False

    async def produce(
        self,
        topic: str,
        value: Dict[str, Any],
        key: Optional[str] = None,
    ) -> None:
        """Produce one event. key is used for partitioning (typically user_id)."""
        if self._producer is None:
            self.dropped += 1
            log.debug("kafka: drop event → %s (not connected, total dropped=%d)", topic, self.dropped)
            return
        try:
            await self._producer.send_and_wait(topic, value=value, key=key)
        except Exception as e:
            self.dropped += 1
            log.warning("kafka: produce to %s failed (%s) — event dropped", topic, e)

    async def consume(
        self,
        topic: str,
        group_id: str,
        handler: Callable[[Dict[str, Any]], Awaitable[None]],
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Consume a topic in a loop. Each message is decoded as JSON and
        passed to `handler`. Commits offset only after handler succeeds.

        This blocks until `stop_event` is set (or the consumer crashes).
        """
        if not self.available:
            log.warning("kafka: cannot consume %s — producer not available", topic)
            return
        from aiokafka import AIOKafkaConsumer
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            enable_auto_commit=False,
            auto_offset_reset="latest",
            session_timeout_ms=10000,
            heartbeat_interval_ms=3000,
        )
        await consumer.start()
        log.info("kafka: consumer started — topic=%s group=%s", topic, group_id)
        try:
            async for msg in consumer:
                try:
                    await handler(msg.value)
                    await consumer.commit()
                except Exception as e:
                    log.error("kafka: handler error on topic %s: %s", topic, e)
                if stop_event is not None and stop_event.is_set():
                    break
        finally:
            try:
                await consumer.stop()
            except Exception:
                pass
            log.info("kafka: consumer stopped — topic=%s", topic)


# Singleton
real_kafka = RealKafka()
