AccFino
Intelligent accounting for Australian businesses: books and ledger, bank reconciliation with AI classification, payroll, tax and investments (CGT), lending analysis, cash-flow forecasting, subscriptions and live bank feeds - one app, one database, nine business modules on a shared platform.
What is in this package
```
backend/accfino/    core/ (platform) · shared/ (db, paths, llm, documents, contracts) · modules/<domain>/ · app.py (composition root)
frontend/src/       core/ (shell, auth, settings, admin, registry) · modules/<domain>/
deploy/             entrypoint.sh · data-seed/ (read-only first-run defaults) · windows/ · northflank.yml
docs/               architecture.md · development.md · ui-design.md · platform/ · operations/ · history/
Dockerfile · docker-compose.yml · .env.example · app.cmd (Windows double-click start)
```
Application code only. Business data and documents live in `../AccFino_Data` (`ACCFINO_DATA_ROOT`); tests and test data in `../AccFino_Testing`.
The modules
Module	What it does	Docs
accounting	ledger, sales/purchases, banking, expenses, assets, inventory, reports	README
reconciliation	statement pipeline, ML/LLM/RDR classification, sessions, company directory	README
cashflow	forecasting	README
trading	CGT (shares, crypto, property), tax-return data	README
lending	statement analysis for serviceability	README
payroll	employees, pay runs, payslips, PAYG/super, STP	README
taxation	BAS/IAS, income tax returns, CGT, FBT, Division 7A, calendar, workpapers, audit (prepares and records; does not lodge with the ATO)	README · docs
billing	Square/Stripe subscription billing	README
open_banking	Basiq and OpenFeed (CDR) bank feeds	README
Run locally
```bash
cp .env.example .env                       # set DATABASE_URL (PostgreSQL), JWT_SECRET, ADMIN_PASSWORD, ACCFINO_DATA_ROOT
cd backend && pip install -r requirements.txt
export PYTHONPATH=. ACCFINO_DATA_ROOT=../../AccFino_Data
python -m accfino.core.init_db
python -m uvicorn accfino.app:app --host 127.0.0.1 --port 8001 --reload
cd ../frontend && npm install && npm run dev        # http://localhost:3000 (proxies /api to :8001)
```
Windows: double-click `app.cmd` (stop: `deploy\windows\stop.cmd`). Docker: `docker compose up --build` (mounts `../AccFino_Data` at `/data`).
PostgreSQL is required (the ledger's integrity triggers); the SQLite fallback of earlier versions does not exist.
Test
`python ../AccFino_Testing/run_tests.py <domain|core|all>` - see docs/development.md.
Deploy
Container via the root `Dockerfile`; mount a persistent volume at `/data` (`ACCFINO_DATA_ROOT=/data`), set `DATABASE_URL`, `JWT_SECRET`. Details: docs/operations/DEPLOYMENT.md, service definition `deploy/northflank.yml`.
Read next
architecture · developing and testing by domain · UI design proposal · security · tenancy · subscriptions
