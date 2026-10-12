"""Smart Lending: CSV bulk loading of the tables people type in by hand.

Every importer calls the SAME service function as the screen, so permissions (edit / settle / configure), org isolation, validation, duplicate checks and audit apply row by row.
Applicants are named by e-mail (or exact name) and loans by their number (LN-0001 ...), so a file never needs a database id.

NOT bulk-loadable on purpose: statement analyses and credit assessments (computed from uploaded statements - the AI/engine output must not be typed in), applications (they move through
an approval workflow), collections activity/arrangements/hardship (case work with decisions), voiding or posting repayments to the ledger (a person's decision), derived balances and schedules."""
from accfino.core.web import bulk_gate
from accfino.modules.lending import lend_models as M
from accfino.modules.lending.svc import applicants, loans, treasury
from accfino.modules.lending.svc.core import LendError
import accfino.modules.accounting.public as acct
from accfino.shared.bulkload import Column as C, RowError, Spec, as_bool, need

enabled, gate = bulk_gate.enabled, bulk_gate.gate


def applicant_id(db, ctx, who):
    w = (who or "").strip()
    if not w:
        raise RowError("applicant (e-mail or exact name) is required")
    hits = [c for c in acct.contacts_search(db, ctx.org.id, w, 50) if w.lower() in ((c.get("email") or "").lower(), (c.get("name") or "").lower())]
    if not hits:
        raise RowError(f"No applicant with e-mail or name '{w}' (load the applicants table first)")
    if len(hits) > 1:
        raise RowError(f"'{w}' matches {len(hits)} applicants: use the e-mail address")
    return hits[0]["id"]


def loan_id(db, ctx, number):
    n = (number or "").strip()
    if not n:
        raise RowError("loan_number is required")
    x = db.query(M.LendLoan).filter_by(org_id=ctx.org.id, number=n).first()
    if x is None:
        raise RowError(f"Loan {n} was not found")
    return x.id


def drop(d):
    return {k: v for k, v in d.items() if v not in (None, "")}


def h_applicants(db, ctx, a, r):
    need(r, "name")
    applicants.create(db, ctx, a, drop(dict(name=r["name"], email=r.get("email"), phone=r.get("phone"), abn=r.get("abn"), address=r.get("address"), notes=r.get("notes"))))


def h_commitments(db, ctx, a, r):
    need(r, "applicant", "kind", "monthly_repayment")
    applicants.save_commitment(db, ctx, a, applicant_id(db, ctx, r["applicant"]), drop(dict(kind=r["kind"].lower(), lender=r.get("lender"), limit_amount=r.get("limit_amount"), balance=r.get("balance"),
                                                                                         monthly_repayment=r["monthly_repayment"], interest_rate=r.get("interest_rate"), notes=r.get("notes"))))


def h_loans(db, ctx, a, r):
    need(r, "applicant", "original_amount", "rate", "start_date")
    if not (r.get("term_months") or r.get("term_periods")):
        raise RowError("term_months (or term_periods) is required")
    loans.create(db, ctx, a, drop(dict(contact_id=applicant_id(db, ctx, r["applicant"]), original_amount=r["original_amount"], rate=r["rate"], term_months=r.get("term_months"), term_periods=r.get("term_periods"),
                                        frequency=(r.get("frequency") or "").lower(), loan_type=(r.get("loan_type") or "").lower(), start_date=r["start_date"], first_due=r.get("first_due"), lender=r.get("lender"),
                                        purpose=r.get("purpose"), security_description=r.get("security_description"), interest_only_periods=r.get("interest_only_periods"), balloon=r.get("balloon"), notes=r.get("notes"))))


def h_repayments(db, ctx, a, r):
    need(r, "loan_number", "paid_date", "amount")
    loans.add_repayment(db, ctx, a, loan_id(db, ctx, r["loan_number"]), drop(dict(paid_date=r["paid_date"], amount=r["amount"], method=r.get("method"), reference=r.get("reference"),
                                                                                allow_duplicate=as_bool(r.get("allow_duplicate"), "allow_duplicate"))), post=False)


def h_rate_changes(db, ctx, a, r):
    need(r, "loan_number", "effective_date", "rate")
    loans.add_rate_change(db, ctx, a, loan_id(db, ctx, r["loan_number"]), r["effective_date"], r["rate"], r.get("note") or "")


def h_facilities(db, ctx, a, r):
    need(r, "name", "limit_amount")
    treasury.save_facility(db, ctx, a, drop(dict(name=r["name"], lender=r.get("lender"), facility_type=(r.get("facility_type") or "").lower(), limit_amount=r["limit_amount"], drawn_amount=r.get("drawn_amount"),
                                                interest_rate=r.get("interest_rate"), expiry_date=r.get("expiry_date"), repayment_amount=r.get("repayment_amount"), repayment_frequency=(r.get("repayment_frequency") or "").lower(),
                                                next_repayment_date=r.get("next_repayment_date"), status=(r.get("status") or "").lower(), notes=r.get("notes"))))


