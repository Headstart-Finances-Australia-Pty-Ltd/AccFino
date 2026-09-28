# AccFino Phase 0 - Platform Foundation

**Status:** ready for staging test · **Automated tests:** 94 passed / 27 skipped (modules not built) / 3 expected failures - `AccFino_Testing/` (see `phase0/PHASE0_AUDIT.md`) · **Date:** 26 Sep 2026 (rev 5)

Phase 0 adds the foundation every later phase builds on: server-side security, organisations, a
double-entry general ledger and an Australian chart of accounts. Existing features keep working;
the regression suite replays all 54 original GET endpoints and they respond as before.

## Rev 6 - navigation by business domain, Admin module switch, audit fixes
- Side panel now has four sections: **Platform** (Overview), **Business Modules** (Books and Accounting, Payroll & Workforce, Taxation & Compliance, Assets/Investments & Wealth, Smart Lending/Credit & Treasury, Planning & Intelligence), **Supporting Modules** (Practice & Client Services, Settings) and **Admin** (Admin Console, admin users only). Each domain is one link to a hub page whose tabs are its modules; tab labels are short so they stay on one line.
- **Admin -> Modules**: tick/untick any domain or module to show/hide it across the side panel, hub tabs, Overview and the public landing page (`/module-visibility`; admin-only writes).
- **Home** (top bar, before Logout) opens the public landing page; a signed-in visitor sees **Go to Overview** instead of Sign in / Start free.
- Open Banking, Integrations and API & Webhooks moved into **Settings**; Payments removed from navigation (renewal prompt is the existing UpgradeBanner).
- **Security fixes found by the Phase 0 audit** - see `PHASE0_AUDIT.md`: module-visibility writes were open to every signed-in user (now admin-only); its read now works before sign-in.
- **Payroll:** super guarantee is now **12%** (engine and payslip label); Payroll modules are labelled **Preview** because the PAYG tables are still the ATO 2023-24 schedule.
- **Module visibility** is stored in the database (`platform_settings`), so every instance/worker agrees; an old `module_visibility.json` is imported once.
- **Front end** loads route pages on demand (entry chunk 146 kB, largest 400 kB; was a single 1.3 MB file); `npm test` runs 19 unit tests.
- **Overview and side panel** no longer show provider switches (Basiq, OpenFeed, Square, Stripe, Groq key pool, ML training, Database, S3, System email, Calendly, Meeting link) as tiles under Books and Accounting / Smart Lending. They stay switchable in Admin > Modules Management and keep working in Settings/Admin.
- Superseded: the navigation described in Rev 4 and Rev 5 below.

## Rev 5 - domain navigation and a single module registry
- Side panel grouped by business domain: Business Finance, Payroll & Workforce, Tax & Compliance, Assets &
  Investments, Lending & Treasury, Planning & Insights - with live modules and dimmed "Soon" entries.
- One registry (`frontend/src/config/modules.json`) now drives the side panel, the Home page and the landing page.
- Home page shows every domain with Live / Preview / Soon status; Overview renamed Home.
- Accounting and Tax/Investment pages open the right tab from the address (`?tab=`), so each side-panel entry
  highlights correctly.
- Landing page: module section generated from the registry; statements that weren't true yet removed or
  corrected - "ATO compliant", "lodge", "BAS Direct Lodgement", "STP Phase 2", "ATO-ready", "BAS-ready",
  "included in all plans" for cash flow (it requires Accounting Pro), and "AU hosted" / "AU data residency"
  (the databases are currently in the USA). The unverified "95% auto-classified" figure was removed with the old section.

## Rev 4 - navigation and organisation Identity
- **Settings** (all users) with tabs **Setup · Organisation · Identity · Security**.
  Identity is shown to organisation owners/admins; Security is personal (MFA, devices, password).
- **Admin** (AccFino super admins only) with tabs **ML Classifier · Admin & Licence · File Manager · Pricing ·
  Platform Users · Company DB**.
