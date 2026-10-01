# Organisation-first signup, access codes, licence seats and tenant addresses

> **Organisation Admin, mandatory contact details and admin-only settings are described in [ORG_ADMIN.md](ORG_ADMIN.md); where the two differ, ORG_ADMIN.md is current** (access codes now only create Organisation *Users*; there is exactly one Organisation Admin; email and phone are required).

**Rule: no organisation + no valid access code = no signup.** Selecting an organisation proves nothing; only a code issued by that organisation's own administrator does.

## The signup flow (Sign Up on the login page)
| Step | New organisation | Join an existing organisation |
|---|---|---|
| 1 | **Create a New Organisation** | **Join an Existing Organisation** |
| 2 | Organisation details: name, ABN / ACN / other ID (at least one, checksum-validated), type, industry, address, city, state, postcode, phone, contact email, optional web address. Nothing is saved yet; the proposed address is shown. | Type the organisation name (3+ letters), pick it from the list (name and town only), enter the **Organisation Access Code**, press **Verify & Continue**. |
| 3 | Your account: first name, last name, email, **phone**, password (+ confirm). | Only after the code verifies: the same account form ("Joining ABC as Bookkeeper"). |
| 4 | The organisation, its ledger, its licence plan and you as **Organisation Admin** (the organisation's single `owner`) are created in one step. | The account is created in that organisation with the code's role; the code is used up. |
| 5 | You are sent to `https://<name>.<domain>/login`. | Same. |

Creating the organisation and its first user happens in one atomic step, so a failed signup never leaves an orphan organisation behind.

## Access codes
* Format `ABC-7F4K-92LM`: a cosmetic organisation prefix + 8 random characters (40 bits, no look-alike characters), from a cryptographic random source.
* **Stored only as an HMAC-SHA256 hash.** The full code is shown once, to the administrator who generated it. After that only a hint (`ABC-7F4K-....`) is visible.
* Bound to one organisation and one role; single use unless the administrator sets more uses (up to 50); expires (1-90 days, default 7); can be revoked; every create / revoke / use / failure is audited.
* A code for organisation A never works for organisation B.
* Validated on the server, twice: when you press Verify, and again when the account is created (so a code revoked in between, or a seat taken in between, is caught).
* All failures (wrong, expired, revoked, used, wrong organisation, unknown organisation) give the **same message**, so the screen reveals nothing. The audit log records the real reason.

## Licence seats
Licensed users = the organisation's plan users + seat-pack add-ons (see SUBSCRIPTIONS.md). **Active members + codes still waiting to be used can never exceed it.**
* Generating codes needs free slots (each unused code reserves one, a 3-use code reserves 3).
* A valid code is still refused when no seat is free: *"This organisation has reached its licensed user limit. Please contact your organisation administrator."*
* Direct "add member by email" respects the same limit.
* The Organisation Admin sees licensed / active / pending / available and counts of unused, used, expired and revoked codes under **Settings > Business Setup > Organisation > Users and access codes**.
* An organisation with no plan assigned has unlimited users. New organisations start on the platform's default plan (Admin > Modules Management > Subscriptions).

## Tenant addresses
Every organisation has a unique, URL-safe name (derived from its name, or chosen at signup; reserved words such as `www`, `api`, `admin` are refused): `https://abc-accounting.yourdomain.com`.
Existing organisations are given one automatically at startup.

**Enforced on the server, on every authenticated request** (auth middleware and `current_org`):
* On an organisation's address only its active members can use the API; everyone else gets 403 (suspended members too). Unknown address: 404.
* The organisation comes from the **address**. Sending a different `X-Org-Id` header or `?org_id=` is refused (403), so changing an id never moves you into another tenant.
* Sign-in on an organisation's address is refused for people who do not belong to it.
* Platform administrators may enter any tenant (for support). `/auth/me` and sign-out stay reachable.
* Every refusal is written to the audit log (`tenant.access_denied`).
* On the main address (no tenant) the existing rule still applies: you only reach organisations you are a member of.
* All accounting data is partitioned by organisation on every query (existing design); users, customers, suppliers, journals, ledger, bank, documents, reports and settings are all organisation-scoped.

## Protection of the signup itself
| Risk | Control |
|---|---|
| Guessing codes | 5 failed attempts per IP + organisation / 15 min, 25 per organisation / hour, 30 per IP / hour, then HTTP 429 (even the correct code is refused while locked). Stored in the database, so it holds across workers. |
| Finding organisations | Search needs 3+ letters, returns at most 5 results with **only name and town**, supports hiding an organisation (exact web address still works), and is rate limited (60 / 10 min per IP). |
| Mass organisation creation | 5 per IP per hour. |
| Forged or reused signup tokens | The signup token is signed, expires in 15 minutes, and is bound to one code; the code is re-checked on use. |
| Old open registration | `/auth/register` now refuses everyone except the very first user of an empty system. Emergency rollback: `ACCFINO_OPEN_SIGNUP=1`. |

## Audit events
`signup.organisation_created`, `invite.created`, `invite.revoked`, `signup.invite_redeemed`, `signup.code_failed` (with reason), `signup.code_lockout`, `signup.rejected_seat_limit`, `tenant.access_denied`, `org.profile_updated`, `auth.registered`.

## API
| Endpoint | Who |
|---|---|
| `GET /tenant/current` | public: which organisation is this address (name only) |
| `POST /signup/organisation/validate`, `POST /signup/organisation` | public |
| `GET /signup/organisations/search?q=`, `GET /signup/organisations/lookup?slug=` | public, rate limited |
| `POST /signup/verify-code`, `POST /signup/join` | public, rate limited |
| `GET/POST /org/current/invites`, `DELETE /org/current/invites/{id}` | Organisation Admin only |
| `GET/PATCH /org/current/tenant` | Organisation Admin only |

## Switching it on
1. Install the update and restart (new tables are created automatically; existing organisations get addresses).
2. Optional, for organisation addresses: set `TENANT_BASE_DOMAIN=yourdomain.com` (and `TENANT_SCHEME`), add a wildcard DNS record `*.yourdomain.com` and a wildcard TLS certificate pointing at the app, and make the proxy pass the `Host` header and overwrite `X-Forwarded-Host`. Without this, everything works on one address and no organisation URL is shown.
3. For local testing use something like `TENANT_BASE_DOMAIN=localhost:5173` and `TENANT_SCHEME=http` (browsers resolve `abc.localhost`).

## Known limits
* **Isolation is logical** (one database, every query scoped by organisation and enforced server-side), not a separate database per tenant.
* Older per-user modules (payroll, tax, investments...) keep their existing per-user ownership rules; they are not partitioned by organisation.
* After signup you sign in once more on the organisation's own address (each address keeps its own sign-in).
* The Organisation switcher still switches within one address; it does not yet jump between organisation addresses.
* An existing AccFino user cannot redeem a code to join a second organisation (an administrator can add them by email).
* The old plan picker and Stripe checkout at registration are gone: a new organisation starts on the platform's default plan; the platform administrator changes it.
* No email verification of new accounts yet.
* Tested with Host headers and the real auth middleware; not with real wildcard DNS / TLS.

## Tests
`cd backend && PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/tenancy_test.py -q` and `cd frontend && npx vitest run`.
