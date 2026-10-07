# 02 – Statutory rules and their sources

Rates, thresholds and dates live in `deploy/data-seed/reference/tax_statutory_rules.json` (copied to `ACCFINO_DATA_ROOT/reference/` on first use). The engines contain none. Each value group carries `{verification, source, checked_on}`. **Research was done on 5 October 2026.** Every group below is only as good as its verification level; treat anything not marked "ATO page read" as needing confirmation.

| Verification | Meaning |
|---|---|
| `ato_primary` | Read on an ato.gov.au page |
| `secondary_consistent` | Several independent professional sources agree; the ATO page itself was not read |
| `knowledge_unverified` | From the maintainers' domain knowledge; **not confirmed** |
| `not_loaded` | Deliberately empty; the engine warns instead of guessing |

## 2026-27 rule set: status of each group
Verification is recorded **per value**. Research dates: 5 October 2026. "ATO page read" means the ATO page (or the Parliament of Australia bill page for legislation) was read.

| Group | Value(s) | Verification | Note |
|---|---|---|---|
| Instant asset write-off | $20,000, permanent from 1 July 2026, pool 15% / 30% | ATO page read | Entities under $10m aggregated turnover |
| Standard deduction | $1,000 for work-related expenses from the 2026-27 return | ATO page read | **Law**: Treasury Laws Amendment (Tax Reform No. 1) Act 2026 (Act No. 49 of 2026), assent 26 June 2026; ATO Law Companion Ruling LCR 2026/D5 was still a draft |
| GST registration threshold | $75,000; $150,000 for non-profits | ATO page read | |
| GST rate 10% | | secondary | Every source agrees; the ATO page was not among those read |
| FBT rate / gross-up | 47%; Type 1 2.0802, Type 2 1.8868 | ATO page read | |
| FBT benchmark interest rate | 8.27% for the year ending 31 March 2027 | ATO page read | Removing it makes loan valuation refuse |
| FBT statutory fraction 20%, $300 minor benefit, $2,000 reportable threshold, return due 21 May / 25 June (agent) | | secondary | Stated in the ATO FBT guide and consistently by many sources; the ATO rates page was not reopened. The $5,000 figure seen earlier was not an RFBA threshold |
| BAS due dates | Quarterly 28 Oct / 28 Feb / 28 Apr / 28 Jul; monthly 21st; annual GST 31 Oct | ATO page read | |
| Registered-agent BAS dates | Q1 25 Nov 2026; Q2 has no concession | ATO page read | Q3 and Q4 2026-27 agent dates not yet published; 2025-26 pattern used, **unconfirmed** |
| PAYG instalment GDP adjustment | 5% for 2026-27 (4% in 2025-26) | ATO page read | Held for reference only: AccFino uses the amount or rate the ATO notified, which already includes it. "Dynamic PAYG instalments" from 1 July 2027 are not modelled |
| Medicare levy surcharge | 2026-27 single $105,000 / $123,000 / $164,000; family $210,000; 1% / 1.25% / 1.5% | ATO page read | Review prompt only |
| Medicare levy low-income thresholds | $28,011 / $35,013 (single) | secondary | **Provisional**: the 2025-26 figures carried forward because the ATO has not published 2026-27 (its page still cites 2025-26). Labelled an assumption on every return that uses them; family, seniors and dependant thresholds are not assessed |
| Medicare levy rate | 2% | ATO page read | ATO 'What is the Medicare levy?' (updated 30 April 2026). The 10-cent phase-in rate for the low-income reduction is **unverified** |
| Company tax rates | 25% base rate entity / 30%; $50m; 80% passive-income limit | secondary | Many independent sources, several quoting the ATO; ATO page not opened. Passive income **includes net capital gains**, interest, rent, royalties, most dividends and franking credits |
| Small business income tax offset | 16%, cap $1,000, turnover under $5m | secondary | ATO myTax 2026 page confirms cap and $5m (2025-26 return year); 2026-27 page not read |
| Resident tax brackets (15% second bracket), LITO | | secondary | |
| Division 7A benchmark | 8.77% | secondary | |
| CGT discount parameters and 12-month rule | | secondary / unverified | |
| CGT reform (see below) | effective 1 July 2027 | ATO page read | **Enacted** |
| TPAR due date | 28 August | ATO page read | |
| Income tax return due dates | 31 October (sole traders, partnerships, trusts; self-lodgers); 28 February for most small companies via a tax agent | secondary | business.gov.au (Australian Government). Agent dates for other entity types vary by client category and are entered on the obligation, never invented |
| State payroll tax | NSW $1.2m / 5.45% flat; VIC $1.0m / 4.85%; QLD $1.3m / 4.75%; WA $1.0m / 5.5%; **SA $1.5m, variable rate to 4.95% at $1.7m, $600k maximum deduction** (monthly return due 7 days after month end; NSW December return 14 January) | secondary | Many sources agree (SA's cite RevenueSA's page, modified 8 July 2026); revenue office pages not opened. **TAS, ACT and NT are not loaded**: sources still disagree on their thresholds. Used by a threshold MONITOR only (see below) |
| BAS label meanings | W1-W5, 4, T1, T2, T7, T11, 5A, F1, 6A, 8A, 8B, 9 | ATO page read | ATO activity statement instructions. 8A = 1A + 4 + 5A + 6A; 8B from credits; 9 = difference. **Instalments are entered with cents ignored** (ATO example: 341.70 -> 341) and totals are worked from whole-dollar entries, as on the form. Not modelled: 5B/6B, 7, T3-T4, T8-T9 (varied instalments), WET, LCT, fuel tax credits |

