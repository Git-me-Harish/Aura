"""
AURA — real ClickHouse event log.

Replaces the in-memory `ClickHouse` mock from `store.py`. All user actions,
RL experiences, policy updates, orchestration traces, and MCP tool calls are
persisted here as append-only rows for sub-second analytical queries.

Driver: `clickhouse-connect` (HTTP-native, async via threadpool).
Tables: see `migrations/clickhouse_init.sql`.

If `USE_REAL_CLICKHOUSE=False` OR the connection probe fails, the client
flips to "unavailable" mode: every `insert` becomes a no-op log-warning and
every `query` returns an empty list. The rest of the app MUST NOT fabricate
data to substitute — affected features simply report "no data yet".
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import settings

log = logging.getLogger("aura.data.clickhouse")


class RealClickHouse:
    """Async-friendly ClickHouse client (clickhouse-connect wrapped in executor)."""

    def __init__(self):
        self._client = None
        self.available = False
        self._database = settings.CLICKHOUSE_DATABASE

    async def connect(self) -> None:
        if self._client is not None:
            return
        if not settings.USE_REAL_CLICKHOUSE:
            log.warning("clickhouse: USE_REAL_CLICKHOUSE=False — events will be dropped")
            return
        try:
            import clickhouse_connect
            from urllib.parse import urlparse

            u = urlparse(settings.CLICKHOUSE_URL)
            host = u.hostname or "localhost"
            port = u.port or 8123

            # Synchronous client — we wrap calls in run_in_executor
            self._client = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=self._database,
                connect_timeout=3.0,
                send_receive_timeout=10.0,
            )
            # Smoke test
            ver = self._client.server_version
            self.available = True
            log.info("clickhouse: connected to %s:%s (server v%s)", host, port, ver)
        except Exception as e:
            log.warning("clickhouse: unavailable (%s) — events will be dropped", e)
            self._client = None
            self.available = False

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self.available = False

    # ──────────────────────────────────────────────────────────────────────
    # Public API — every method is async (sync work runs in executor)
    # ──────────────────────────────────────────────────────────────────────
    async def insert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        """Insert a list of dicts into the given table.

        Each dict's keys must match the table columns. `ingested_at` is auto-
        filled server-side via DEFAULT.
        """
        if not rows:
            return
        if self._client is None:
            log.debug("clickhouse: drop %d rows → %s (not connected)", len(rows), table)
            return
        import asyncio
        cols = list(rows[0].keys())
        data = [[r.get(c) for c in cols] for r in rows]
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._client.insert(table, data, column_names=cols, database=self._database),
            )
        except Exception as e:
            log.warning("clickhouse: insert into %s failed (%s) — rows dropped", table, e)

    async def insert_one(self, table: str, row: Dict[str, Any]) -> None:
        await self.insert(table, [row])

    async def query(
        self,
        sql: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Run a SELECT and return rows as dicts. Returns [] on any failure."""
        if self._client is None:
            return []
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None,
                lambda: self._client.query(sql, parameters=parameters),
            )
            cols = res.column_names
            return [dict(zip(cols, row)) for row in res.result_rows]
        except Exception as e:
            log.warning("clickhouse: query failed (%s) — returning []", e)
            return []

    async def query_one(self, sql: str, parameters: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        rows = await self.query(sql, parameters)
        return rows[0] if rows else None

    async def count(self, table: str) -> int:
        row = await self.query_one(f"SELECT count() AS c FROM {self._database}.{table}")
        return int(row["c"]) if row else 0


# Singleton
real_clickhouse = RealClickHouse()
