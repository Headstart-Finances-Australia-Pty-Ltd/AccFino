# Subscriptions per organisation

Each **organisation** has a subscription: a **plan** (modules + user seats) plus optional **add-ons**. Everyone in the organisation gets the same modules;
their **role** (owner, admin, accountant, bookkeeper, payroll, readonly) still decides what each person may do inside them.

## Safe by default
**Enforcement is OFF.** Until an administrator turns it on, every organisation can use every module exactly as before. Organisations with no plan assigned are never locked.

## Where things are
| Who | Where | What |
|---|---|---|
| Platform admin | Admin > Modules Management > **Subscriptions** | Turn enforcement on/off, choose the default plan for new organisations, edit plans and add-ons (price, users, modules), assign a plan / add-ons / status / paid-until date to each organisation. Applies immediately. |
| Organisation owner | Settings > Business Setup > Organisation > **Subscription** | See plan, status, users used, included and locked modules; **request** a plan change or add-on (recorded in the audit log). |
| Any member | Menus and tabs | Locked modules are hidden. |

## Starting plans (placeholder prices - edit them)
| Plan | Users | Modules |
|---|---|---|
| Starter ($29/mo) | 3 | Dashboard, General ledger, Banking & reconciliation, Sales, Purchases, Financial reports |
| Growth ($79/mo) | 10 | Starter + Expenses, Inventory, Fixed assets |
| Premium ($149/mo) | Unlimited | Everything (including Bulk data import and future modules) |

Add-ons: Bulk data import, Expense claims, Inventory, Fixed assets (each a module), and "5 extra users" (adds seats).

## Rules
* **Server-enforced:** the Sales, Purchases, Contacts, Ledger, Reports, Banking, Expenses, Inventory, Fixed assets and Bulk-import APIs refuse calls for a module the organisation does not have (HTTP 402 with a clear message). Hiding the menu is only a convenience.
* **Seats:** adding a member beyond the plan's users (plan + seat packs) is refused. Existing members are never removed.
* **Expired / cancelled-and-ended / trial-ended:** the organisation becomes **read-only** (view and export, no posting or editing). A 7-day grace period applies to lapsed payments. Data is never deleted.
* **Platform administrators** are never blocked (so support can always help).
* **Bulk data import** now needs both the platform switch and the organisation's plan / add-on.
* **Upgrades apply at once:** the admin saves, every open session re-reads the subscription, and the new module appears without signing out.

## Rolling it out
1. Install the update and restart (new tables are created automatically).
2. Admin > Modules Management > Subscriptions: review plans and prices; assign each organisation a plan (or leave unassigned to keep everything).
3. Tick **Enforce subscriptions**.

## Not included yet
* **Stripe / automatic payment:** the table has columns reserved for Stripe IDs, but upgrades are applied by the administrator for now (owners press "Request").
* **Other modules** (payroll, tax, investments, ...): only the Books & Accounting modules above are gated. The others have user-level (not organisation-level) APIs and need a separate step.
* Locked modules are hidden rather than shown greyed-out; the Subscription card lists them with their add-on price.

## Tests
`cd backend && PYTHONPATH=. python -m pytest ../../AccFino_Testing/tests/subscription_test.py -q` (10 tests) and `cd frontend && npx vitest run`.
