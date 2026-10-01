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


## Financial Reports - all 24 reports live (Books & Accounting)
The eleven reports that showed "Soon" are now built, each derived only from the posted ledger and sub-ledgers and each carrying its own reconciliation check where one exists:
Budget Variance (with budgets: create from last year, or PUT lines), Cash Summary, Management Report (P&L with comparative, ratios, 12-month trend, aged, GST, alerts), Expense Claims, PAYG Summary (BAS W1/W2, super), General Ledger Summary, Bank Reconciliation, Account Summary, Cash Validation, Journal Report, Inventory Item Details.
- New endpoints under `/ledger/reports/*` (`gl-summary, journal-report, cash-summary, account-summary, cash-validation, expense-claims, payg-summary, management-report, inventory-items, budget-variance, budget, budget/generate`); reads need `read`, budget writes need `post`.
- New table `org_budget_lines` (created by the normal migration).
- Fixes: the cash-flow statement now reconciles in a period that contains an asset disposal; the GST-account check no longer counts BAS payments/refunds as GST postings.
- Shared report UI moved to `reportKit.jsx`; new screens in `ExtraReports.jsx`.
- Demo data: `python -m accfino_core.seed_demo --user demo@accfino.com --verify` builds a complete demo organisation (15 months) through the real service layer and runs 19 cross-report reconciliation checks.


## General Ledger upgrade (journals workflow)
Closes the gaps against Xero, MYOB and ERPNext while keeping AccFino's rule that posted journals are immutable (correct by reversing).
- **Drafts and approval**: save a draft, submit for approval, approve/reject with a reason. Approvers: owner, admin, accountant. You cannot approve your own journal unless you are owner/admin.
  Optional per-organisation policy "require approval for manual journals". Drafts live in `ledger_journal_drafts` and never affect any report.
- **AI / rule bank suggestions** (Review tab): unreconciled bank lines become reviewable journals with a confidence and a reason. Evidence order: matching open invoice/bill/payment (90-99%), bank rule (95%), what the
  organisation has taught the classifier (75-95%). Approve / adjust the account / reject / bulk-approve at a chosen confidence. Approving uses the same path as manual reconciliation and teaches the classifier.
- **GST on manual journals**: "amounts include GST" / "exclude GST" adds the GST line and carries the tax amount so BAS 1A/1B is right. A 10% tax code with no GST treatment is now refused (it used to be silently dropped).
- **Auto-reversing journals** (accruals), **reference** on every journal, **attachments** on journals and drafts, **copy journal**, **history & notes** per journal, links back to the source invoice/payment/claim.
- **Repeating journals** with {month}/{year}/{fy}/{quarter}/... labels; each occurrence becomes a draft (or posts, approvers only). Run with "Run due now" (there is no background scheduler).
- **CSV import**: check first, all-or-nothing, as drafts (default) or posted (approvers). Template download.
- **Journals list**: search (narration, reference, number, contact), all sources, status, account, amount range, paging, CSV export.
- **General Ledger (detailed)** report: multiple accounts, party, tracking, source, text and amount filters; group by account / journal / party / tracking / source / month; opening, running and closing balances; consolidate by voucher; CSV.
- **Ledger health strip**: drafts, approvals, AI suggestions, repeating due, future-dated journals, suspense balance.
- Manual journals to the AR/AP control accounts are now blocked (they put the sub-ledger out of step).
- New tables `ledger_journal_drafts`, `ledger_repeating_journals` and column `journals.reference` are created by the normal startup migration.
- **Bug fix (reports)**: on the reports added earlier, changing the dates/filters and pressing Run re-queried with the OLD values. Fixed once in `useReport`; regression tests added.
- Not built: P&L by tracking option, multi-currency journals, MYOB-style splitting one line across several jobs, an LLM classifier for suggestions (rules, learned memory and document matching only).


