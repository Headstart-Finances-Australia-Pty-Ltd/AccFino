# AccFino - production image (Northflank / any Docker host)
# Layout: backend/accfino (FastAPI: core, shared, modules), frontend/ (React/Vite), deploy/ (runtime scripts)

# ── Stage 1: build the React frontend ─────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npm run build && test -f /build/dist/index.html

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend ACCFINO_ROOT=/app ACCFINO_DATA_ROOT=/data

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 poppler-utils tesseract-ocr curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --upgrade pip && pip install -r backend/requirements.txt

COPY backend/ backend/
COPY deploy/ deploy/
COPY --from=frontend-build /build/dist frontend/dist

# Persistent business data + documents live OUTSIDE the application: mount a volume at /data (ACCFINO_DATA_ROOT).
# deploy/data-seed/ holds read-only first-run defaults; they are copied into /data only when a file is missing.
RUN mkdir -p /data && test -f backend/accfino/app.py && test -f frontend/dist/index.html \
    && chmod +x deploy/entrypoint.sh
VOLUME ["/data"]

EXPOSE 8001
HEALTHCHECK --interval=20s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -sf http://localhost:${PORT:-8001}/ready || exit 1
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
