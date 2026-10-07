# 03 – Controls and limits

## What AccFino does not do
- **It does not submit to the ATO by itself.** Statuses `lodged` and `paid` are records made by a person with the ATO receipt reference, and only after a declaration (taxpayer or registered agent). Direct lodgement needs an ATO-accredited Digital Service Provider; AccFino has a gateway slot that stays unavailable until an accredited adapter is configured. See [06](06-lodgement-and-agent-signoff.md). The Lodgement module is marked Preview; a test prevents marketing text claiming otherwise.
- It never stores a Tax File Number; entering one in a registration is refused.
- It is not tax advice. Items it cannot assess are returned as `review` findings and repeated on every document.

## Not assessed (tax agent required)
Medicare levy low-income, senior and family rules and surcharge; company loss tests (continuity of ownership, same-business); trust distributions, section 100A and trustee beneficiary reporting; partnership interests; SMSF exempt pension income; franking account; FBT operating-cost method, housing, living-away-from-home, NFP rebates, employee-contribution timing; Division 7A distributable-surplus cap and sub-trust arrangements; small business CGT concession basic-conditions tests; foreign-resident CGT apportionment; the enacted post-1 July 2027 CGT regime (indexation and 30% minimum tax) and dynamic PAYG instalments; effective-life depreciation (non-small-business); payroll tax liability beyond a flat-rate NSW indication (a threshold monitor and return due dates only: see document 02) and land tax (registrations and custom due dates only).

## Roles
| Role | Can |
|---|---|
| Organisation Admin / platform admin | Everything |
| Accountant (and legacy admin) | View, prepare, approve, record lodgement, configure, view audit trail |
| Bookkeeper | View, prepare, attach evidence. Cannot approve, record lodgement or configure |
| Read-only | View |
| Payroll, Employee | No access |

Separation of duties: the approver must differ from the preparer, for BAS, returns, FBT returns and workpaper review. A one-person business can enable self-approval in the tax profile; each use is audited as `*.approved.self`.

## Audit trail
Every action writes an event holding who, when, what and before/after values. Events are chained by SHA-256 so editing or deleting one breaks the chain; **Verify integrity** reports the first broken event. The chain proves tampering within the database; it does not protect against someone with database access rewriting the whole chain, so back up and restrict access accordingly.

## Tenancy and files
Every query is scoped by `org_id`; another organisation's record answers 404. Evidence files: PDF, PNG, JPEG, CSV, text, Excel, Word up to 5 MB, stored with a SHA-256 checked on every download, served as an attachment with `nosniff`. CSV exports neutralise cells beginning `= + - @`.
