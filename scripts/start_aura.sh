#!/usr/bin/env bash
# AURA — one-shot startup script.
#
# Brings up the full stack in the right order:
#   1. Embedded Postgres (pgserver) + apply migrations
#   2. Seed users + interactions
#   3. Restart FastAPI backend on :8000
#
# Frontend (Next.js :3000) and gateway (Caddy :81) are NOT managed here —
# they should already be running in this dev environment.
#
# Usage:
#     python scripts/start_aura.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/aura-backend"
VENV_PYTHON=""

if [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
  VENV_PYTHON="$BACKEND_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACKEND_DIR/.venv/Scripts/python" ]; then
  VENV_PYTHON="$BACKEND_DIR/.venv/Scripts/python"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
elif [ -x "$PROJECT_ROOT/.venv/Scripts/python" ]; then
  VENV_PYTHON="$PROJECT_ROOT/.venv/Scripts/python"
elif [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  VENV_PYTHON="python"
else
  echo "Python interpreter not found" >&2
  exit 1
fi

PY="$VENV_PYTHON"
SCRIPTS="$PROJECT_ROOT/scripts"
LOG="$BACKEND_DIR/logs/uvicorn.log"

echo "════════════════════════════════════════════════════════════════"
echo "AURA startup — Postgres → seed → backend"
echo "════════════════════════════════════════════════════════════════"

echo ""
echo "[1/4] Starting embedded Postgres + applying migrations…"
$PY $SCRIPTS/start_postgres.py 2>&1 | tail -8

echo ""
echo "[2/4] Seeding users + interactions…"
$PY $SCRIPTS/seed_interactions.py 2>&1 | tail -10

echo ""
echo "[3/4] Restarting FastAPI backend on :8000…"
pkill -9 -f "uvicorn app.main" 2>/dev/null || true
sleep 2
$PY $SCRIPTS/start_backend.py

echo ""
echo "[4/4] Verifying backend…"
sleep 3
if curl -s --max-time 5 http://localhost:8000/api/health | grep -q '"ok"'; then
    echo "  ✓ backend healthy"
else
    echo "  ✗ backend NOT responding — check $LOG"
    exit 1
fi

if curl -s --max-time 5 http://localhost:8000/api/recsys/status | grep -q '"available":true'; then
    echo "  ✓ recsys rankers available"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "AURA is live."
echo "  Backend:     http://localhost:8000"
echo "  Frontend:    http://localhost:3000"
echo "  Gateway:     http://localhost:81"
echo "  Postgres:    embedded (DSN in .env.pg)"
echo ""
echo "Quick smoke test:"
echo "  curl -X POST http://localhost:8000/api/recsys/train"
echo "  curl -X POST http://localhost:8000/api/orchestrate -d '{}'"
echo "  curl http://localhost:8000/api/orchestrate/last | python -m json.tool"
echo "════════════════════════════════════════════════════════════════"
