# AccFino — Intelligent Accounting for Australian Business

Full-stack SaaS accounting platform: FastAPI backend + React/Vite frontend, served from a single Docker container.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 + Vite + Recharts + Lucide |
| Backend | FastAPI + uvicorn + SQLAlchemy 2.0 |
| AI / ML | Ollama LLM + scikit-learn + RDR rules + tesseract OCR |
| Database | Neon Postgres (production) / SQLite (local dev) |
| Auth | PyJWT + bcrypt + RBAC |
| Payments | Stripe |
| Hosting | Northflank (Docker) + Cloudflare DNS |

## URL routing

| URL | Serves |
|---|---|
| `www.accfino.com/` | Marketing homepage (`index-marketing.html`) |
| `www.accfino.com/login` | React SPA → LoginPage.jsx |
| `www.accfino.com/dashboard` | React SPA → DashboardPage.jsx |
| `www.accfino.com/reconciliation` | React SPA → ReconciliationPage.jsx |
| `www.accfino.com/api/*` | FastAPI REST endpoints (JSON) |
| `www.accfino.com/assets/*` | Vite-compiled JS/CSS/images |

## Local development

```bash
# 1. Start Python backend
pip install -r requirements.txt
python -m db_app.init_db
python -m uvicorn main_app.react_api:app --host 127.0.0.1 --port 8001 --reload

# 2. Start React frontend (separate terminal)
cd react_frontend
npm install
npm run dev
# → http://localhost:3000 (proxies /api → :8001 via vite.config.js)
```

Leave `DATABASE_URL` unset locally — the app falls back to SQLite automatically.

## Northflank deployment

### Environment variables (Service → Environment → Secret Variables)

```
DATABASE_URL       postgresql+psycopg2://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require
JWT_SECRET         your-long-random-secret
STRIPE_SECRET_KEY  sk_live_xxx
RESEND_API_KEY     re_xxx
FROM_EMAIL         noreply@accfino.com
PYTHONPATH         /app
```

### Persistent volumes (Service → Storage → Volumes)

| Mount path | Purpose |
|---|---|
| `/app/db_app/data` | SQLite fallback + session data |
| `/app/main_app/data` | Reconciliation session files |
| `/app/main_app/classifier_model` | ML model .pkl files |
| `/app/main_app/backend/cash_flow/outputs` | Cash flow forecast outputs |

### Networking

- Port: `8001` (Public)
- Health check path: `/health`
- Copy the external URL → paste as CNAME target in Cloudflare DNS

### Cloudflare DNS (accfino.com)

```
Type   Name   Target                        Proxy
CNAME  www    your-service.northflank.app  🟠 Proxied (Orange)
CNAME  @      your-service.northflank.app  🟠 Proxied (Orange)
```

## Database migration (SQLite → Neon Postgres)

1. Create a free project at [neon.tech](https://neon.tech)
2. Copy the connection string
3. Set `DATABASE_URL` in Northflank environment variables
4. Redeploy — `init_db.py` runs automatically on startup and creates all tables
5. `entrypoint.sh` automatically switches to `--workers 2` when `DATABASE_URL` is set

## File structure (changed files from original)

```
accfino-main/
├── Dockerfile                          ← cleaned, added HEALTHCHECK
├── entrypoint.sh                       ← auto workers 1/2 based on DATABASE_URL
├── requirements.txt                    ← added psycopg2-binary==2.9.9
├── .env.example                        ← new — reference for all env vars
├── db_app/
│   └── database.py                     ← Postgres + SQLite fallback
├── main_app/
│   └── react_api.py                    ← CORS + marketing route + /health
└── react_frontend/
    └── public/
        └── index-marketing.html        ← new — AccFino marketing website
```