## General Ledger upgrade, part 2 (closes the remaining gaps)
- **AI bank-coding, RDR + Groq**: after your own bank rules and what the organisation has taught, unreconciled lines are tried against the platform's RDR rules (deterministic; rule account names are mapped onto the organisation's own chart; 85%) and, if the organisation has switched it on, Groq through the existing shared key pool (`groq_key_pool`, with its rotation and cool-down). The model sees only the organisation's postable accounts and must answer with one of their codes; anything else is discarded; confidence is capped at 80% and answers under 50% are dropped. Bank narrations sent to the model have long digit runs and emails masked. **Off by default** (Review tab, approvers only, with a consent prompt). AI and RDR suggestions can never be bulk-approved (the lowest bulk threshold is 90%), a person always decides, and approving one teaches the organisation's own memory. Per-run budget of 25 model calls; a merchant seen twice in a run costs one call; if no key is available the run carries on with rules and RDR.
- **Background scheduler** for repeating journals: opt in per template ("run automatically"). A daemon thread checks every `ACCFINO_SCHEDULER_SECONDS` (default 900) using the business date in `ACCFINO_TZ` (default Australia/Sydney); `ACCFINO_SCHEDULER=0` turns it off. Safe with several workers/replicas: a PostgreSQL advisory lock allows one sweep at a time, each template row is locked with SKIP LOCKED, and an occurrence that already exists is never created again. An auto-run template that POSTS is honoured only while its creator is still an approver; otherwise it becomes a draft. Each sweep stores a heartbeat (shown on the Repeating tab) and writes an audit entry under the name "scheduler".
- **Tracking Profit & Loss** report: one column per option of a tracking category plus Unassigned and Total; the columns are checked against the ordinary Profit & Loss and the screen warns if they ever differ. A line tagged with several options of the same category is shared equally.
- **Split a line across jobs** (MYOB-style allocation): one journal line split by percentage or amount across tracking options; the parts always add back exactly (the last part takes the rounding) and GST is split in the same proportions. Works in the editor, drafts, repeating templates, and CSV import (`Sydney:60;Melbourne:40` in the Tracking column).
- **Multi-currency journals**: enter a journal in a foreign currency at a stated rate; the ledger holds base-currency amounts and keeps the original amounts and the rate on the journal and each line. The journal must balance in the foreign currency; any cent left by per-line conversion is absorbed in the largest line and shown. Rates come only from the organisation's own **Exchange rates** table or are typed on the journal - AccFino never guesses or fetches one (the legacy currency service's hard-coded fallback rates are deliberately not used). Auto-reversals and reversals keep the currency and rate; repeating templates look up the rate for each occurrence's date and stop with an error if there is none. GST calculation is not available on foreign-currency journals.
- New tables/columns (created by the startup migration): `ledger_fx_rates`; `journals.currency/exchange_rate`; `journal_lines.orig_debit/orig_credit`; `currency`/`exchange_rate` on drafts; `currency`/`auto_run` on repeating journals.
- Demo data: USD rates and a USD journal, a 50/30/20 split across regions, an auto-run template.
- New env settings: `ACCFINO_SCHEDULER`, `ACCFINO_SCHEDULER_SECONDS`, `ACCFINO_TZ` (see `.env.example`).
- (Part 2 listed foreign-currency revaluation, bank accounts, rate feeds, CSV currency columns, GST on foreign journals and wider AI as not built; part 3 below delivers them.)
- **Verified on SQLite only** (not on your PostgreSQL): the PostgreSQL-specific parts - the advisory lock, `FOR UPDATE SKIP LOCKED`, and the `ALTER TABLE` statements - are written to the standard syntax but have not been executed here. The Groq call itself was tested against a fake HTTP layer, not the live API.


