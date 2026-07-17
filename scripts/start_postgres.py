"""
AURA — embedded Postgres launcher.

Brings up a real PostgreSQL server in-process (no docker, no system install
required) using `pgserver`. This lets the entire AURA backend talk to a
real Postgres — same asyncpg driver, same SQL, same schema — without
needing docker-compose in this dev environment.

Side effects:
  * Starts a postgres server (socket-only) under /home/z/my-project/aura-backend/pgdata
  * Creates the `aura` database if it doesn't exist
  * Applies migrations/001_init.sql, 002_items_seed.sql, 003_knowledge_seed.sql
  * Writes the live DSN to /home/z/my-project/aura-backend/.env.pg
  * Prints the DSN to stdout (last line) so callers can use it

Idempotent: re-running won't fail if the DB already exists; migrations
use ON CONFLICT / IF NOT EXISTS so re-seeding is safe.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

import pgserver

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "aura-backend"
PGDATA = BACKEND / "pgdata"
MIGRATIONS = BACKEND / "migrations"
ENV_PG = BACKEND / ".env.pg"
DB_NAME = "aura"


def _log(msg: str) -> None:
    print(f"[aura-pg] {msg}", flush=True)


def main() -> int:
    PGDATA.parent.mkdir(parents=True, exist_ok=True)

    _log("starting embedded postgres (pgserver)…")
    server = pgserver.get_server(str(PGDATA), cleanup_mode=None)  # persist across runs
    server.ensure_pgdata_inited()
    server.ensure_postgres_running()

    # First connect to the default `postgres` db to create our app DB
    admin_uri = server.get_uri(database="postgres")
    _log(f"admin uri: {admin_uri}")

    # Create the aura database if it doesn't exist
    import asyncpg
    async def _create_db():
        conn = await asyncpg.connect(admin_uri)
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", DB_NAME
            )
            if not exists:
                await conn.execute(f'CREATE DATABASE "{DB_NAME}"')
                _log(f"created database: {DB_NAME}")
            else:
                _log(f"database already exists: {DB_NAME}")
        finally:
            await conn.close()
    import asyncio
    asyncio.run(_create_db())

    # Now get the app DB URI and apply migrations
    app_uri = server.get_uri(database=DB_NAME)
    # pgserver returns a URI with host=/socket/path — convert to DSN format asyncpg likes
    # Actually asyncpg accepts postgres URIs just fine. But our config expects a DSN.
    # Format: postgresql://postgres@/aura?host=/tmp/sockets
    _log(f"app uri: {app_uri}")

    # Apply migrations in order
    migration_files = [
        MIGRATIONS / "001_init.sql",
        MIGRATIONS / "002_items_seed.sql",
        MIGRATIONS / "003_knowledge_seed.sql",
    ]

    async def _apply_migrations():
        conn = await asyncpg.connect(app_uri)
        try:
            for mig in migration_files:
                if not mig.exists():
                    _log(f"SKIP (missing): {mig.name}")
                    continue
                sql = mig.read_text()
                # asyncpg.execute can run multi-statement SQL when using the simple query protocol
                # via conn.execute() — but for many statements we should use the lower-level
                # conn.executemany() pattern. The simplest reliable approach is to use
                # the simple query protocol by calling pgconn.exec(sql).
                _log(f"applying {mig.name} ({len(sql)} bytes)…")
                await conn.execute(sql)
                _log(f"  OK: {mig.name}")
        finally:
            await conn.close()
    asyncio.run(_apply_migrations())

    # Verify tables
    async def _verify():
        conn = await asyncpg.connect(app_uri)
        try:
            tables = await conn.fetch(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name"
            )
            _log(f"tables in '{DB_NAME}': {[t['table_name'] for t in tables]}")
            n_items = await conn.fetchval("SELECT COUNT(*) FROM items")
            n_docs = await conn.fetchval("SELECT COUNT(*) FROM knowledge_docs")
            n_kg = await conn.fetchval("SELECT COUNT(*) FROM kg_entities")
            _log(f"row counts: items={n_items}, knowledge_docs={n_docs}, kg_entities={n_kg}")
        finally:
            await conn.close()
    asyncio.run(_verify())

    # Write the DSN to .env.pg so the backend can pick it up
    # Convert URI to a DSN asyncpg/SQLAlchemy accepts
    # pgserver's URI is like: postgresql:///aura?host=/tmp/pgserver-xxxx
    # We want: postgresql://postgres@/aura?host=/tmp/pgserver-xxxx
    dsn = app_uri
    ENV_PG.write_text(f"POSTGRES_DSN={dsn}\n")
    _log(f"wrote DSN to {ENV_PG}")

    # Also update the backend's .env file so the running backend uses this DSN
    env_file = BACKEND / ".env"
    if env_file.exists():
        content = env_file.read_text()
        # Replace the POSTGRES_DSN line
        new_lines = []
        found = False
        for line in content.splitlines():
            if line.startswith("POSTGRES_DSN="):
                new_lines.append(f"POSTGRES_DSN={dsn}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"POSTGRES_DSN={dsn}")
        env_file.write_text("\n".join(new_lines) + "\n")
        _log(f"updated POSTGRES_DSN in {env_file}")

    # Print the DSN as the final line (for callers to capture)
    print(dsn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
