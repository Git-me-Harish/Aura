"""
AURA — Redis layer with dev/prod auto-routing.

Resolution order (per call):
  1. Real Redis  — when USE_REAL_REDIS=True AND the real server is reachable.
  2. Fake Redis  — when ENVIRONMENT is "dev" or "test" (in-process, async-safe,
                   fully functional pub/sub + cache). This is what makes the
                   WebSocket hub multi-worker fan-out actually work in local dev
                   without needing a docker Redis container.
  3. None        — in prod with no real server, methods return None/0/[].

Fake Redis is `fakeredis.aioredis.FakeRedis` — a drop-in async redis mock
that supports pub/sub, TTL, KEYS, INCR, GET/SET. It is shared across the
process (one shared server instance) so multiple HybridRedis consumers see
the same keyspace.
"""
from __future__ import annotations
import logging
from typing import Any, List, Optional

from app.config import settings

log = logging.getLogger("aura.data.redis")


# Shared fakeredis server — created lazily on first use, then reused by every
# subsequent FakeRedis client so all callers see the same keyspace.
_FAKE_SERVER: Any = None


def _get_fake_server():
    global _FAKE_SERVER
    if _FAKE_SERVER is None:
        from fakeredis import FakeServer
        _FAKE_SERVER = FakeServer()
        log.info("redis: fakeredis server initialised (shared, in-process)")
    return _FAKE_SERVER


def _new_fake_client():
    """Return a new async FakeRedis client bound to the shared fake server."""
    from fakeredis import aioredis as fake_aioredis
    return fake_aioredis.FakeRedis(server=_get_fake_server())


class RealRedis:
    """Async Redis client with fakeredis dev fallback.

    `available=True` once either the real server OR fakeredis is wired up.
    `mode` exposes which one is active: "real" | "fake" | "none".
    """

    def __init__(self):
        self._client: Any = None
        self._mode: str = "none"
        self.available: bool = False

    @property
    def mode(self) -> str:
        return self._mode

    async def connect(self) -> None:
        if self._client is not None:
            return

        # 1. Try real Redis first if enabled
        if settings.USE_REAL_REDIS:
            try:
                import redis.asyncio as aioredis  # type: ignore
                client = aioredis.from_url(
                    settings.REDIS_URL,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                )
                await client.ping()
                self._client = client
                self._mode = "real"
                self.available = True
                log.info("redis: connected to REAL Redis at %s", settings.REDIS_URL)
                return
            except Exception as e:
                log.warning("redis: real server unreachable (%s) — checking fakeredis fallback", e)

        # 2. Fall back to fakeredis in dev / test
        if settings.ENVIRONMENT in ("dev", "test"):
            try:
                self._client = _new_fake_client()
                await self._client.ping()
                self._mode = "fake"
                self.available = True
                log.info("redis: using FAKEREDIS (in-process) — WS pub/sub + cache active")
                return
            except Exception as e:
                log.error("redis: fakeredis init failed (%s) — Redis fully unavailable", e)

        # 3. Prod with no real server → unavailable
        self._client = None
        self._mode = "none"
        self.available = False
        log.warning("redis: unavailable in %s env — WS hub will run in single-worker mode", settings.ENVIRONMENT)

    async def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.aclose()
        except Exception:
            pass
        self._client = None
        self._mode = "none"
        self.available = False

    # ── Public API ────────────────────────────────────────────────────────
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        if self._client is None:
            return
        try:
            v = value if isinstance(value, str) else str(value)
            await self._client.set(key, v, ex=ttl_seconds)
        except Exception as e:
            log.debug("redis set failed: %s", e)

    async def get(self, key: str) -> Optional[Any]:
        if self._client is None:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            log.debug("redis get failed: %s", e)
            return None

    async def incr(self, key: str, by: int = 1) -> int:
        if self._client is None:
            return 0
        try:
            return await self._client.incrby(key, by)
        except Exception as e:
            log.debug("redis incr failed: %s", e)
            return 0

    async def keys(self, pattern: str = "*") -> List[str]:
        if self._client is None:
            return []
        try:
            return await self._client.keys(pattern)
        except Exception as e:
            log.debug("redis keys failed: %s", e)
            return []

    async def publish(self, channel: str, message: str) -> int:
        """Pub/sub for WebSocket fan-out. Returns number of subscribers reached."""
        if self._client is None:
            return 0
        try:
            return await self._client.publish(channel, message)
        except Exception as e:
            log.debug("redis publish failed: %s", e)
            return 0

    async def pubsub(self):
        """Return a redis pubsub object for subscribing to channels.

        Caller is responsible for `subscribe()`, `get_message()`, and `close()`.
        Returns None if Redis is unavailable.
        """
        if self._client is None:
            return None
        try:
            return self._client.pubsub()
        except Exception as e:
            log.debug("redis pubsub open failed: %s", e)
            return None


real_redis = RealRedis()