def h_forecast_items(db, ctx, a, r):
    need(r, "item_date", "amount", "description")
    treasury.save_item(db, ctx, a, drop(dict(item_date=r["item_date"], amount=r["amount"], description=r["description"], category=r.get("category"), status=(r.get("status") or "").lower())))


def _spec(order, key, label, area, cap, cols, handler, notes=""):
    def wrapped(db, ctx, a, r):
        a.require(cap)
        return handler(db, ctx, a, r)
    return Spec(key=key, label=label, area=area, capability=cap, columns=cols, handler=wrapped, order=order, notes=notes)


SPECS = {s.key: s for s in [
    _spec(10, "applicants", "Applicants", "Applicants", "edit", [C("name", True, "", "Jane Citizen"), C("email", False, "Used to find the applicant in other files", "jane@example.com"), C("phone"), C("abn"), C("address"), C("notes")], h_applicants,
          "Never put a tax file number in any column: it is refused. An applicant that already exists (same name/e-mail) is matched, not duplicated."),
    _spec(20, "commitments", "Applicant commitments", "Applicants", "edit", [C("applicant", True, "E-mail or exact name of an existing applicant", "jane@example.com"),
          C("kind", True, "home_loan, investment_loan, car_loan, personal_loan, credit_card, hecs_help, buy_now_pay_later, child_support, other", "car_loan"), C("monthly_repayment", True, "", "450"), C("lender"), C("limit_amount"), C("balance"),
          C("interest_rate", False, "A fraction: 6.5% is 0.065", "0.069"), C("notes")], h_commitments),
    _spec(30, "loans", "Loan register", "Loans", "settle", [C("applicant", True, "E-mail or exact name of an existing applicant", "jane@example.com"), C("original_amount", True, "", "25000"), C("rate", True, "A fraction: 6.5% is 0.065", "0.065"),
          C("term_months", False, "Or give term_periods", "60"), C("term_periods"), C("start_date", True, "YYYY-MM-DD", "2026-07-01"), C("frequency", False, "weekly, fortnightly, monthly, quarterly (default monthly)", "monthly"),
          C("loan_type", False, "term_loan, interest_only, line_of_credit, overdraft, car_loan, personal_loan, home_loan, business_loan, equipment_lease, hire_purchase, other", "car_loan"), C("first_due"), C("lender"), C("purpose"),
          C("security_description"), C("interest_only_periods"), C("balloon"), C("notes")], h_loans,
          "Each row gets the next loan number. Ledger accounts are not set from a file: set them on the loan if repayments are to be posted. Re-loading the same file creates the loans again."),
    _spec(40, "repayments", "Loan repayments", "Loans", "edit", [C("loan_number", True, "", "LN-0001"), C("paid_date", True, "Not before the loan started, not in the future", "2026-08-01"), C("amount", True, "", "480.25"), C("method"), C("reference"),
          C("allow_duplicate", False, "yes only for a genuine second payment of the same amount on the same day", "")], h_repayments,
          "Recorded only - not posted to the ledger (posting is a separate decision on the loan screen). Exact duplicates are rejected."),
    _spec(50, "rate_changes", "Loan rate changes", "Loans", "settle", [C("loan_number", True, "", "LN-0001"), C("effective_date", True, "", "2026-09-01"), C("rate", True, "A fraction: 6.5% is 0.065", "0.0695"), C("note")], h_rate_changes,
          "A change on a date that already has one replaces it."),
    _spec(60, "facilities", "Credit facilities", "Treasury", "configure", [C("name", True, "", "Westpac overdraft"), C("limit_amount", True, "", "50000"), C("lender"),
          C("facility_type", False, "overdraft, line_of_credit, term_loan, invoice_finance, equipment_finance, credit_card, other", "overdraft"), C("drawn_amount", False, "Used when no ledger account is linked", "10000"),
          C("interest_rate", False, "A fraction", "0.085"), C("expiry_date"), C("repayment_amount"), C("repayment_frequency"), C("next_repayment_date"), C("status", False, "active or closed", "active"), C("notes")], h_facilities,
          "Always creates a new facility; to change one, edit it on the Treasury screen."),
    _spec(70, "forecast_items", "Expected cash movements", "Treasury", "edit", [C("item_date", True, "", "2026-11-15"), C("amount", True, "Money in is positive, money out negative", "-2500"), C("description", True, "", "Insurance premium"),
          C("category"), C("status", False, "expected, received, cancelled", "expected")], h_forecast_items),
]}
