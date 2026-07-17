"""
AURA — Postgres-backed event log.

This is the durable fallback for ClickHouse + Kafka. It mirrors the
RealClickHouse API surface (insert / insert_one / query / query_one / count)
so the event bus and the metrics endpoints can use either store interchangeably.

Design:
  * Always available when Postgres is available (no separate process to run).
  * Self-provisions its tables on connect() via CREATE TABLE IF NOT EXISTS.
  * Two tables:
      - app_events         — mirrors ClickHouse `user_actions`
      - policy_updates_pg  — mirrors ClickHouse `policy_updates`
  * Asyncpg parameterised queries — SQL injection safe.
  * `available=True` is independent of ClickHouse; the event_bus writes to
    BOTH when both are up, and to whichever is up otherwise.

Why keep this in Postgres instead of faking ClickHouse? Because Postgres IS
already our durable store. Spinning a separate ClickHouse container in dev
just to hold the same event rows is over-engineering — Postgres handles the
event volume fine for single-node deployments. ClickHouse remains the right
choice for multi-node / high-volume prod where its columnar compression and
distributed aggregates pay off; that's why the dual-write design lets you
turn it on later without code changes.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.data_layer.postgres import real_postgres

log = logging.getLogger("aura.data.pg_events")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_events (
    event_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    item_id         TEXT NOT NULL DEFAULT '',
    action          TEXT NOT NULL,
    reward          REAL NOT NULL DEFAULT 0.0,
    timestamp       TIMESTAMPTZ NOT NULL,
    context         JSONB NOT NULL DEFAULT '{}'::jsonb,
    topic           TEXT NOT NULL DEFAULT 'user_actions',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_app_events_user_ts   ON app_events(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_app_events_action    ON app_events(action);
CREATE INDEX IF NOT EXISTS idx_app_events_ts        ON app_events(timestamp DESC);

CREATE TABLE IF NOT EXISTS policy_updates_pg (
    version         TEXT NOT NULL,
    mean_reward     REAL NOT NULL DEFAULT 0.0,
    samples         BIGINT NOT NULL DEFAULT 0,
    epsilon         REAL NOT NULL DEFAULT 0.0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_policy_updates_pg_ts ON policy_updates_pg(updated_at DESC);
"""


class PostgresEventLog:
    """Mirrors the RealClickHouse API. Uses the shared asyncpg pool."""

    def __init__(self):
        self._initialised = False
        self.available = False

    async def _ensure_schema(self) -> None:
        if self._initialised:
            return
        if not real_postgres.available or real_postgres._pool is None:
            return
        try:
            async with real_postgres._pool.acquire() as conn:
                for stmt in _SCHEMA_SQL.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await conn.execute(stmt)
            self._initialised = True
            self.available = True
            log.info("pg_event_log: schema ready (app_events + policy_updates_pg)")
        except Exception as e:
            log.warning("pg_event_log: schema init failed (%s)", e)
            self.available = False

    # ── API surface — matches RealClickHouse ──────────────────────────────
    async def insert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        await self._ensure_schema()
        if not self.available or real_postgres._pool is None:
            return
        # Route by table name
        if table == "user_actions":
            await self._insert_user_actions(rows)
        elif table == "policy_updates":
            await self._insert_policy_updates(rows)
        else:
            log.debug("pg_event_log: unknown table %s — dropping %d rows", table, len(rows))

    async def insert_one(self, table: str, row: Dict[str, Any]) -> None:
        await self.insert(table, [row])

    async def _insert_user_actions(self, rows: List[Dict[str, Any]]) -> None:
        sql = (
            "INSERT INTO app_events "
            "(event_id, user_id, item_id, action, reward, timestamp, context, topic) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8) "
            "ON CONFLICT (event_id) DO NOTHING"
        )
        async with real_postgres._pool.acquire() as conn:
            for r in rows:
                try:
                    ts = r.get("timestamp")
                    if isinstance(ts, str):
                        ts = ts.replace("Z", "+00:00")
                        try:
                            ts = datetime.fromisoformat(ts)
                        except Exception:
                            ts = datetime.now(timezone.utc)
                    elif not isinstance(ts, datetime):
                        ts = datetime.now(timezone.utc)
                    ctx = r.get("context", {})
                    if isinstance(ctx, str):
                        ctx_str = ctx
                    else:
                        ctx_str = json.dumps(ctx, default=str)
                    await conn.execute(
                        sql,
                        str(r.get("event_id", "")),
                        str(r.get("user_id", "")),
                        str(r.get("item_id", "")),
                        str(r.get("action", "click")),
                        float(r.get("reward", 0.0)),
                        ts,
                        ctx_str,
                        str(r.get("topic", "user_actions")),
                    )
                except Exception as e:
                    log.warning("pg_event_log: insert user_actions row failed (row=%r): %s", r, e)

    async def _insert_policy_updates(self, rows: List[Dict[str, Any]]) -> None:
        sql = (
            "INSERT INTO policy_updates_pg "
            "(version, mean_reward, samples, epsilon, updated_at) "
            "VALUES ($1, $2, $3, $4, $5)"
        )
        async with real_postgres._pool.acquire() as conn:
            for r in rows:
                try:
                    ts = r.get("updated_at") or r.get("timestamp") or datetime.now(timezone.utc)
                    if isinstance(ts, str):
                        try:
                            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except Exception:
                            ts = datetime.now(timezone.utc)
                    await conn.execute(
                        sql,
                        str(r.get("version", "v0")),
                        float(r.get("mean_reward", 0.0)),
                        int(r.get("samples", 0)),
                        float(r.get("epsilon", 0.0)),
                        ts,
                    )
                except Exception as e:
                    log.debug("pg_event_log: insert policy_update row failed: %s", e)

    async def query(
        self,
        sql: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Run a SELECT, returning rows as dicts.

        The SQL string is rewritten on the fly:
          - Table `user_actions`   → `app_events`
          - Table `policy_updates` → `policy_updates_pg`
        This lets the same query strings used against ClickHouse work here.
        Parameter style is %(name)s (same as clickhouse-connect).
        """
        await self._ensure_schema()
        if not self.available or real_postgres._pool is None:
            return []
        try:
            rewritten = (
                sql.replace("user_actions", "app_events")
                   .replace("policy_updates", "policy_updates_pg")
            )
            # Convert %(name)s → $N for asyncpg
            params: List[Any] = []
            def _repl(m):
                name = m.group(1)
                params.append(parameters.get(name) if parameters else None)
                return f"${len(params)}"
            import re
            rewritten = re.sub(r"%\((\w+)\)s", _repl, rewritten)
            async with real_postgres._pool.acquire() as conn:
                rows = await conn.fetch(rewritten, *params)
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("pg_event_log: query failed (%s) — returning []", e)
            return []

    async def query_one(
        self,
        sql: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        rows = await self.query(sql, parameters)
        return rows[0] if rows else None

    async def count(self, table: str) -> int:
        await self._ensure_schema()
        if not self.available or real_postgres._pool is None:
            return 0
        actual = (
            "app_events" if table == "user_actions"
            else "policy_updates_pg" if table == "policy_updates"
            else table
        )
        try:
            async with real_postgres._pool.acquire() as conn:
                v = await conn.fetchval(f"SELECT COUNT(*) FROM {actual}")
            return int(v) if v is not None else 0
        except Exception:
            return 0


# Singleton
pg_event_log = PostgresEventLog()