- **Organisation Identity** (Settings → Identity): owners/admins see every member's status, MFA and last sign-in;
  suspend/restore a member's access to the organisation. For members whose *home* organisation it is: sign out
  everywhere, reset MFA, require password change, devices and sign-in history. Account-wide actions are limited to
  home members so an organisation admin can't add a stranger by email and weaken their account.
- Old addresses (/setup, /security, /licence, /pricing-admin …) redirect to the new ones.
- Side panel scrolls on small screens; security checklist split into "Fix now" and "Before go-live".

## Rev 3 additions - IAM step 2 (Microsoft Entra-style)
- **Device sessions:** every sign-in is a named session (browser/OS, IP, methods, last active). Users sign out any
  device or all others; logout now ends only the current device.
- **Identity admin page** (Admin → Platform Users): search/filter users (active, disabled, locked, no MFA);
  disable/enable with audited reason; sign out everywhere; reset MFA; unlock; require password change; end sessions;
  sign-in history.
- **Conditional Access per organisation** (Settings → Organisation → Access policy): require MFA, accepted methods, IP
  allow-list, sign-in frequency, scope, report-only mode, lock-out protection.
- **Forced password change** flow with a Change password card on the Security page.
- **Security fix - IP spoofing:** the app trusted the first `X-Forwarded-For` entry, which any client can set,
  weakening login throttling. Now only the proxy-added address is trusted (`PROXY_HOPS`).
- **Safety guard:** AccFino refuses to create or alter tables in a database that belongs to another application.
- Accepts any PostgreSQL URL form (`postgresql+asyncpg://`, `postgres://`, `?ssl=require`).
- Windows: `app.cmd` restored at the top level; Python 3.13/3.14 install fixed; `JWT_SECRET` auto-generated.

## Rev 2 additions
- **Choice of sign-in verification** (Security → Sign-in methods): face or fingerprint (passkeys: Face ID, Touch ID,
  Windows Hello, Android), authenticator-app passcode, code sent to phone (SMS), email code, recovery codes.
  Users can enable several; the sign-in prompt offers each one.
- **"Sign in with face or fingerprint"** on the login page - passwordless sign-in with a passkey.
- **Windows launcher crash fixed** ("Could not import module main_app.api_call" / "AUTH API CRASHED"): the launcher
  started a module that was deleted upstream. It now starts only the main API and reads settings from `.env`.
- **Leaked production database password removed** from the launcher. It remains in public git history - **rotate the Neon password**.
- **Clean structure**: `backend/`, `frontend/`, `deploy/`, `scripts/`, `docs/`; tests and test documents moved to the
  separate `AccFino_Testing/` folder. `docker-compose.yml` and `.env.example` added.
- Fixed: after login the app fetched the plan before storing the new token, causing a 401 and a page reload;
  a wrong password no longer reloads the page (the error message now stays visible).

## What users will notice
- Everyone signs in once after the upgrade (old browser sessions had no token).
- New menu items: **General Ledger** (all users), **Organisation** and **Security** (Control Panel).
- New and changed passwords need 8+ characters including a letter and a number. Existing passwords still work.
- Optional two-step verification (authenticator app + recovery codes).
- Users only ever see their own data. Previously some screens showed other customers' records (below).

## M1 - Security, identity, multi-tenancy
| Change | Detail |
|---|---|
| Session tokens | Login now issues a signed JWT (8 h). The frontend already expected one; it was never issued. |
| Auth guard on every route | Resolves the real route (with or without `/api`) and applies public / signed-in / admin policy. |
| Ownership enforcement | Non-admin callers can't pass another `user_id`/`username` in path, query, JSON body or upload form. Routes with an optional `user_id` are scoped to the caller. |
| Admin-only tools | DB browser, file manager, key pool, licences, payments admin, pricing edits, company approval, ML training, API docs. |
| Disabled | `GET /auth/login` (password in URL); `POST /shutdown` (unless `ALLOW_SHUTDOWN=true`). |
| Login protection | Lockout after 10 failures (15 min), per-IP throttle, audit of every attempt. |
| MFA | TOTP enrolment with QR code, 8 single-use recovery codes, `MFA_ENFORCED` switch. |
| Sessions | Password change and "sign out everywhere" revoke other tokens (token versioning). |
| Audit log | Append-only (DB trigger). Records logins, security events, every write request and every ledger change. |
| Admin checklist | `/security` shows default-password, JWT secret, MFA and other posture checks. |

