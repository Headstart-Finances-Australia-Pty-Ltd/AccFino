Copy these files over the same paths in your AccFino folder, then restart the backend and rebuild the frontend (npm run build).

EMAIL: security/messaging.py, db_app/api/password_reset.py - System Email saved in Admin Console > API Keys is now used for verification and reset emails.
FORCE DELETE: force_delete.py, api/force_delete_api.py - clears references that blocked the delete; errors name the real cause.
ADMIN LOCK: migrate.py - database trigger: the AccFino admin account can never be deleted (installed at next start).
USERS & LICENCE: api/org_directory_api.py (+ __init__.py), OrgDirectoryPanel.jsx, LicencePage.jsx - organisation list with admin email/phone, licence, users, roles.
LIVE UPDATE: deleted rows disappear immediately (no page refresh); all admin tables refresh together; server sends no-store.
FORCE DELETE HIDDEN WHEN OFF: the button and all selection checkboxes are not shown unless Force delete is ticked in Modules Management.
SIGN-UP: components/signup/SignupFlow.jsx - the Create / Join buttons now stay inside the 'Create your account' card and wrap their text.
AUDIT LOG: SecurityPage.jsx, platformApi.js, api/audit_api.py - the Organisation audit log table is shown only to the AccFino administrator (platform-wide, with an Org column); other users never see or request it, and /audit returns 403 for them.
EMPTY ORGANISATIONS: force_delete.py, api/org_directory_api.py, OrgDirectoryPanel.jsx, booksApi.js - deleting a login now also removes an organisation left with no users; 'Remove N empty organisations' button clears the existing leftovers (organisations with posted journals are kept unless Force delete is on).

PRICING & PLANS (domain based): subscription/service.py (+ api/subscription_api.py, SubscriptionCard.jsx, SubscriptionAdminPanel.jsx)
  Plans are now grouped by the 7 business domains (a plan/add-on can include a whole domain as "domain:<id>"). AUD per month, GST incl.
    Essentials  A$25 / A$250 yr   3 users    Books core + cash-flow forecasting
    Business    A$59 / A$590 yr   10 users   Books & Accounting (all) + Planning & Intelligence
    Professional A$99 / A$990 yr  25 users   + Payroll & Workforce + Taxation & Compliance
    Complete    A$179 / A$1790 yr unlimited  every domain
  Domain add-ons: Payroll 15, Tax 15, Planning 15, Assets & Investments 12, Lending & Treasury 19, Practice 25 (A$/mo);
  module add-ons: Inventory 12, Expenses 6, Fixed assets 10, Bulk import 8; 5 extra users 15.
  An existing installation is moved ONCE: new plans are added, the old Starter/Growth/Premium are retired (organisations on them keep their plan),
  default plan for new organisations = Essentials. Edit anything in Admin > Modules Management > Subscriptions.
LICENCE MANAGEMENT: signup_api.py no longer creates a per-user "base plan" licence; migrate.py removes the untouched auto-created ones at start;
  react_api.py lists only people who belong to an organisation (+ the AccFino admin); org_directory_api.py + OrgDirectoryPanel.jsx add
  "Delete N logins without an organisation" for leftovers.

LANDING PAGE + LOGIN: frontend/public/index-marketing.html - hero, metrics, comparison table (Xero/MYOB/Zoho, AUD, Jul-Sep 2026), pricing section now show the
  domain-based plans, domain add-ons and 7 business domains, loaded live from the new public endpoint GET /public/pricing
  (api/public_pricing_api.py + middleware.py public list + __init__.py), with the shipped catalogue as an offline fallback. Old Vault/Opus/"free base plan" copy removed.
  LoginPage.jsx - when sign-in fails because no account exists, a "Sign up" button appears directly under the message.