## General Ledger upgrade, part 3 (foreign currency completed, wider AI)
- **Foreign-currency accounts.** A bank account, card or loan can be *held in* a currency (Ledger > Foreign currency), only while it has no postings, so its foreign balance is exact from the first entry. Every posting to it must be in that currency (enforced in the posting engine); a base-currency journal, or a base-currency invoice/bill payment, is refused with an explanation. Bank statement lines on such an account are in that currency.
- **Realised gains and losses.** Money in is booked at the day's rate. Money out leaves the account at its **average cost**; the difference to what was received or bought is a realised gain/loss on the *Realised Foreign Exchange* account. Emptying an account takes all of its cost, so no stray cents remain. Spend/receive money (with GST), AUD<->foreign conversions (using the amounts the bank really moved, from the paired statement line or the amount you enter), same-currency transfers, and un-reconcile all work. Two different foreign currencies must go through the base-currency account.
- **Period-end revaluation.** Ledger > Foreign currency > Revaluation restates each foreign account to the closing rate: one journal per currency to *Unrealised Foreign Exchange*, auto-reversing the next day (so nothing is counted twice). Repeating for the same date posts only the difference (e.g. after correcting a rate). A missing closing rate stops the run and names the currency. Approvers only; locked periods are respected. Historical cost is always measured excluding revaluation journals.
- **FX gains & losses report** (realised/unrealised by currency, positions at cost and at the closing rate).
- **Bank reconciliation** for a foreign account compares the statement with the ledger *in that currency*; the account list shows the foreign balance and its value at cost.
- **GST on foreign-currency journals.** GST is calculated in base currency on the converted amount (10% of the dollars, as the BAS needs), the GST account line is the sum, original foreign amounts are kept, and any cent of conversion rounding is absorbed in the largest non-GST line and reported. Works with inclusive/exclusive, split lines and CSV import. Bank-line coding on a foreign account does the same.
- **Automatic rate feed** (opt-in per organisation): daily ECB *reference* rates, converted to the base currency by cross rate, for the currencies you choose plus any used by foreign accounts, drafts and repeating templates; 90-day back-fill; run by the scheduler once per business day or with "Fetch now". A rate you entered for a day is never overwritten (manual wins); a failed or malformed download changes nothing and is reported. The feed URLs are `eurofxref-daily.xml` and `eurofxref-hist-90d.xml` on ecb.europa.eu.
- **CSV import** accepts `Currency` and `Rate` columns (one currency and rate per journal; blank rate = your stored rate for the date; no rate available is a row error).
- **AI beyond bank coding** (separate opt-in, `llm_assist`, approvers only, off by default, 20 requests/hour/organisation, every call audited): (1) *Describe a journal* - a sentence becomes a proposed journal using only your own account codes, validated by the normal preview engine, and it only fills the editor; (2) *AI review* - an approver's second opinion on a submitted draft, alongside the deterministic checks, advisory only; (3) *Explain the change in profit* - AccFino computes the movements, the model writes the summary, and the summary is withheld if it quotes a figure that is not in the data. Contact names are never sent; long digit runs and emails are masked.
- New: `ledger_accounts.foreign_currency` (added by the startup migration); system accounts *Realised/Unrealised Foreign Exchange* are created on first use. No new environment variables. Demo data: a USD operating account (opening deposit, client receipt, GST-coded USD purchase) revalued at the demo date.
- **Fixed in this pass**: the model-reply JSON reader could return an inner object instead of the whole reply; USD demo rates were stored upside-down; a rate typed before the stored-rate lookup returned could be overwritten by the late response.
- **Limits that remain**: invoices and bills are still in the base currency (so receivables/payables are not revalued - foreign-held accounts are); manual journals to a foreign account book at spot, not average cost (only bank-feed postings compute realised gains); foreign-to-foreign transfers must go via the base currency; revaluation is run by a person (not automatic); the rate feed is one source (ECB reference rates, not the rate your bank gave you).
- **Verified on SQLite only.** The PostgreSQL-specific pieces (the new ALTER TABLE, advisory lock, SKIP LOCKED) were not executed against PostgreSQL. The Groq and ECB calls were tested against fake HTTP responses; neither live service was contacted, and the ECB URLs are from memory - confirm them.
