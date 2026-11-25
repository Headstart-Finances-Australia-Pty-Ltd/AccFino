# ── Stage 1: Build React frontend ────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /build
COPY react_frontend/package.json react_frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY react_frontend/ ./
RUN npm run build
RUN test -f /build/dist/index.html || (echo "ERROR: Vite build failed" && exit 1)

# ── Stage 2: Python runtime ───────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

# System deps for PDF/image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 poppler-utils tesseract-ocr curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy application code
COPY . .

# Remove dev/build artifacts
RUN rm -rf react_frontend/node_modules react_frontend/src react_frontend/public

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist ./react_frontend/dist

# Create required directories
RUN mkdir -p main_app/data \
             main_app/classifier_model \
             main_app/backend/cash_flow/outputs/plots

# Verify critical files
RUN test -f /app/db_app/models/company.py \
    && test -f /app/db_app/api/company.py \
    && echo "Company files OK" \
    || (echo "ERROR: company files missing" && exit 1)

# Verify frontend built
RUN test -f /app/react_frontend/dist/index.html \
    && echo "Frontend OK" \
    || (echo "ERROR: frontend dist missing" && exit 1)

RUN chmod +x /app/entrypoint.sh

# Northflank routes external traffic to $PORT (default 8001)
EXPOSE 8001

# Health check via /ready endpoint (returns 503 until app is fully loaded)
HEALTHCHECK --interval=20s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -sf http://localhost:${PORT:-8001}/ready || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
