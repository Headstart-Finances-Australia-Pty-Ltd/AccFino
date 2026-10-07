# Organisation Admin, mandatory contact details and admin-only settings

## The rules
1. **One Organisation Admin per organisation** (the Account Owner). Whoever creates an organisation becomes it automatically.
2. **Every user account needs a valid email address and phone number**: Organisation Admin, invited users, anyone joining by access code, and anyone created any other way.
3. **Only the Organisation Admin** manages organisation settings, users, invitations / access codes, licence / subscription, access policy / security and organisation notifications.
4. **Organisation-level communication goes to the Organisation Admin**; personal account communication goes to the individual.

## How each rule is enforced
| Rule | Frontend | API | Database |
|---|---|---|---|
| One admin | Admin shown as a badge; no role picker, Remove or code for it; "Transfer admin" | owner/admin roles refused by invites, add-member and role change (422); admin cannot be removed/suspended/re-roled (409) | `organisations.admin_user_id` + unique index `uq_org_one_owner` (one `owner` row per organisation) |
| Email + phone | Inline messages on signup and My Account | Shared validator `security/contact.py` on `/signup/*`, `/auth/register`, `/auth/me/profile` (422 with the messages below) | `User` model event guard + PostgreSQL trigger `trg_users_contact_guard` (valid email, E.164 phone) |
| Admin-only | Settings hidden; My Account for everyone | `ctx.require_org_admin()` on every organisation-level endpoint (403 otherwise) | - |
| Isolation | - | `current_org` resolves the caller's membership in the *requested* organisation; none = 403 | - |

Messages: `Email address is required.` / `Please enter a valid email address.` / `Phone number is required.` / `Please enter a valid phone number.`

## Phone numbers
Australian (`0412 345 678`, `(02) 9999 9999`, `+61 412 345 678`) and international (`+<country><number>`, 8-15 digits) numbers are accepted and stored as E.164 (`+61412345678`). Australian and North American numbers are checked against their numbering plans; others by E.164 length.

## Roles
| Role | Who | Organisation administration | Day-to-day access |
|---|---|---|---|
| `owner` = **Organisation Admin** | exactly one | everything | everything |
| `accountant` | Organisation User | none | post, read, audit, accounting set-up (chart of accounts, tax codes, tracking, bank accounts, document settings) |
| `bookkeeper` | Organisation User | none | read, post |
| `payroll`, `readonly` | Organisation User | none | read |
| `admin` (legacy) | old rows only; cannot be assigned | none (treated as accountant) | as accountant |

Accounting set-up uses the `settings` permission and is **not** organisation administration. To make it admin-only too, remove `settings` from `accountant` / `admin` in `ROLE_PERMS` (`security/context.py`).
AccFino platform administrators (the `admin` *user* role) can still enter any organisation for support.

## Organisation-admin endpoints (all Organisation Admin only)
`PATCH /org/current`, `POST /org/current/lock-date`, `GET/POST /org/current/members`, `PATCH/DELETE /org/current/members/{id}`, `POST /org/current/transfer-admin`, `GET /org/current/admin/overview`,
`/org/current/invites*`, `/org/current/tenant`, `POST /org/current/subscription/request`, `/org/current/access-policy`, `/org/current/identity/*`.
Any member: `GET /org/current` (name, own role, admin's *name*), `GET /org/current/directory` (names and roles only), `PATCH /auth/me/profile` (own details; changing an existing email/phone needs the current password).

## Transfer admin
`POST /org/current/transfer-admin {new_admin_user_id, password}`: the current admin re-enters their password; the target must be an active member with a complete profile. The former admin becomes an Accountant. Both are told by email.

## Primary contact
The admin's email and phone *are* the organisation's contact details (`accfino/core/identity/org_admin.py: org_contact`). Blank organisation contact fields at signup default to them; changing the admin's email updates the organisation contact email if it was the same address, and warns the old address.

## Notifications (`accfino/core/notifications.py`)
To the Organisation Admin: organisation created, new user joined, settings changed, member added / role changed / removed / suspended / restored / 2-step reset, access codes generated, licence nearly full / full / someone refused for lack of a seat, subscription changed or expired, access-code guessing lockout, access policy changed, admin contact details changed. Security alerts also text the admin's phone when `ACCFINO_ORG_SMS_ALERTS=1`.
To the individual: their own role / access change, their email change (old and new address), admin transfer.
Sent on a background pool (`ACCFINO_NOTIFY_SYNC=1` for inline); failures are logged and never break the action; bursts of the same alert are de-duplicated.

## Existing data (applied automatically at startup, idempotent)
* Organisations with several owners: the creator (else earliest) stays admin; the others become accountants (audited as `org.admin_normalised`). Organisations with no owner: an `admin`-role member is promoted. `admin_user_id` is back-filled.
* Users with no valid email/phone are **not** locked out of the database. At next sign-in the app asks them to complete their profile; until then the API allows only profile, security and sign-out (`PROFILE_GATE_ENFORCED=0` switches only that gate off).
* The platform administrator is created without a phone unless `ADMIN_PHONE` is set.

## Settings that non-admins cannot see or use
The whole **Settings** area (Organisation, Business Account, Chart of Accounts, Business Rules, Knowledge Base, IAM Setup, Open Banking, Integrations, Payment Setup) is shown only to the Organisation Admin; everyone else has **My Account**. Server-side, in the auth middleware (`ORG_ADMIN_RULES`):
* Payment Setup (`/square/*`, `/stripe/*`, `/bank-account/*`) and Open Banking configuration (`/openfeed/*`): every method refused to non-admins.
* Knowledge Base (`/kb*`) and Business Rules (`/rdr/rules*`): all **changes** refused. *Reading* them stays open, because bank reconciliation uses them for every user.
* The newer organisation endpoints (details, members, invites, licence, access policy, identity) use `require_org_admin()` as listed above.
The check uses the organisation named by the web address / `X-Org-Id` / the sign-in token, so being admin of another organisation does not help.
**Known limit:** Square / Stripe / bank-account / Open Banking settings are saved in ONE file shared by the whole installation (older design), not per organisation. They are now admin-only, but the values are still shared by every organisation; making them per-organisation is a separate piece of work.

## Organisation web address (e.g. https://kutumb.syd.accfino.com)
Every organisation already has a web name (`Kutumb` -> `kutumb`; created automatically, also for existing organisations). It becomes a full address only when the installation is told its base domain:
1. Server setting: `TENANT_BASE_DOMAIN=syd.accfino.com` (and `TENANT_SCHEME=https`), then restart.
2. DNS: a wildcard record `*.syd.accfino.com` pointing at the app. TLS: a wildcard certificate for `*.syd.accfino.com`.
3. The proxy must pass the `Host` header through and overwrite `X-Forwarded-Host`.
Until step 1 is done no address can be shown (the application cannot invent a domain it does not control). Once it is, the address is shown to **every member** in the sidebar, under My Account, on the sign-up confirmation, and to the admin under Settings > Organisation; people sign in at that address and can only enter their own organisation. For local testing use `TENANT_BASE_DOMAIN=localhost:5173` and `TENANT_SCHEME=http`.

## Not included
Email verification (the app has none today: email is format-validated only), phone verification, MX checks.

## Tests
`cd backend && PYTHONPATH=. ACCFINO_NOTIFY_SYNC=1 python -m pytest ../../AccFino_Testing/tests/org_admin_test.py ../../AccFino_Testing/tests/tenancy_test.py -q` · `cd frontend && npx vitest run`
