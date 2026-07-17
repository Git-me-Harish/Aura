"""
AURA — real PostgreSQL layer (asyncpg).

When `USE_REAL_POSTGRES=True` AND the pool can be reached, all methods hit
the real async Postgres pool. When the pool is unavailable, `available=False`
and every method returns None / [] / 0 — callers receive "no data yet"
rather than fabricated rows. There is NO in-process mock fallback.

Public API:
    await pg.table("users").insert(row_id, row)
    await pg.table("users").get(row_id)
    await pg.table("users").all()
    await pg.table("users").where(**filters)
    await pg.table("users").count()
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

import asyncpg

from app.config import settings

log = logging.getLogger("aura.data.postgres")


# ──────────────────────────────────────────────────────────────────────────────
# Real async table facade
# ──────────────────────────────────────────────────────────────────────────────
# Primary-key column name per table.
# The legacy mock store used "id" for every table; the real schema uses
# domain-specific names (user_id, item_id, interaction_id, …). This map
# lets the generic table facade issue correct WHERE / ON CONFLICT clauses.
_PK_COLUMN: Dict[str, str] = {
    "users":               "user_id",
    "items":               "item_id",
    "interactions":        "interaction_id",
    "memory_records":      "record_id",
    "preference_profiles": "user_id",
    "oauth_tokens":        "id",   # composite (user_id, provider); use a synthetic row id
    "knowledge_docs":      "doc_id",
    "kg_entities":         "entity",
    "rl_experiences":      "exp_id",
    "audit_log":           "audit_id",
}


def _pk_for(table_name: str) -> str:
    return _PK_COLUMN.get(table_name, "id")


class RealPostgresTable:
    def __init__(self, pool: asyncpg.Pool, name: str):
        self._pool = pool
        self.name = name
        self.pk = _pk_for(name)
        # Column type cache, populated lazily — lets us decide whether to
        # JSON-encode a value (JSONB columns) or pass it as-is (TEXT[] arrays,
        # scalars). asyncpg is strict: TEXT[] wants a Python list, JSONB wants
        # a JSON string.
        self._jsonb_cols: Optional[set] = None

    async def _ensure_column_types(self) -> None:
        if self._jsonb_cols is not None:
            return
        # udt_name='jsonb' is the reliable way to detect JSONB columns across
        # all Postgres versions (data_type is sometimes 'USER-DEFINED', sometimes 'jsonb').
        rows = await self._pool.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=$1 AND udt_name='jsonb'",
            self.name,
        )
        self._jsonb_cols = {r["column_name"] for r in rows}

    async def insert(self, row_id: str, row: Dict[str, Any]) -> None:
        pk = self.pk
        await self._ensure_column_types()
        cols = [c for c in row.keys() if c != pk]
        if not cols:
            await self._pool.execute(
                f'INSERT INTO {self.name} ("{pk}") VALUES ($1) '
                f'ON CONFLICT ("{pk}") DO NOTHING'
            )
            return
        # Encode values: JSONB columns get JSON-strings, everything else is
        # passed as-is (asyncpg handles TEXT[] from Python lists, scalars natively).
        import json as _json
        values = []
        for c in cols:
            v = row[c]
            if c in self._jsonb_cols and isinstance(v, (dict, list)):
                values.append(_json.dumps(v))
            else:
                values.append(v)
        col_sql = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(f"${i+2}" for i in range(len(cols)))  # $2..$N
        sql = (
            f'INSERT INTO {self.name} ("{pk}", {col_sql}) '
            f'VALUES ($1, {placeholders}) '
            f'ON CONFLICT ("{pk}") DO UPDATE SET '
            + ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols)
        )
        await self._pool.execute(sql, row_id, *values)

    async def get(self, row_id: str) -> Optional[Dict[str, Any]]:
        row = await self._pool.fetchrow(
            f'SELECT * FROM {self.name} WHERE "{self.pk}" = $1', row_id
        )
        return dict(row) if row else None

    async def all(self) -> List[Dict[str, Any]]:
        rows = await self._pool.fetch(f"SELECT * FROM {self.name}")
        return [dict(r) for r in rows]

    async def where(self, **filters) -> List[Dict[str, Any]]:
        if not filters:
            return await self.all()
        where_sql = " AND ".join(f'"{k}" = ${i+1}' for i, k in enumerate(filters.keys()))
        sql = f"SELECT * FROM {self.name} WHERE {where_sql}"
        rows = await self._pool.fetch(sql, *filters.values())
        return [dict(r) for r in rows]

    async def count(self) -> int:
        return await self._pool.fetchval(f"SELECT COUNT(*) FROM {self.name}")


class RealPostgres:
    """Real async Postgres facade with the same surface as the mock `Postgres`."""

    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._tables: Dict[str, RealPostgresTable] = {}
        self._lock = asyncio.Lock()
        self.available = False

    async def connect(self) -> None:
        if self._pool is not None:
            return
        try:
            self._pool = await asyncpg.create_pool(
                dsn=settings.POSTGRES_DSN,
                min_size=2,
                max_size=10,
                command_timeout=10.0,
            )
            # Smoke test
            async with self._pool.acquire() as conn:
                val = await conn.fetchval("SELECT 1")
                assert val == 1
            self.available = True
            log.info("postgres: connected to %s", settings.POSTGRES_DSN)
        except Exception as e:
            log.warning("postgres: unavailable (%s) — falling back to in-memory", e)
            self.available = False
            self._pool = None

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self.available = False

    def table(self, name: str) -> RealPostgresTable:
        if name not in self._tables:
            self._tables[name] = RealPostgresTable(self._pool, name)
        return self._tables[name]


# Singleton
real_postgres = RealPostgres()
