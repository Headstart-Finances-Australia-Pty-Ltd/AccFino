# 04 – User guide

## First-time setup (Accountant or Admin)
1. **Rates & Settings > Tax profile.** Entity type, ABN, GST registration and basis, BAS frequency, PAYG withholding and instalments (amount or rate exactly as the ATO notified), FBT, TPAR, aggregated turnover, tax agent, extra state public holidays.
2. **Rates & Settings > Statutory rates.** Read the verification column. Enter any value shown "not loaded" that you need (for example the FBT benchmark loan rate), with its source as the reason.
3. **Calendar > Generate due dates** for the income year; **Registrations** to record what you are registered for.
4. Check **Dashboard > Data health** and fix errors.

## Preparing a BAS or IAS
GST/BAS/IAS > **New BAS / IAS** > pick the period > **Calculate**. Read every label's basis and source; read the findings. A **GST account that does not agree to 1A − 1B** (usually a manual journal without a tax code) or **PAYG that disagrees with the pay runs** blocks preparation: fix the books. Override a label only with a reason, then **Create workpaper**. **Mark prepared**; a second person **Approves**. Lodge outside AccFino, then **Record lodgement** with the receipt reference, later **Record payment** (and post the bank payment in Accounting).

## Preparing an income tax return
Tax Returns > **Start return**. Add **adjustments** first (Income Tax Workings), run the depreciation review and **Generate adjustments**, enter **CGT events**, then enter the return's own inputs and **Calculate**. Read the working top to bottom: the first line is the ledger profit. Adjustments marked "requires review" must be reviewed by an approver before approval. After lodgement record the **notice of assessment**; if it differs from the computed amount, investigate. To correct a lodged return use **Amend**.

## CGT
Add events (property, business assets) or bring disposals in from Investments: on **Investments > Shares / ETFs > CGT Disposals** press **Send to Tax (CGT)** (a preview comes first and repeat sends are safe), or paste the Disposals sheet as CSV under **CGT > Import**. Crypto disposals are not wired to this button yet: paste them as CSV with the same columns. Enter capital losses brought forward; after each return update the register with the carried-forward amount shown.

## FBT and Division 7A
Pick the FBT year (1 April – 31 March). Add benefits, calculate and prepare the return. Record Division 7A loans with a written agreement date; record repayments and interest; read the schedule's shortfall flags before 30 June.

## Sign-off and lodgement
Once a document is **approved**, the **Sign-off & lodgement** panel appears on it. Sign as the taxpayer / authorised person, or have your registered tax or BAS agent sign off with their 8-digit registration number (they need an Accountant-role login). If your organisation's policy (Rates & Settings > Lodgement policy) requires an agent, a taxpayer declaration alone will not unlock lodgement. Then choose the route: lodge elsewhere and **Record lodgement** with the ATO receipt, or **Prepare pack** for your agent to lodge, or (only if your operator has configured an accredited gateway) **Lodge with the ATO**. If you change anything after signing, the sign-off no longer counts and the document has to be approved and signed again.

## State payroll tax
Calendar > **State payroll tax (monitor)** shows whether Payroll wages are heading towards your state's threshold. Set your state in the tax profile. If you are registered, add a **payroll tax** registration so the monthly return dates appear in the calendar. It never replaces the revenue office's assessment; SA, TAS, ACT and NT thresholds must be entered from the revenue office (Rates & Settings).

## Planning
Tax Planning > leave projected profit blank to project year-to-date (an assumption, labelled) or enter your own; add levers; save scenarios to compare. Year-end considerations are prompts for your tax agent, not recommendations.

## Demonstration data
For a demonstration organisation, call `accfino.modules.taxation.demo_seed.seed(db, ctx)` from a Python shell. It is idempotent and never creates an approved or lodged document, so a trainee walks the workflow themselves.