OPEN BANKING VIA OPENFEED (CDR): accfino_core/openfeed_cdr.py + api/openfeed_api.py (+ __init__.py, migrate.py, middleware.py, react_api.py), BankFeedCard.jsx, OpenBankingPage.jsx, booksApi.js, api.js
  AccFino registers ONE app with OpenFeed (AccFino admin, once: Settings > Open Banking > "OpenFeed platform setup": generate keys, paste the public key set into
  app.openfeed.au, paste back the two IDs). Each organisation's admin then presses "Connect my bank" - no OpenFeed registration/dashboard visit by the client.
  Flow: AccFino -> OpenFeed sign-in (email code, created on first use) -> bank login/CDR consent at the bank -> "share with AccFino" -> back in AccFino.
  AccFino keeps the (encrypted) refresh token and pulls accounts/transactions; Reconciliation lists the organisation's shared accounts and pulls through /openbanking/pull.
  Set in production:  APP_URL=https://<your public AccFino URL>   (used for the redirect back from OpenFeed)
                      FIELD_ENCRYPTION_KEY=<a Fernet key>          (optional; otherwise derived from JWT_SECRET)
  The old per-platform stub (/openfeed/connect, /openfeed/disconnect) is removed.

WHY ACCFINO + USER-BASED PRICING: frontend/public/index-marketing.html, subscription/service.py, SubscriptionCard.jsx
  "Why AccFino" section redesigned (4 benefit cards with mini visuals + a trust strip). Plans now scale with users:
    Essentials A$25 = 1 user | Business A$59 = 3 | Professional A$99 = 6 | Complete A$179 = 15. No plan is unlimited.
    Extra users: A$6 each, or 5 for A$25 (Zoho Books charges ~A$4.40). Existing installs move once (catalogue v3) - only plans/add-ons nobody edited.
  Also fixed: an add-on listed twice used to be counted twice for seats.
  Removed the "data never leaves AU infrastructure" claims (cannot be verified from the project; the dev database in the zip is in US East).

