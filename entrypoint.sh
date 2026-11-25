#!/bin/sh
# AccFino entrypoint — Northflank / Docker deployment
# Do NOT use set -e — background process failures would kill the whole script

cd /app
export PYTHONPATH=/app
export PYTHONIOENCODING=utf-8
export PYTHONWARNINGS=ignore

echo "[accfino] ============================================"
echo "[accfino] AccFino starting..."
echo "[accfino] PORT=${PORT:-8001}"

# ── Validate DATABASE_URL ─────────────────────────────────────────────────────
if [ -z "$DATABASE_URL" ]; then
    echo "[accfino] ERROR: DATABASE_URL is not set."
    echo "[accfino] Set DATABASE_URL in Northflank environment variables."
    echo "[accfino] Example: postgresql+psycopg2://user:pass@host/db?sslmode=require"
    exit 1
fi
echo "[accfino] DATABASE_URL is set (Neon PostgreSQL)"

# ── Ensure required directories exist ────────────────────────────────────────
mkdir -p /app/main_app/data
mkdir -p /app/main_app/classifier_model
mkdir -p /app/main_app/backend/cash_flow/outputs/plots

# ── Initialise database schema ────────────────────────────────────────────────
echo "[accfino] Initialising database schema..."
ACCFINO_APP_NAME=accfino-init python -m db_app.init_db
if [ $? -ne 0 ]; then
    echo "[accfino] ERROR: DB init failed — check DATABASE_URL and Postgres connectivity"
    exit 1
fi
echo "[accfino] Database ready"

# ── Start internal auth API on 127.0.0.1:8000 (background, OPTIONAL) ─────────
# Nothing in the main API depends on this process, so if it is missing (newer
# versions of the project may not ship main_app/api_call.py) or fails to start,
# warn and carry on. Exiting here would make the platform restart the container
# in a loop - and every restart wakes the database (burning Neon CU hours).
if [ -f /app/main_app/api_call.py ]; then
    echo "[accfino] Starting auth API on 127.0.0.1:8000..."
    ACCFINO_APP_NAME=accfino-auth python -m uvicorn main_app.api_call:app \
        --host 127.0.0.1 \
        --port 8000 \
        --log-level warning &
    AUTH_PID=$!
    sleep 3
    if kill -0 $AUTH_PID 2>/dev/null; then
        echo "[accfino] Auth API ready (PID $AUTH_PID)"
    else
        echo "[accfino] WARNING: Auth API failed to start - continuing without it"
    fi
else
    echo "[accfino] Auth API module not present - skipping (not required)"
fi

# ── Start main API on $PORT (foreground) ─────────────────────────────────────
# Northflank injects $PORT — fall back to 8001 if not set
APP_PORT=${PORT:-8001}

echo "[accfino] Starting main API on 0.0.0.0:${APP_PORT}..."
echo "[accfino] Note: ML models take 30-90s to load — /ready returns 503 until done"

exec env ACCFINO_APP_NAME=accfino-api python -m uvicorn main_app.react_api:app \
    --host 0.0.0.0 \
    --port "${APP_PORT}" \
    --workers 1 \
    --timeout-keep-alive 75 \
    --timeout-graceful-shutdown 30 \
    --log-level info
