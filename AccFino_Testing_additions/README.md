# Ledger workflow tests
Offline (SQLite) end-to-end tests. From `backend/`:

    DATABASE_URL=postgresql://x:y@localhost/none python3 -m accfino_core.seed_demo --sqlite /tmp/demo.db --today 2026-09-30 --verify
    python3 ../AccFino_Testing_additions/ledger_api_test.py      # 92 checks over HTTP; works on a COPY of /tmp/demo.db

    python3 ../AccFino_Testing_additions/advanced_ledger_test.py  # 129 checks: RDR + Groq coder (fake HTTP), scheduler, P&L by tracking, split lines, multi-currency

    python3 ../AccFino_Testing_additions/fx_ledger_test.py  # 145 checks: GST on foreign journals, foreign bank accounts, realised/unrealised FX, revaluation, ECB feed (fake HTTP), CSV currency, AI assistant (fake model)

They exercise GST handling, drafts and approval (incl. segregation of duties and the require-approval policy), AI/rule suggestions and bulk approval,
repeating journals, CSV import (dry-run, all-or-nothing), auto-reversal, the detailed general ledger, and audit events.
Frontend: `npm test` (vitest) - `src/pages/ledger/__tests__/JournalTools.test.jsx` and `src/pages/accounting/__tests__/ExtraReports.test.jsx`.
These were run on SQLite, not PostgreSQL - run them once against your own database after deploying.

The Groq call is tested against a fake HTTP layer; the PostgreSQL-only pieces (advisory lock, SKIP LOCKED, ALTER TABLE) are not exercised on SQLite.
`dump_pl_fixture.py` regenerates the Tracking P&L test fixture from the advanced test database.

fx_ledger_test.py and advanced_ledger_test.py start from a demo built with `--no-foreign-demo`:
    python3 -m accfino_core.seed_demo --sqlite /tmp/demo_nofx.db --today 2026-09-30 --no-foreign-demo