### Security defects fixed
1. **Anyone on the internet could read and edit every table** through `/api/db-browser` (no login needed). Fixed.
2. **No API authentication at all** - any caller could read any user's data by changing `user_id`. Fixed.
3. **Admin password reset to the public default `Accfino@1` on every restart.** Now only set on first install or with `ADMIN_FORCE_RESET=true`. Change the admin password after deploying.
4. **Aged receivables returned every tenant's unpaid invoices.** Now reads the user's own sales invoices.
5. **Legacy business/invoice records had no owner** and were visible to all users. New `owner_user_id`; legacy rows without an owner are admin-only.
6. **Payroll employee list returned all tenants' employees** when no `user_id` was sent. Now scoped automatically.
7. **`entrypoint.sh` started `main_app.api_call`, which was deleted upstream**, so a fresh container exited before the app started. Removed.

## Organisations
- One organisation per user created automatically, owning that user's existing data (`legacy_user_id`).
- Roles: owner, admin, accountant, bookkeeper, payroll, readonly. Add existing users by email.
- Organisation details (legal name, ABN with checksum validation, entity type, GST basis, financial year end).
- Lock date: nothing can be posted, reversed or re-synced on/before it.
- Create further organisations; switch with the selector (sent as `X-Org-Id`).

## M2 - Double-entry ledger engine
- `journals` / `journal_lines` with NUMERIC(18,2) amounts, Decimal arithmetic, half-up rounding to cents.
- Single posting service validates: 2+ lines, one side per line, debits = credits, same-org accounts, active accounts, lock date.
- PostgreSQL triggers are a second line of defence: journal must balance at commit (deferred constraint trigger), posted lines can't be updated/deleted, journals can't be deleted or have core fields changed.
- Reversal workflow (never edit, always reverse).
- Reports: trial balance, profit & loss, balance sheet (prior-year earnings rolled into retained earnings), account transactions with running balance.
- **Bank sync**: posts saved reconciliation transactions to the ledger. GST split to 820, internal transfers via 855 Transfers Clearing, loan principal/interest split, uncoded to 850 Suspense. Idempotent; changed transactions are reversed and re-posted; deleted ones reversed; locked periods respected. Preview mode.

## M3 - Chart of accounts, tax codes, tracking
- 76-account Australian template per organisation including all 53 legacy accounts (same codes and names) plus AR, AP, GST, PAYG withholding, super payable, wages payable, income tax payable, retained earnings, suspense, transfers clearing, rounding, historical adjustment.
- Accounts added to the legacy global COA are imported as `U###` accounts.
- 11 GST tax codes; names match the legacy `gst_category` values; BAS labels stored for Phase 2.
- Up to two tracking categories with options on journal lines.
- System accounts can't be archived; accounts with a balance can't be archived.

## Not changed in Phase 0 (planned)
- Legacy money columns (transactions, accounting documents) are still floating point; they move to NUMERIC when Sales/AR and Purchases/AP post to the ledger in **Phase 1**. The ledger itself is exact.
- The Setup page still edits the **global** COA, rules and knowledge base shared by all customers (now audit-logged). Phase 1 moves the classifier to per-organisation data.
- Payroll tax tables (2023-24), 11% SG and simulated STP are unchanged - fixed in **Phase 2 (M9/T4)**.
- `react_api.py` is not yet split up (M24 continues in each phase).

## Known limitations
- The per-IP login throttle is per worker process (the account lockout is database-backed and global).
- The new screens were build-verified and their APIs fully tested, but no browser was available in the build environment; the manual cases in the test workbook are their first click-through.
- The legacy "Invoice" page calls `/invoice/businesses` (plural), a route that doesn't exist in the live app; that pre-existing issue is unchanged and will be resolved when invoicing is consolidated in Phase 1.
