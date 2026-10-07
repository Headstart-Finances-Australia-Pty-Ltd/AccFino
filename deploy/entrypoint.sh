#!/bin/sh
# AccFino entrypoint — Northflank / Docker deployment
# Do NOT use set -e — background process failures would kill the whole script

# Repository layout: /app/backend (Python packages), /app/frontend/dist (built UI)
cd /app/backend
export PYTHONPATH=/app/backend
export ACCFINO_ROOT=/app
export ACCFINO_DATA_ROOT=${ACCFINO_DATA_ROOT:-/data}
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

# ── Data root (persistent volume, outside the application) ───────────────────
mkdir -p "$ACCFINO_DATA_ROOT"
echo "[accfino] ACCFINO_DATA_ROOT=$ACCFINO_DATA_ROOT"
python -c "from accfino.shared import paths; paths.bootstrap_data_root()" || echo "[accfino] WARNING: could not prepare the data root"

# ── Initialise database schema ────────────────────────────────────────────────
echo "[accfino] Initialising database schema..."
python -m accfino.core.init_db
if [ $? -ne 0 ]; then
    echo "[accfino] ERROR: DB init failed — check DATABASE_URL and Postgres connectivity"
    exit 1
fi
echo "[accfino] Database ready"

# ── Start main API on $PORT (foreground) ─────────────────────────────────────
# Northflank injects $PORT — fall back to 8001 if not set
APP_PORT=${PORT:-8001}

echo "[accfino] Starting main API on 0.0.0.0:${APP_PORT}..."
echo "[accfino] Note: ML models take 30-90s to load — /ready returns 503 until done"

exec python -m uvicorn accfino.app:app \
    --host 0.0.0.0 \
    --port "${APP_PORT}" \
    --workers 1 \
    --timeout-keep-alive 75 \
    --timeout-graceful-shutdown 30 \
    --log-level info
