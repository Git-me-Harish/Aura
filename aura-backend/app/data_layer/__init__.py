"""
AURA — unified data layer facade.

Exposes `postgres`, `vector_db`, `redis`, `object_storage`, `clickhouse`,
`kafka` symbols that the rest of the app imports. Each one routes to the real
async client. The in-process mock classes from `store.py` are NOT used as
silent fallbacks any more — when a real service is down the affected method
logs an error and returns None / [] / 0 so callers can surface "no data yet"
honestly instead of substituting fake records.

Lifecycle: `await init_data_layer()` is called from FastAPI lifespan.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.data_layer.postgres import real_postgres, RealPostgresTable
from app.data_layer.redis_client import real_redis
from app.data_layer.qdrant import real_qdrant
from app.data_layer.clickhouse import real_clickhouse
from app.data_layer.kafka import real_kafka
from app.data_layer.pg_event_log import pg_event_log

log = logging.getLogger("aura.data")


# ──────────────────────────────────────────────────────────────────────────────
# Postgres facade — routes to real asyncpg pool. No in-memory fallback.
# ──────────────────────────────────────────────────────────────────────────────
class HybridPostgresTable:
    """Async Postgres table facade.

    When real_postgres is available, all methods hit the real pool. When it's
    not, every method returns None / [] / 0 — callers receive "no data yet"
    rather than fabricated rows.
    """

    def __init__(self, name: str):
        self.name = name
        self._real: Optional[RealPostgresTable] = None

    def _bind(self) -> Optional[RealPostgresTable]:
        if self._real is None and real_postgres.available:
            self._real = RealPostgresTable(real_postgres._pool, self.name)
        return self._real

    async def insert(self, row_id: str, row: Dict[str, Any]) -> None:
        t = self._bind()
        if t is None:
            log.error("postgres: insert into %s skipped (DB unavailable)", self.name)
            return
        await t.insert(row_id, row)

    async def get(self, row_id: str) -> Optional[Dict[str, Any]]:
        t = self._bind()
        if t is None:
            return None
        return await t.get(row_id)

    async def all(self) -> List[Dict[str, Any]]:
        t = self._bind()
        if t is None:
            return []
        return await t.all()

    async def where(self, **filters) -> List[Dict[str, Any]]:
        t = self._bind()
        if t is None:
            return []
        return await t.where(**filters)

    async def count(self) -> int:
        t = self._bind()
        if t is None:
            return 0
        return await t.count()

    async def execute(self, sql: str, *args) -> str:
        """Run arbitrary SQL on the pool. Returns the postgres status string."""
        if not real_postgres.available or real_postgres._pool is None:
            log.error("postgres: execute skipped (DB unavailable)")
            return ""
        return await real_postgres._pool.execute(sql, *args)

    async def fetch(self, sql: str, *args) -> List[Dict[str, Any]]:
        if not real_postgres.available or real_postgres._pool is None:
            return []
        rows = await real_postgres._pool.fetch(sql, *args)
        return [dict(r) for r in rows]

    async def fetchrow(self, sql: str, *args) -> Optional[Dict[str, Any]]:
        if not real_postgres.available or real_postgres._pool is None:
            return None
        row = await real_postgres._pool.fetchrow(sql, *args)
        return dict(row) if row else None


class HybridPostgres:
    def __init__(self):
        self._tables: Dict[str, HybridPostgresTable] = {}

    def table(self, name: str) -> HybridPostgresTable:
        if name not in self._tables:
            self._tables[name] = HybridPostgresTable(name)
        return self._tables[name]

    @property
    def available(self) -> bool:
        return real_postgres.available


# ──────────────────────────────────────────────────────────────────────────────
# Redis facade — uses real_redis if available; methods no-op on failure.
# ──────────────────────────────────────────────────────────────────────────────
class HybridRedis:
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        if settings.USE_REAL_REDIS and real_redis.available:
            await real_redis.set(key, value, ttl_seconds)

    async def get(self, key: str) -> Optional[Any]:
        if settings.USE_REAL_REDIS and real_redis.available:
            return await real_redis.get(key)
        return None

    async def incr(self, key: str, by: int = 1) -> int:
        if settings.USE_REAL_REDIS and real_redis.available:
            return await real_redis.incr(key, by)
        return 0

    async def keys(self, pattern: str = "*") -> List[str]:
        if settings.USE_REAL_REDIS and real_redis.available:
            return await real_redis.keys(pattern)
        return []

    async def publish(self, channel: str, message: str) -> int:
        if settings.USE_REAL_REDIS and real_redis.available:
            return await real_redis.publish(channel, message)
        return 0

    async def pubsub(self):
        """Return a redis pubsub object (or None if redis is unavailable)."""
        if not (settings.USE_REAL_REDIS and real_redis.available):
            return None
        return await real_redis.pubsub()

    @property
    def available(self) -> bool:
        return settings.USE_REAL_REDIS and real_redis.available


# ──────────────────────────────────────────────────────────────────────────────
# Vector DB facade — Qdrant only. Returns [] / 0 when unavailable.
# ──────────────────────────────────────────────────────────────────────────────
class HybridVectorDB:
    def __init__(self, dim: int = 384):
        self.dim = dim

    async def upsert(self, point_id: str, vector: List[float], payload: Dict[str, Any]) -> None:
        if settings.USE_REAL_QDRANT and real_qdrant.available:
            await real_qdrant.upsert(point_id, vector, payload)
        else:
            log.error("qdrant: upsert skipped (DB unavailable)")

    async def search(
        self,
        query_vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        if settings.USE_REAL_QDRANT and real_qdrant.available:
            return await real_qdrant.search(query_vector, top_k, filters)
        return []

    async def count(self) -> int:
        if settings.USE_REAL_QDRANT and real_qdrant.available:
            return await real_qdrant.count()
        return 0


# ──────────────────────────────────────────────────────────────────────────────
# Object storage — local filesystem under /tmp/aura-objects.
# (S3 wiring is a future task — kept simple but real, not faked.)
# ──────────────────────────────────────────────────────────────────────────────
class LocalObjectStorage:
    def __init__(self):
        from pathlib import Path
        self._root = Path("/tmp/aura-objects")
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes) -> None:
        p = self._root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> Optional[bytes]:
        p = self._root / key
        return p.read_bytes() if p.exists() else None

    def list(self, prefix: str = "") -> List[str]:
        return [str(p.relative_to(self._root)) for p in self._root.rglob("*") if p.is_file() and str(p.relative_to(self._root)).startswith(prefix)]


# ──────────────────────────────────────────────────────────────────────────────
# Singletons (these are the symbols the rest of the app imports)
# ──────────────────────────────────────────────────────────────────────────────
postgres = HybridPostgres()
vector_db = HybridVectorDB(dim=settings.EMBEDDING_DIM)
redis = HybridRedis()
object_storage = LocalObjectStorage()
clickhouse = real_clickhouse          # real ClickHouse (singleton from clickhouse.py)
kafka = real_kafka                    # real Kafka producer (singleton from kafka.py)
pg_event_log = pg_event_log          # Postgres-backed event log (always available with Postgres)


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────────────
async def init_data_layer() -> None:
    """Called from FastAPI lifespan — connect real clients in parallel."""
    tasks = []
    if settings.USE_REAL_POSTGRES:
        tasks.append(real_postgres.connect())
    if settings.USE_REAL_REDIS:
        tasks.append(real_redis.connect())
    if settings.USE_REAL_QDRANT:
        real_qdrant.dim = settings.EMBEDDING_DIM
        tasks.append(real_qdrant.connect())
    if settings.USE_REAL_CLICKHOUSE:
        tasks.append(real_clickhouse.connect())
    if settings.USE_REAL_KAFKA:
        tasks.append(real_kafka.connect())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    # Postgres-backed event log self-provisions its schema after Postgres is up
    if real_postgres.available:
        await pg_event_log._ensure_schema()
    log.info(
        "data layer ready — postgres=%s redis=%s(mode=%s) qdrant=%s(mode=%s) "
        "clickhouse=%s kafka=%s pg_event_log=%s",
        real_postgres.available,
        real_redis.available, real_redis.mode,
        real_qdrant.available, real_qdrant.mode,
        real_clickhouse.available, real_kafka.available,
        pg_event_log.available,
    )


async def shutdown_data_layer() -> None:
    await asyncio.gather(
        real_postgres.disconnect(),
        real_redis.disconnect(),
        real_qdrant.disconnect(),
        real_clickhouse.disconnect(),
        real_kafka.disconnect(),
        return_exceptions=True,
    )
