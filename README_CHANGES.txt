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