ADMIN CONSOLE > PRICING: frontend/src/pages/PricingAdminPage.jsx - the page now shows the CURRENT plans (domain-based, with users, add-ons, each organisation's plan)
  instead of the old Vault/Trading price list. The old per-user plans are kept behind a "Show legacy per-user plans" button (the old checkout still reads them).
LOGO URL: frontend/public/accfino-logo.svg + .png, served publicly at https://<your domain>/accfino-logo.svg and /accfino-logo.png (react_api.py routes + middleware public list).

ADMIN CONSOLE > OPEN BANKING (platform set-up for Basiq + OpenFeed): new tab in Admin Console. Basiq API key is saved encrypted there (no .env edit / restart needed; a
  server BASIQ_API_KEY still wins), with a Test connection button. OpenFeed's key/ID set-up moved there too. Settings > Open Banking is now client-only:
  no keys, no setup instructions - just "Connect my bank" (OpenFeed) and the Basiq account tools; if the platform isn't set up, clients see "contact AccFino support".
  Files: accfino_core/openbanking_setup.py, api/openbanking_admin_api.py, open_banking/auth.py + user.py (read settings live), OpenBankingSetupPage.jsx,
  BasiqPlatformSetup.jsx, OpenFeedPlatformSetup.jsx, OpenBankingPage.jsx, BankFeedCard.jsx, AdminHub.jsx, App.jsx, booksApi.js, react_api.py.

ADMIN CONSOLE REORGANISED: "Open Banking" and "Payment Card Setup" are now tabs INSIDE Admin Console > API Keys (with Platform Settings and ML Training), not separate menu items.
  Old addresses /admin/open-banking and /admin/payments redirect to the right tab; /admin/api-keys?tab=open-banking|payments deep-links. Files: AdminPage.jsx, AdminHub.jsx, App.jsx,
  OpenBankingSetupPage.jsx + PaymentGatewayAdminPage.jsx (new "embedded" mode), OpenBankingPage.jsx / BankFeedCard.jsx (links).

OPENFEED "did not accept the request" FIX (found by comparing with a working open-source OpenFeed client):
  - PAR now carries the DPoP proof header (it was missing); scopes are now `openid offline_access openfeed-au:data:banking:read` (offline_access gives the refresh token);
    the client assertion carries the key id (kid); token calls send client_id; no extra `resource` / `grant_management_action` parameters.
  - The redirect URI MUST be registered at OpenFeed (earlier guide said it need not be). Admin card now shows the exact value and the three scopes to tick.
  - New "Test OpenFeed set-up" button shows OpenFeed's own error (invalid_scope / invalid_redirect_uri / invalid_client ...). The administrator also sees it when pressing Connect.
  - IMPORTANT: generate the keys again (Admin Console > API Keys > Open Banking) and paste the NEW public key set into OpenFeed - older keys have no key id.
  Files: accfino_core/openfeed_cdr.py, api/openfeed_api.py, OpenFeedPlatformSetup.jsx, api.js, openfeed_test.py, OPENFEED_SETUP.md

AUTOMATIC SUBSCRIPTION BILLING VIA SQUARE (see SQUARE_BILLING_SETUP.md): accfino_core/billing/* (models, square_client, service, runner), api/billing_api.py, __init__.py, migrate.py,
  react_api.py (starts the renewal loop), BillingCard.jsx (organisation: add card, subscribe monthly/yearly, history), SquarePlatformPanel.jsx (Admin: Square credentials sealed, test, billing overview),
  SubscriptionCard.jsx, PaymentGatewayAdminPage.jsx, booksApi.js. New tables org_billing, billing_charges are created at start.

OPENFEED invalid_client FIX: accfino_core/openfeed_cdr.py - signed timestamps used datetime.utcnow().timestamp(), which a server in an Australian time zone shifts by 10-11 hours, so OpenFeed rejected
  every signature (invalid_client). Now uses real UTC time. Also: "Show public key set" (re-copy the key set without regenerating), key id + fingerprint on the card, clock-skew check and
  invalid_client hints in the Test button. Files: openfeed_cdr.py, api/openfeed_api.py, OpenFeedPlatformSetup.jsx, api.js, openfeed_test.py, OPENFEED_SETUP.md (troubleshooting section).

ADMIN CONSOLE SWITCHES FOR OPEN BANKING + PAYMENT CARD SETUP: Admin > Modules Management > Settings & Admin Console now lists, under "Admin Console", Open Banking (Basiq, OpenFeed) as well as Payment Card Setup
  (Square, Stripe). They are separate from the Settings switches clients see. Admin > API Keys hides the Open Banking tab when both providers are off, and the Payment Card Setup tab when both gateways are off.
  Files: config/modules.json (new ids basiq-admin-open-banking, openfeed-admin-open-banking), AdminPage.jsx, OpenBankingSetupPage.jsx, tests.

OPENFEED invalid_scope + CORRECTIONS (from the real OpenFeed dashboard and Quickstart): only "Banking accounts and transactions" (openfeed-au:data:banking:read) is a tick-box; openid and offline_access
  are requested automatically and are NOT boxes. Redirect URIs are NOT registered at OpenFeed (the earlier guide/card were wrong on both points). "Test OpenFeed set-up" now asks for each scope on its own and
  shows a tick/cross per scope plus the exact fix. Files: openfeed_cdr.py, api/openfeed_api.py, OpenFeedPlatformSetup.jsx, openfeed_test.py, OPENFEED_SETUP.md.

OPENFEED banking scope "not allowed" although ticked: the Test button now shows which Client ID it tested as, and when the banking scope is refused it re-tries the same request from other redirect addresses
  (http://localhost:<port> / https) to tell a redirect-address problem from a missing tick or a second app. Files: openfeed_cdr.py, OpenFeedPlatformSetup.jsx, openfeed_test.py.

LOCAL (WINDOWS) RUN FIXES, from the server log:
  1) GET /modules.json -> 500 "'charmap' codec can't decode byte 0x8f": text files were read with the Windows default encoding (cp1252) and modules.json contains emoji. react_api.py now reads/writes UTF-8.
  2) "QueuePool limit of size 2 overflow 3 reached, connection timed out": the auth middleware did its database lookups on the event loop, so a busy pool froze the server until the 60 s timeout.
     middleware.py now runs them in a worker thread; db_app/database.py pool is now 4 + 4 (was 2 + 3), timeout 30 s, tunable with DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT.
  Tests: local_run_safety_test.py (new), tenancy_test.py (own 3-seat plan: Essentials is now 1 user).

OPENFEED grant management + Path to production: the connect request now sends grant_management_action=create (first connect) or replace + grant_id (change shared accounts), as OpenFeed recommends; OPENFEED_GRANT_MANAGEMENT=0 turns it off,
  and the Test button says if OpenFeed objects to it. OPENFEED_SETUP.md: no sandbox exists (one live platform), 10 free credits, 5 active grants until the business is verified, Privacy Act duties (APP 8 cross-border).

CONNECT MY BANK IN A POP-UP WINDOW: OpenFeed sign-in, the bank screens and the "share with AccFino" screen now open in a pop-up window; the Settings page stays where it is. The pop-up ends on a small
  self-closing page (/open-banking/openfeed/done) that tells the main window "connected / declined / error" (postMessage, or BroadcastChannel) and closes itself; the card then refreshes without a reload.
  If the browser blocks pop-ups it falls back to the previous full-page flow. Files: BankFeedCard.jsx, booksApi.js, openfeed_cdr.py, api/openfeed_api.py, middleware.py (public route), tests.

BANK FEED: SEVERAL ACCOUNTS FROM SEVERAL BANKS, DISCONNECT ONE: the card lists every account OpenFeed shares ("3 accounts from 2 banks"), each with a "Use" switch (on/off in AccFino immediately, others untouched,
  stays off after refreshes, off accounts are not offered in reconciliation) and "Stop sharing..." (switches it off, then opens OpenFeed so the permission can be withdrawn there). "Change shared accounts" is now
  "Add or remove accounts"; "Disconnect" is "Disconnect all". Bug fixed: cancelling "change accounts" used to flip a live feed to "pending" so reconciliation lost every account.
  Files: openfeed_cdr.py, api/openfeed_api.py (POST /org/current/open-banking/account), BankFeedCard.jsx, booksApi.js, tests.

PLAN-LOCKED MODULES HIDDEN: the menu, tab bars, Home/dashboard tiles already hide domains/modules a plan does not include - but ONLY while Admin > Pricing > "Enforce subscriptions" is ON (it is Off by default, which
  shows everything to every organisation). That switch now explains itself. New: PlanGate (components/subscription/PlanGate.jsx, wired into Layout.jsx) - a locked page opened by typed address / bookmark shows
  "<module> is not part of your plan" (with the upgrade route for the Organisation Admin) instead of the page. lib/modules.js: moduleAtLocation(). Tests: PlanVisibility.test.jsx, DomainPlans.test.jsx.


ONE PRICE LIST - OLD PLANS REMOVED, VISIBILITY BY PLAN:
  Plans: Starter A$25 (1 user, ALL of Books & Accounting - and nothing else), Business A$59 (3 users, + Planning & Intelligence), Professional A$99 (6, + Payroll + Tax), Complete A$179 (15, everything).
  Essentials was renamed Starter. Vault -> Starter, Ultra -> Complete (Accounting Pro -> Business; Payroll/Tax/Lending plans -> Starter + the matching domain add-on).
  One-off migration at the next start (catalogue version 4, accfino_core/subscription/align.py): every organisation is moved to the new plans, every old plan (Starter v1, Growth, Premium, any plan outside the four) and the add-ons
  Books & Accounting now includes (Inventory, Expenses, Fixed assets, Bulk import) are DELETED, organisations with no plan get one from their owner's old licence, the AccFino administrator is on Complete with no end date,
  old licence labels are relabelled, and the old pricing_plans table is rewritten as a mirror of the four plans (kept in step after every edit in Admin > Pricing).
  Plans are ENFORCED by default: the menu, tabs, Home, dashboard and the server all show/allow only the domains and modules in the organisation's plan; a locked page opened by address shows "not part of your plan".
  The plan badge and Upgrade buttons use the organisation plan (never "Vault"/"Ultra"); /upgrade now opens Settings > Subscription (the old Stripe page is no longer used).


PLAN NAMES, ONE USER, YEARLY = ONE MONTH FREE:
  Plans are now Essential A$25, Business A$59, Professional A$99, Ultra A$179 (Starter -> Essential, Complete -> Ultra; plan ids essential / business / professional / ultra).
  Yearly = 11 x monthly: A$275 / A$649 / A$1,089 / A$1,969 (add-ons likewise 11 months). EVERY plan is for 1 user.
  More users = a USER PACK arranged with the AccFino team: an add-on with extra_seats created for ONE organisation (Admin > Pricing > Add-ons, then assign it to the organisation) and charged with the plan.
  The public 1-user / 5-user seat packs are removed. Organisations show "Need more users? Ask about a user pack" (records a request; contact@accfino.com).
  One-off migration (catalogue version 5, accfino_core/subscription/align.py: migrate_catalogue): renames the plan ids everywhere (organisations, payment history, default plan, licences, the old pricing_plans table),
  sets every plan to 1 user, moves yearly prices to 11 months (unless an administrator set their own), and gives every organisation that already has more than 1 user - or that bought seat packs - ONE pack
  ("Extra users (arranged with AccFino)") with the same number of users and the price it already paid (A$0 if it had none), so nobody loses access; the AccFino team then agrees the price.
  Landing page: new names and prices, "1 month free", "Need more users? Talk to the team".


LICENCE MANAGEMENT REPLACED BY "PLANS BY USER" (Admin > Users & Licence): the old table (licence type, payment mode, start/end, notes, per-user module list, "Auto-created") was the OLD per-user
  licence record - nothing reads it any more. The tab now lists every person with their ORGANISATION's plan: plan (changeable by the administrator, only the plan changes), billing, paid-to date, card/auto-renew,
  users used / allowed, add-ons and the business domains the plan shows; the AccFino administrator shows Ultra. Files: api/org_directory_api.py (GET /admin/org-directory/user-plans,
  PUT /admin/org-directory/org/{id}/plan), UserPlansPanel.jsx, LicencePage.jsx, booksApi.js, tests. "Add User" in that tab is gone (users join through sign-up or an Organisation Admin's access codes).


ORGANISATION WEB ADDRESSES (https://<organisation>.<your domain>): the app side already worked; the platform side (TENANT_BASE_DOMAIN + wildcard DNS + wildcard certificate + routing) was never set up.
  New: Admin Console > API Keys > "Web Addresses" > "Check my set-up" tests the four steps with a made-up name and says which is missing and what to do (accfino_core/tenancy/address_check.py,
  GET /admin/org-directory/address-check, TenantAddressCheck.jsx). The warning on the Organisation page now says plainly what happens until it is on, and links the platform owner to the check.
  Setup steps for your hosting (Northflank wildcard certificate "Wildcard via DCV" + wildcard sub-domain): docs/TENANT_URLS_SETUP.md.


PLAN FUNCTIONS - "OPEN BANKING" CHECKBOX PER PLAN: Admin > Pricing > (a plan) Edit > "Functions" box > "Open banking - live bank feeds". Untick it and that plan has no bank feeds: Settings > Open Banking and the
  reconciliation bank-feed input disappear, the OpenFeed routes answer 402, the feed card says "not part of your plan". It is a function, separate from the business domains, so Books & Accounting stays intact.
  All four plans include it by default (one-off migration to catalogue version 6 adds it to every plan; an administrator's later removal is never undone). An add-on can sell it to a plan that lacks it.
  Files: subscription/service.py (FEATURES), align.py, subscription_api.py, openfeed_api.py, react_api.py, useModuleVisibility.jsx, OpenBankingPage.jsx, ReconciliationPage.jsx, BankFeedCard.jsx,
  SubscriptionAdminPanel.jsx, SubscriptionCard.jsx, tests.


RECONCILIATION > OPEN BANKING: OpenFeed accounts showed "OpenFeed - soon", were greyed out and counted as "0 of 0 selected" - a leftover from when OpenFeed could not be pulled. They are now selectable (Basiq and OpenFeed
  counted together) and pulled through the server. Pulled rows from a bank feed carry a MASKED account number (xxxxxx xxxxx1912), which now merges into the statement account whose full number ends in those digits
  (lib/accountMatch.js; at least 4 digits). Files: OpenBankingInput.jsx, ReconciliationPage.jsx, accountMatch.js, ReconBankFeed.test.jsx.


RETURN TO RECONCILIATION AFTER SETTING UP A BANK ACCOUNT: Reconciliation > Open Banking > "Open settings" / "Add or change bank accounts" now opens Settings > Open Banking with a return address
  (?returnTo=/reconciliation?input=openbanking). A banner says where it will return to (with a Back link). When an OpenFeed bank is connected - or Basiq accounts are saved for Reconciliation - the page goes back
  automatically after a moment, and Reconciliation opens on its Open Banking input. A declined/failed connection stays on Settings; only addresses inside AccFino are accepted as a return address.
  Files: lib/returnTo.js, OpenBankingInput.jsx, OpenBankingPage.jsx, BankFeedCard.jsx, ReconciliationPage.jsx, ReturnToRecon.test.jsx.
