# Practice & Client Services  (`accfino.modules.practice`)

Six capabilities for accounting practices, built as one module (one set of 46 `pc_*` tables, one access model): **Practice Management**, **Clients & Entities**, **Workpapers & Documents**, **Client Portal**, **Engagements & Workflows**, **Billing**.

| | |
|---|---|
| Backend | `backend/accfino/modules/practice/` (`engine/` pure rules, `models/`, `services/`, `api/`) |
| Frontend | `frontend/src/modules/practice/` (staff tabs in the Practice hub; client portal at `/portal`, `/portal/accept`) |
| Tests | `python AccFino_Testing/run_tests.py practice` -> `AccFino_Testing/tests/modules/practice/`; `frontend/src/modules/practice/__tests__/` |
| Owns tables | all `pc_*` tables (`models/practice.py`) |
| Data files | `ACCFINO_DATA_ROOT/modules/practice/documents/` (private; never served by URL) |
| Uses (public facades) | `accounting.public` (`create_sales_invoice`, `sales_document`, `void_sales_invoice`, `credit_sales_invoice`) - invoices are ordinary Accounts Receivable documents, there is no second ledger |
| Uses (shared services) | `contracts`, `db`, `paths`, core `audit`, `secrets` (sealed identifiers), `messaging` (email) |
| Public API for other modules | none |

## Rules the code enforces
- **Isolation**: every staff call needs an active `PcMember` of the practice for the request's organisation, a capability for the role, and the client in scope (admin/partner all; others assigned or via team; billing role all clients for billing only). Out-of-scope and other-practice ids both answer 404.
- **Portal**: portal users have no organisation membership; access is re-checked on every call (access row, client active, contact link, plan, entity restriction). Invitations are hashed, single-use, expiring; unknown/used/revoked/expired are indistinguishable.
- **Documents**: private storage, content sniffing, safe names, versioning, retention and legal hold; downloads are single-use short-lived tickets redeemed with `POST` (never in a URL).
- **Deadlines**: no statutory date is built in. A statutory rule needs a source and a last-verified date; created deadlines are unverified until verified; overrides need a reason and are audited.
- **Billing**: approved time is snapshotted (rate and amount); the approver cannot approve their own time; the database prevents billing the same time twice; issuing posts through the accounting facade and fails if the ledger total differs from the practice total.
- **Not provided**: ATO lodgement, e-signature, identity verification, antivirus scanning (`scan_status = not_scanned`), a scheduler (recurrence and reminders run via `POST /practice/recurrences/run`).

## HTTP API (URL prefixes, route count)
| Prefix | Routes |
|---|---|
| `/portal/clients`, `/portal/invitations` (client side) | 18 |
| `/practice/me`, `workspace`, `profile`, `settings`, `members`, `teams`, `audit`, `dashboard` | 18 |
| `/practice/clients`, `entities`, `relations`, `contact-links` | 28 |
| `/practice/documents`, `documents-download`, `workpapers`, `workpaper-templates` | 20 |
| `/practice/engagements`, `engagement-templates`, `deadline-rules`, `deadlines`, `jobs`, `tasks`, `checklist`, `review-points`, `my-work`, `recurrences` | 25 |
| `/practice/portal` (staff side) | 15 |
| `/practice/billing` | 19 |
