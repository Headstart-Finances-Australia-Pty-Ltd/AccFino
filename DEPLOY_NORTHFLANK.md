# Deploying AccFino 2.0 on Northflank

Everything below was rehearsed against a real PostgreSQL 16: a fresh database is created by the start-up script (all tables including the 46 Practice tables), a second start is safe, the UI, landing page and the new bulk-load routes respond, and `deploy/smoke_test.sh` passes. The Docker image itself could not be built in the preparation sandbox (no Docker Hub access), so the first Northflank build is the first full image build; its inputs (npm lock file, Python 3.11 requirements, Dockerfile paths) were checked separately.

## 1. Before you start
* A PostgreSQL database (Neon works). Copy its connection string.
* Make the **AccFino folder itself the root of your Git repository** (the folder that contains `Dockerfile`, `backend/`, `frontend/`, `deploy/`).

## 2. Create the service
1. Northflank > Create service > **Combined service** (build + run) from your Git repository.
2. Build: **Dockerfile**, Dockerfile path `/Dockerfile`, build context `/`.
   (If you instead keep AccFino as a sub-folder of a bigger repo, use path `/AccFino/Dockerfile` and context `/AccFino`. The two must name the same folder, otherwise you get `"/frontend": not found`.)
3. Port: `8001`, HTTP, public.
4. Plan: at least 0.5 vCPU / 512 MB (1 vCPU / 1 GB recommended).
5. **Volume**: mount a persistent volume (5 GB or more) at `/data`. Without it uploaded files and generated documents are lost on every deploy.
6. Health check: HTTP `/ready` on port 8001, initial delay 120 s (models take 30 to 90 s to load).

## 3. Environment variables (secrets as Northflank *secrets*)
| Name | Required | Value |
|---|---|---|
| `DATABASE_URL` | yes | `postgresql+psycopg2://user:pass@host/db?sslmode=require` (Neon `postgres://` and `postgresql://` forms are also accepted) |
| `JWT_SECRET` | strongly | 64+ random characters |
| `ADMIN_EMAIL` | yes (first start) | the platform administrator's e-mail |
| `ADMIN_PASSWORD` | yes (first start) | used only when the admin account is first created. If it is missing, the public default password is used: change it at once |
| `ADMIN_PHONE` | recommended | `+61...` |
| `APP_URL` | yes | your public address, `https://...` with no trailing slash (e-mail links, portal invitations, bank feeds) |
| `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGINS` | for passkeys | host name of `APP_URL`; the full `APP_URL` |
| `ACCFINO_DATA_ROOT` | no | `/data` (default) |
| `CORS_ORIGINS`, `TENANT_BASE_DOMAIN` | optional | only if you use extra origins or organisation sub-domains |
| `SMTP_*`, `FROM_EMAIL`, `STRIPE_*`, `SMS_*` | optional | see `.env.example` |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | optional | default 4 + 4; raise to 8 + 8 if pages queue |
| `ACCFINO_PROFILE=1`, `ACCFINO_SLOW_MS` | optional | log slow requests with their query count |

The service reads `PORT` itself; leave Northflank's default.

## 4. First start
The start-up script validates `DATABASE_URL`, prepares `/data`, creates or upgrades the database schema (safe to repeat), and starts the app. Watch the log for `Database ready` and then `Application startup complete`; `/ready` returns 503 until the models have loaded.

## 5. Verify
```
sh deploy/smoke_test.sh https://your-app.code.run
```
All lines should say `ok` and finish with `SMOKE TEST PASSED`. Then sign in as the admin, open Admin > Security status and clear any warnings.

## 6. Turn on the new modules
Admin > Pricing / Modules Management: make sure the plans you sell include the domain (Practice & Client Services is in Ultra or the A$25 add-on). In each Practice organisation the Org Admin creates the practice workspace once. Bulk CSV loading can be switched off platform-wide with the system setting `platform.bulk_import` = `off`.

## 7. Updating, backups, rollback
* Back up PostgreSQL before each release (Neon: create a branch or snapshot).
* Deploy a new build; the schema upgrade runs automatically. Existing data is kept.
* Rollback: redeploy the previous build. New tables are additive and ignored by older builds.

## 8. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `"/frontend": not found` | Dockerfile path and build context name different folders (see step 2) |
| Container exits at once: `DATABASE_URL is not set` | add the secret |
| `DB init failed` | wrong connection string, or the database blocks Northflank's address; test with `psql` |
| `/ready` stays 503 | wait up to 2 minutes; check memory (512 MB is the minimum) |
| Pages slow | put the database in a region near the service (Sydney), use the pooled connection string, see `DB_POOL_SIZE`, and enable `ACCFINO_PROFILE=1` |
| Files disappear after a deploy | the `/data` volume is not mounted |
