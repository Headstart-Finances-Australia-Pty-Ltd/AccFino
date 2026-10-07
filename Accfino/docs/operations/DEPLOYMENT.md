# Deploying Phase 0

## 1. Before you deploy
1. **Back up the Neon database** (Neon branch or `pg_dump`).
2. Add secrets in Northflank → Service → Environment:
   - `JWT_SECRET` - 64+ random characters (`python -c "import secrets;print(secrets.token_urlsafe(64))"`).
   - `ADMIN_PASSWORD` - only used if the admin account doesn't exist yet.
   - Leave `AUTH_MODE` unset (defaults to `enforce`), `MFA_ENFORCED` unset for now.
   - Sign-in methods: `WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGINS`, `SMS_PROVIDER` + provider keys, SMTP settings (see `docs/SECURITY.md`).
   - `PROXY_HOPS=1` for Northflank (2 if Cloudflare is in front).
3. Northflank: no path changes needed - the root `Dockerfile` builds `backend/` and `frontend/`.
4. **Rotate the Neon database password** (it was committed in the old `app.cmd`).

## 2. Deploy to staging first
1. Restore a copy of production into a staging database.
2. Deploy this branch to a staging service pointing at it.
3. `entrypoint.sh` runs `python -m accfino.core.init_db`, which applies the Phase 0 migration automatically (idempotent - safe on every restart).
4. Run the automated suite (from the separate `AccFino_Testing/` folder) against staging:
   ```
   cd AccFino_Testing
   export ACCFINO_BACKEND=/path/to/AccFino/backend
   export DATABASE_URL=<staging db url>
   export ACCFINO_BASE_URL=https://<staging host>
   export ACCFINO_ADMIN_EMAIL=admin@accfino.com ACCFINO_ADMIN_PASSWORD=<staging admin pw>
   pip install -r requirements-test.txt
   pytest -q
   ```
   Start staging with `LOGIN_IP_MAX_ATTEMPTS=100000 SESSION_CACHE_SECONDS=1 SMS_PROVIDER=console SMS_OUTBOX_FILE=/tmp/outbox.jsonl` while running the suite
   (and export the same `SMS_OUTBOX_FILE` for pytest), then restore the real SMS provider.
5. Work through the manual cases in `AccFino_Phase0_Test_Cases.xlsx`.

## 3. Production
1. Deploy. Users sign in once.
2. **Immediately change the admin password** (Settings → Security → Change password), then check Settings → Security → checklist.
3. Encourage users to enable two-step verification; set `MFA_ENFORCED=true` when ready (required before ATO DSP certification).

## 4. Rollback
- **Fast switch (no redeploy of code):** set `AUTH_MODE=report` and restart - requests are logged instead of blocked. Use only while fixing a blocking issue; it re-opens the vulnerabilities.
- **Full rollback:** redeploy the previous image. The Phase 0 tables are additive, and the only change to an existing table is a new nullable column `business_details.owner_user_id`, so the old version keeps working on the migrated database.

## 5. Database objects added
Tables: `user_sessions`, `access_policies`, `webauthn_credentials`, `mfa_challenges`, `organisations`, `org_memberships`, `user_security`, `system_settings`, `audit_log`, `tax_codes`,
`ledger_accounts`, `tracking_categories`, `tracking_options`, `journals`, `journal_lines`, `ledger_source_links`.
Functions/triggers: `accfino_block_change`, `accfino_journal_guard`, `accfino_journal_balanced`
(`trg_audit_log_immutable`, `trg_journal_lines_immutable`, `trg_journal_guard`, `trg_journal_balanced`).
Columns: `business_details.owner_user_id`; `user_security.phone_e164`, `sms_mfa_enabled`, `email_mfa_enabled`, `disabled_at`, `disabled_reason`, `must_change_password`.

## Northflank deployment and DNS (from the former README)

### Environment variables (Service → Environment → Secret Variables)

```
DATABASE_URL       postgresql+psycopg2://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require
JWT_SECRET         your-long-random-secret   (required from Phase 0)
ADMIN_PASSWORD     used only when the admin account is first created
STRIPE_SECRET_KEY  sk_live_xxx
RESEND_API_KEY     re_xxx
FROM_EMAIL         noreply@accfino.com
PYTHONPATH         /app/backend
ACCFINO_DATA_ROOT  /data
```

### Persistent volume (Service → Storage → Volumes)

| Mount path | Purpose |
|---|---|
| `/data` (`ACCFINO_DATA_ROOT=/data`) | ALL persistent business data and documents: reference data, runtime config, trained models, LLM caches, generated outputs, per-module files. See `AccFino_Data/README.md` for the layout. |

Without this volume everything under the data root is lost on every deploy. The application package itself (`/app`) is read-only code.

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



The Northflank service definition is `deploy/northflank.yml`; the container is built by the root `Dockerfile`.
