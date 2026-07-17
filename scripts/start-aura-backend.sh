#!/usr/bin/env bash
# Start AURA Python FastAPI backend on port 8000
set -e
cd /home/z/my-project/aura-backend
exec /home/z/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload 2>&1
