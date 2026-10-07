# Taxation & Compliance

Phase 3 of AccFino. A tax and compliance workspace built on the ledger, payroll and fixed-assets data AccFino already holds. It **prepares, checks, explains and records**. It does **not** lodge anything with the ATO (see [03 – Controls and limits](03-controls-and-limits.md)).

| Area | What it does | Screen (tab) |
|---|---|---|
| Compliance dashboard | Overdue and due-soon items, document status, data-health checks, recent activity | Dashboard |
| Tax returns | Income tax return for individual, sole trader, company, partnership, trust, SMSF; starts from ledger profit | Tax Returns |
| Income tax workings | Book-to-tax adjustments; small-business depreciation and instant asset write-off review | Income Tax Workings |
| GST / BAS / IAS | Activity statements from ledger GST and payroll PAYG, with reconciliation checks, label overrides, review workflow | GST/BAS/IAS |
| CGT | Event register, import from Investments, capital-loss register, net capital gain feeding the return | CGT |
| FBT and Division 7A | Benefit valuation, FBT return, reportable fringe benefits; loan register, minimum repayments, shortfall flags | FBT & Div 7A |
| Tax planning | Year-end estimate (labelled assumption), what-if levers, saved scenarios, year-end prompts | Tax Planning |
| Compliance calendar | Generated due dates, status, registrations, state payroll tax threshold monitor | Calendar |
| Workpapers and evidence | Documented working, reviewer sign-off, hashed evidence files, links to Documents and ledger | Workpapers |
| Reports | Reconciliation, Excel summary pack, CSV exports | Reports |
| Sign-off & lodgement | Taxpayer declaration or registered tax / BAS agent sign-off, an organisation policy requiring agent sign-off, agent hand-off pack, and a gateway slot for an accredited SBR/DSP adapter (AccFino itself does not lodge) | Document screens, Lodgement Readiness |
| Rates and settings | Tax profile, statutory rates with provenance, audited overrides | Rates & Settings |
| Audit trail | Hash-chained history of every tax action, integrity check | Audit Trail |

Documents: [01 Architecture and data](01-architecture-and-data.md) · [02 Statutory rules and their sources](02-statutory-rules-and-sources.md) · [03 Controls and limits](03-controls-and-limits.md) · [04 User guide](04-user-guide.md) · [05 Running, testing, API](05-running-testing-api.md) · [06 Lodgement and agent sign-off](06-lodgement-and-agent-signoff.md)

## Status in one paragraph
The engines, services, API and screens are implemented and tested (backend 115+ taxation tests on SQLite; frontend 37 tests; 95 real-browser checks against the real backend on PostgreSQL 16 (see AccFino_Testing/e2e/tax)). **Some statutory values are not yet confirmed against ATO pages** (company rates and the small business offset are confirmed by secondary sources only; several FBT items, TPAR and return dates and the BAS label meanings are unverified) and two are deliberately empty (the Medicare low-income thresholds, not yet published): see document 02. The CGT reform and the standard deduction are enacted; 2027-28 is not yet supported and the Rates & Settings screen, which shows the verification level of every value. A registered tax agent must review the rules each 1 July and after each Budget, and must review any return before it is lodged.