## State payroll tax: a monitor, not a calculator
AccFino compares wages from Payroll (gross plus employer super, scaled to 12 months: an assumption) with the state's threshold and reports **below / approaching (80%) / at or above**, with an action if no payroll tax registration is recorded. For a registered employer it generates the monthly return due dates (rolled for weekends and holidays; NSW's published December exception is data). An indicative amount is shown **only for NSW** (a flat rate above the threshold). It does not calculate liability for VIC, QLD or WA because their thresholds taper or are adjusted at higher wage levels and regional rates and surcharges apply, nor for any state because liability depends on grouping, interstate wages, contractor deeming, fringe benefits and allowances that AccFino does not hold. Land tax is not covered.

## CGT reform: enacted; provisional handling for 2027-28
The Treasury Laws Amendment (Tax Reform No. 1) Act 2026 (Act No. 49 of 2026; finally passed 25 June 2026, assent 26 June 2026) replaces the 50% discount for individuals, trusts and partnerships with **cost base indexation and a 30% minimum tax on gains accruing from 1 July 2027**; gains accrued to 30 June 2027 keep the 50% discount (the 1 July 2027 market value becomes the starting cost base).
- **No 2026-27 disposal is affected**: every 2026-27 CGT event is before 1 July 2027, so the calculation here is correct for the income year this release covers.
- **2027-28 has a PROVISIONAL rule set** so BAS and planning keep working after 1 July 2027. The only real change is the legislated 14% second tax bracket (secondary sources); every other value is carried forward from 2026-27, graded `knowledge_unverified`, and the Rates screen, every BAS/return/FBT and the dashboard say so. The FBT benchmark rate, Division 7A benchmark and PAYG uplift for 2027-28 are left empty rather than guessed. Years beyond 2027-28 are still refused.
- **CGT events on or after 1 July 2027 block the return** (an error finding) until the user or their tax agent enters the net capital gain computed under the new regime in the return inputs; the entered figure is then flagged for tax agent review. AccFino does not compute indexation or the 30% minimum tax.
- The new regime will be calculated once the ATO publishes the indexation parameters and the deemed-cost-base rules.

## Updating each year
1. Copy the 2026-27 object, change `id`, `effective_from`, `effective_to`, and every value; set `checked_on` and re-grade `verification` honestly.
2. Existing installs keep the copy already in their data root: **replace that file** (the engine reloads on file change, no restart).
3. A tax agent signs off the file. Rates & Settings shows the verification summary and the dashboard warns while any value is unverified.
4. An organisation may override a single value (needs a reason, audited, shown on screen) when it must act before a release.
