"""Bulk CSV import for every Taxation module: one framework, one importer per dataset.

Flow: PREVIEW (nothing is written) -> COMMIT. Both run the same pipeline: parse the file, check the columns, coerce and check each value, detect duplicates (inside the file and already in the
database), then validate each row by running the REAL service inside a savepoint that is always rolled back, so preview can never disagree with the actual insert. Commit repeats that and
inserts the rows that passed, one savepoint per row, so a failing row cannot damage anything. Modes: 'valid_only' (default) or 'all_or_nothing' (any error refuses the whole file).
Every commit is one audit event carrying the file's SHA-256 and the counts. Nothing here talks to the ATO: imported lodgement data are records of what the user says was lodged."""
import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional, Tuple

from accfino.modules.taxation.engine.money import D, q2
from accfino.modules.taxation.models import tax as T
from accfino.modules.taxation.services import (bas, cgt, core, div7a, fbt, gst, obligations, planning, profile as P, returns, workpapers)
from accfino.modules.taxation.services.core import TaxError

MAX_BYTES, MAX_ROWS = 2_000_000, 5000
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y")
TRUE, FALSE = {"true", "yes", "y", "1", "t"}, {"false", "no", "n", "0", "f", ""}


@dataclass
class Col:
    name: str
    kind: str = "text"            # text | int | money | date | bool | enum | percent
    required: bool = False
    enum: Tuple[str, ...] = ()
    example: str = ""
    help: str = ""
    maxlen: int = 300


def canon(h: str) -> str:
    return re.sub(r"[\s\-]+", "_", (h or "").strip().lower().lstrip("\ufeff"))


def coerce(c: Col, raw: Optional[str]):
    s = (raw if raw is not None else "").strip()
    if s == "":
        if c.required:
            raise ValueError(f"{c.name} is required")
        return None
    if c.kind in ("text", "enum"):
        if len(s) > c.maxlen:
            raise ValueError(f"{c.name} is longer than {c.maxlen} characters")
        if c.kind == "enum":
            s = s.lower().replace(" ", "_")
            if s not in c.enum:
                raise ValueError(f"{c.name} must be one of: {', '.join(c.enum)} (got '{raw.strip()}')")
        return s
    if c.kind == "int":
        try:
            return int(Decimal(s))
        except (InvalidOperation, ValueError):
            raise ValueError(f"{c.name} must be a whole number (got '{s}')")
    if c.kind in ("money", "percent"):
        neg = s.startswith("(") and s.endswith(")")
        t = s.strip("()").replace("$", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d+,\d{1,2}", t):                                      # '1320,00' is a decimal comma: reading it as 132,000 would silently multiply the amount by 100
            raise ValueError(f"{c.name} looks like it uses a decimal comma ('{s}'): use a full stop for cents, for example 1320.00")
        t = t.replace(",", "")
        try:
            v = Decimal(t)
        except InvalidOperation:
            raise ValueError(f"{c.name} must be a number (got '{s}')")
        return q2(-v if neg else v) if c.kind == "money" else v
    if c.kind == "date":
        for f in DATE_FORMATS:
            try:
                return datetime.strptime(s, f).date()
            except ValueError:
                pass
        raise ValueError(f"{c.name} must be a date such as 2026-09-30 or 30/09/2026 (got '{s}')")
    if c.kind == "bool":
        v = s.lower()
        if v in TRUE:
            return True
        if v in FALSE:
            return False
        raise ValueError(f"{c.name} must be yes/no or true/false (got '{s}')")
    raise ValueError("unsupported column type")


class Importer:
    key = title = description = ""
    cap = "prepare"
    columns: List[Col] = []
    examples: List[dict] = []
    notes: List[str] = []

    def natural_key(self, d: dict) -> str:                                  # identity inside the file and in the database
        return "|".join(str(d.get(c.name)) for c in self.columns if c.required)

    def exists(self, db, ctx, d: dict) -> bool:                              # already in the database?
        return False

    def insert(self, db, ctx, a, d: dict):                                  # the real operation (also used, rolled back, for validation)
        raise NotImplementedError

    group_key: Optional[Callable[[dict], Any]] = None                        # rows sharing a key are one record (e.g. the levers of one scenario)

    def insert_group(self, db, ctx, a, rows: List[dict]):
        raise NotImplementedError

    def group_exists(self, db, ctx, rows: List[dict]) -> bool:
        return False

    def warn(self, d: dict) -> List[str]:
        return []


IMPORTERS: Dict[str, Importer] = {}


def reg(i: Importer) -> Importer:
    IMPORTERS[i.key] = i
    return i


def _get(db, T_, ctx, **kw):
    return db.query(T_).filter_by(org_id=ctx.org.id, **kw).first()


# ---------------------------------------------------------------------------------------------------------------------- GST
class GstAdjustments(Importer):
    key, title = "gst_adjustments", "GST adjustments"
    description = "Bad debts, change of extent, private use, goods returned and similar. Confirmed rows feed the activity statement for their period (increasing -> 1A, decreasing -> 1B)."
    columns = [Col("adjustment_date", "date", True, example="2026-08-14", help="Date of the adjustment event"), Col("adjustment_type", "enum", True, T.GST_ADJ_TYPES, "decreasing", "increasing adds to 1A, decreasing adds to 1B"),
               Col("reason", "enum", False, T.GST_ADJ_REASONS, "bad_debt"), Col("description", "text", True, example="Customer invoice INV-1042 written off"),
               Col("amount_ex_gst", "money", False, example="1200.00"), Col("gst_amount", "money", True, example="120.00", help="Must be > 0 and no more than 10% of amount_ex_gst"),
               Col("reference", "text", False, example="INV-1042"), Col("status", "enum", False, T.GST_ADJ_STATUSES, "confirmed", "draft rows are kept but excluded from the BAS")]
    examples = [dict(adjustment_date="2026-08-14", adjustment_type="decreasing", reason="bad_debt", description="Customer invoice INV-1042 written off", amount_ex_gst="1200.00", gst_amount="120.00", reference="INV-1042", status="confirmed")]

    def _body(self, d):
        return dict(adj_date=d["adjustment_date"], adj_type=d["adjustment_type"], reason=d.get("reason") or "other", description=d["description"], amount_ex_gst=d.get("amount_ex_gst"), gst_amount=d["gst_amount"],
                    reference=d.get("reference"), status=d.get("status") or "confirmed")

    def natural_key(self, d):
        return f"{d['adjustment_date']}|{d['adjustment_type']}|{d.get('reference') or d['description']}|{d['gst_amount']}"

    def exists(self, db, ctx, d):
        return any(r["adj_date"] == d["adjustment_date"].isoformat() and r["adj_type"] == d["adjustment_type"] and D(r["gst_amount"]) == d["gst_amount"] and (r["reference"] or r["description"]) == (d.get("reference") or d["description"])
                   for r in gst.listing(db, ctx))

    def insert(self, db, ctx, a, d):
        gst.save(db, ctx, a, self._body(d), source="import")

    def warn(self, d):
        try:
            return gst.warnings_for(gst.clean(self._body(d)))
        except TaxError:
            return []


class GstHistory(Importer):
    key, title = "gst_history", "Activity statement history (BAS / IAS)"
    description = "Statements lodged before AccFino (or drafts). Labels are loaded as lodged, not recomputed; lodged and paid rows are locked like any lodged statement."
    _lab = ("G1", "G2", "G3", "G10", "G11", "1A", "1B", "W1", "W2", "W3", "W4", "5A", "F1")
    columns = ([Col("kind", "enum", True, ("bas", "ias"), "bas"), Col("period_start", "date", True, example="2026-07-01"), Col("period_end", "date", True, example="2026-09-30"),
                Col("status", "enum", True, ("draft", "lodged", "paid"), "lodged")] + [Col(l.lower(), "money", False, example="0.00", help=f"ATO label {l}") for l in _lab] +
               [Col("lodged_on", "date", False, example="2026-10-27", help="Required for lodged / paid"), Col("lodgement_reference", "text", False, example="ATO-5521-77", help="ATO receipt: required for lodged / paid"),
                Col("lodgement_method", "enum", False, ("ato_online_services", "tax_agent", "gateway", "other"), "tax_agent"), Col("paid_on", "date", False, example="2026-10-28", help="Required for paid")])
    examples = [dict(kind="bas", period_start="2026-07-01", period_end="2026-09-30", status="lodged", g1="82500.00", g10="0.00", g11="31900.00", **{"1a": "7500.00", "1b": "2900.00"}, lodged_on="2026-10-27", lodgement_reference="ATO-5521-77", lodgement_method="tax_agent")]

    def natural_key(self, d):
        return f"{d['kind']}|{d['period_start']}|{d['period_end']}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxBasStatement).filter(T.TaxBasStatement.org_id == ctx.org.id, T.TaxBasStatement.kind == d["kind"], T.TaxBasStatement.period_start == d["period_start"],
                                                  T.TaxBasStatement.period_end == d["period_end"], T.TaxBasStatement.status != "void").first() is not None

    def insert(self, db, ctx, a, d):
        if d["status"] in ("lodged", "paid"):
            if not d.get("lodged_on") or not d.get("lodgement_reference"):
                raise TaxError("lodged_on and lodgement_reference (the ATO receipt) are required when status is lodged or paid")
            if d["lodged_on"] < d["period_end"]:
                raise TaxError("lodged_on cannot be before the period ends")
        if d["status"] == "paid" and (not d.get("paid_on") or d["paid_on"] < d["lodged_on"]):
            raise TaxError("paid_on is required and cannot be before lodged_on")
        if d["status"] == "draft" and (d.get("lodged_on") or d.get("paid_on")):
            raise TaxError("A draft cannot have lodged_on or paid_on")
        dd = dict(d)
        for l in self._lab:
            dd[l] = d.get(l.lower())
        bas.import_history(db, ctx, a, dd)

    def warn(self, d):
        w = []
        g1, a1, w1, w2 = (d.get(k) or Decimal(0) for k in ("g1", "1a", "w1", "w2"))
        if g1 and a1 > q2(g1 / 11) + 1:
            w.append("1A is more than 1/11 of G1: check the GST on sales")
        if w2 > w1 > 0:
            w.append("W2 (PAYG withheld) is more than W1 (wages)")
        return w


# ---------------------------------------------------------------------------------------------------------------------- CGT
class CgtEvents(Importer):
    key, title = "cgt_events", "CGT events"
    description = "Disposals of shares, ETFs, crypto, property and business assets. Each row is one CGT event with its own acquisition date (needed for the 12-month discount)."
    columns = [Col("asset_class", "enum", True, T.CGT_CLASSES, "shares"), Col("asset_name", "text", True, example="BHP Group Ltd (BHP)"), Col("quantity", "money", False, example="250"),
               Col("acquire_date", "date", True, example="2024-03-12"), Col("dispose_date", "date", True, example="2026-09-18"), Col("proceeds", "money", True, example="14250.00"),
               Col("acquisition_cost", "money", False, example="9800.00"), Col("incidental_costs", "money", False, example="19.95"), Col("ownership_costs", "money", False, example="0"),
               Col("capital_improvements", "money", False, example="0"), Col("disposal_costs", "money", False, example="19.95"),
               Col("pre_cgt", "bool", False, example="no", help="Acquired before 20 September 1985"), Col("main_residence_exempt", "bool", False, example="no", help="Property only"), Col("notes", "text", False)]
    examples = [dict(asset_class="shares", asset_name="BHP Group Ltd (BHP)", quantity="250", acquire_date="2024-03-12", dispose_date="2026-09-18", proceeds="14250.00", acquisition_cost="9800.00", incidental_costs="19.95", disposal_costs="19.95", pre_cgt="no", main_residence_exempt="no")]

    def _body(self, d):
        return dict(asset_class=d["asset_class"], asset_name=d["asset_name"], quantity=d.get("quantity"), acquire_date=d["acquire_date"], dispose_date=d["dispose_date"], proceeds=d["proceeds"],
                    acquisition_cost=d.get("acquisition_cost") or 0, incidental_costs=d.get("incidental_costs") or 0, ownership_costs=d.get("ownership_costs") or 0, capital_improvements=d.get("capital_improvements") or 0,
                    disposal_costs=d.get("disposal_costs") or 0, pre_cgt=bool(d.get("pre_cgt")), main_residence_exempt=bool(d.get("main_residence_exempt")), notes=d.get("notes"), source="csv_import")

    def natural_key(self, d):
        return f"{d['asset_name']}|{d['acquire_date']}|{d['dispose_date']}|{d['proceeds']}|{d.get('quantity')}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxCgtEvent).filter(T.TaxCgtEvent.org_id == ctx.org.id, T.TaxCgtEvent.asset_name == d["asset_name"][:200], T.TaxCgtEvent.acquire_date == d["acquire_date"],
                                              T.TaxCgtEvent.dispose_date == d["dispose_date"], T.TaxCgtEvent.proceeds == d["proceeds"]).first() is not None

    def insert(self, db, ctx, a, d):
        cgt.save_event(db, ctx, a, self._body(d))


class CgtLosses(Importer):
    key, title = "cgt_losses", "Capital losses brought forward"
    description = "Net capital losses carried forward from earlier income years, applied before the CGT discount."
    columns = [Col("fy_incurred", "text", True, example="2024-25", help="Income year the loss arose, e.g. 2024-25"), Col("amount", "money", True, example="3200.00"), Col("note", "text", False, example="Loss on ASX share sales")]
    examples = [dict(fy_incurred="2024-25", amount="3200.00", note="Loss on ASX share sales")]

    def exists(self, db, ctx, d):
        return db.query(T.TaxCapitalLoss).filter_by(org_id=ctx.org.id, fy_incurred=d["fy_incurred"], amount=d["amount"]).first() is not None

    def insert(self, db, ctx, a, d):
        cgt.add_loss(db, ctx, a, d["fy_incurred"], d["amount"], d.get("note") or "")


# ---------------------------------------------------------------------------------------------------------------------- FBT
_FBT_NUM = ("base_value", "days_available", "average_balance", "interest_paid", "days", "actual_cost", "otherwise_deductible", "employee_contribution", "market_value", "taxable_percent")


class FbtBenefits(Importer):
    key, title = "fbt_benefits", "FBT benefits"
    description = "Fringe benefits by FBT year (1 April - 31 March). The taxable value is calculated on import by the FBT engine; fill only the columns that apply to the benefit type."
    columns = ([Col("fbt_year", "text", True, example="FBT2027", help="Year ENDING 31 March, e.g. FBT2027 = 1 Apr 2026 - 31 Mar 2027"), Col("employee", "text", True, example="Sam Driver"),
                Col("benefit_type", "enum", True, T.FBT_TYPES, "car"), Col("description", "text", False, example="Toyota Hilux, private use"), Col("type1", "bool", False, example="yes", help="Employer can claim a GST credit (Type 1)")] +
               [Col(k, "money", False, example=ex, help=h) for k, ex, h in (("base_value", "52000", "car: base value"), ("days_available", "365", "car: days available (1-366)"), ("employee_contribution", "0", "all: contributions by the employee"),
                                                                           ("average_balance", "", "loan: average balance"), ("interest_paid", "", "loan: interest paid by the employee"), ("days", "", "loan: days outstanding"),
                                                                           ("actual_cost", "", "expense payment, property, entertainment: cost"), ("otherwise_deductible", "", "expense payment: otherwise-deductible amount"),
                                                                           ("taxable_percent", "", "entertainment: % treated as taxable"))] +
               [Col("exempt_reason", "text", False, help="Declared exemption (evidence required)"), Col("minor_benefit", "bool", False, help="Under the minor-benefit threshold, infrequent and irregular")])
    examples = [dict(fbt_year="FBT2027", employee="Sam Driver", benefit_type="car", description="Toyota Hilux, private use", type1="yes", base_value="52000", days_available="365", employee_contribution="1500")]

    def _inputs(self, d):
        return {k: str(d[k]) for k in _FBT_NUM if d.get(k) is not None} | ({"exempt_reason": d["exempt_reason"]} if d.get("exempt_reason") else {}) | ({"minor_benefit": True} if d.get("minor_benefit") else {})

    def natural_key(self, d):
        return f"{d['fbt_year']}|{d['employee']}|{d['benefit_type']}|{d.get('description')}|{sorted(self._inputs(d).items())}"

    def exists(self, db, ctx, d):
        want = self._inputs(d)
        for b in db.query(T.TaxFbtBenefit).filter_by(org_id=ctx.org.id, fbt_year=d["fbt_year"], employee=d["employee"][:200], benefit_type=d["benefit_type"]):
            if (b.description or "") == (d.get("description") or "") and {k: str(v) for k, v in (b.inputs or {}).items()} == {k: str(v) for k, v in want.items()}:
                return True
        return False

    def insert(self, db, ctx, a, d):
        fbt.save_benefit(db, ctx, a, d["fbt_year"], dict(benefit_type=d["benefit_type"], employee=d["employee"], description=d.get("description"), type1=True if d.get("type1") is None else d["type1"], inputs=self._inputs(d)))


class Div7aLoans(Importer):
    key, title = "div7a_loans", "Division 7A loans"
    description = "Loans from a private company to a shareholder or associate. A written agreement date is required for the loan to comply."
    columns = [Col("borrower", "text", True, example="Maria Haddad (director)"), Col("advance_date", "date", True, example="2025-08-01"), Col("principal", "money", True, example="120000"),
               Col("term_years", "int", False, example="7", help="7 (unsecured) up to 25 (secured by a registered mortgage)"), Col("secured", "bool", False, example="no"),
               Col("agreement_date", "date", False, example="2025-08-01"), Col("notes", "text", False)]
    examples = [dict(borrower="Maria Haddad (director)", advance_date="2025-08-01", principal="120000", term_years="7", secured="no", agreement_date="2025-08-01")]

    def natural_key(self, d):
        return f"{d['borrower']}|{d['advance_date']}|{d['principal']}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxDiv7aLoan).filter_by(org_id=ctx.org.id, borrower=d["borrower"][:200], advance_date=d["advance_date"], principal=d["principal"]).first() is not None

    def insert(self, db, ctx, a, d):
        div7a.save_loan(db, ctx, a, dict(borrower=d["borrower"], advance_date=d["advance_date"], principal=d["principal"], term_years=d.get("term_years") or 7, secured=bool(d.get("secured")),
                                         agreement_date=d.get("agreement_date"), notes=d.get("notes")))


class Div7aPayments(Importer):
    key, title = "div7a_payments", "Division 7A repayments and interest"
    description = "Repayments and interest on loans already loaded. The loan is identified by borrower and advance date."
    columns = [Col("borrower", "text", True, example="Maria Haddad (director)"), Col("loan_advance_date", "date", True, example="2025-08-01"), Col("paid_on", "date", True, example="2026-06-30"),
               Col("amount", "money", True, example="22000"), Col("kind", "enum", False, ("repayment", "interest"), "repayment"), Col("note", "text", False)]
    examples = [dict(borrower="Maria Haddad (director)", loan_advance_date="2025-08-01", paid_on="2026-06-30", amount="22000", kind="repayment")]

    def _loan(self, db, ctx, d):
        return db.query(T.TaxDiv7aLoan).filter_by(org_id=ctx.org.id, borrower=d["borrower"][:200], advance_date=d["loan_advance_date"]).first()

    def exists(self, db, ctx, d):
        l = self._loan(db, ctx, d)
        return bool(l) and db.query(T.TaxDiv7aPayment).filter_by(org_id=ctx.org.id, loan_id=l.id, paid_on=d["paid_on"], amount=d["amount"], kind=d.get("kind") or "repayment").first() is not None

    def insert(self, db, ctx, a, d):
        l = self._loan(db, ctx, d)
        if l is None:
            raise TaxError(f"No Division 7A loan for '{d['borrower']}' advanced on {d['loan_advance_date']}: import the loans first")
        div7a.add_payment(db, ctx, a, l.id, dict(paid_on=d["paid_on"], amount=d["amount"], kind=d.get("kind") or "repayment", note=d.get("note")))


# ---------------------------------------------------------------------------------------------------------------------- Income tax workings
class IncomeAdjustments(Importer):
    key, title = "income_adjustments", "Book-to-tax adjustments"
    description = "Adjustments between accounting profit and taxable income. Estimates and assumptions are always flagged for review."
    columns = [Col("fy", "text", True, example="2026-27"), Col("code", "enum", False, tuple(c["code"].lower() for c in returns.COMMON_ADJUSTMENTS), "entertainment"),
               Col("description", "text", True, example="Client entertainment (non-deductible)"), Col("direction", "enum", True, ("add", "deduct"), "add", "add increases taxable income"),
               Col("amount", "money", True, example="1850.00"), Col("category", "enum", False, T.ADJ_CATEGORIES, "user_entered"), Col("requires_review", "bool", False, example="no"), Col("review_note", "text", False)]
    examples = [dict(fy="2026-27", code="entertainment", description="Client entertainment (non-deductible)", direction="add", amount="1850.00", category="user_entered")]

    def natural_key(self, d):
        return f"{d['fy']}|{d.get('code')}|{d['description']}|{d['direction']}|{d['amount']}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxAdjustment).filter_by(org_id=ctx.org.id, fy=d["fy"], description=d["description"][:300], direction=d["direction"], amount=d["amount"]).first() is not None

    def insert(self, db, ctx, a, d):
        returns.save_adjustment(db, ctx, a, d["fy"], dict(code=(d.get("code") or "other").upper(), description=d["description"], direction=d["direction"], amount=d["amount"], category=d.get("category") or "user_entered",
                                                           requires_review=bool(d.get("requires_review")), review_note=d.get("review_note")))


class IncomeReturnInputs(Importer):
    key, title = "income_return_inputs", "Income tax return inputs"
    description = "The inputs the ledger cannot know (other income, withholding, offsets, losses). One row per income year: it creates the draft return or updates the existing draft; an approved or lodged return is refused."
    columns = [Col("fy", "text", True, example="2026-27")] + [Col(k, "money", False, example=ex) for k, ex in (("other_income", "4200"), ("labour_income", ""), ("work_expenses_itemised", ""), ("deductions_other", "850"),
                                                                                                            ("franking_credits", "310"), ("tax_withheld", ""), ("help_repayment", ""), ("medicare_surcharge", ""),
                                                                                                            ("other_offsets", ""), ("losses_brought_forward", "0"), ("net_capital_gain_override", ""))]
    examples = [dict(fy="2026-27", other_income="4200", deductions_other="850", franking_credits="310", losses_brought_forward="0")]

    def natural_key(self, d):
        return d["fy"]

    def insert(self, db, ctx, a, d):
        inputs = {k: str(v) for k, v in d.items() if k != "fy" and v is not None}
        p = P.get(db, ctx)
        r = db.query(T.TaxReturn).filter(T.TaxReturn.org_id == ctx.org.id, T.TaxReturn.fy == d["fy"], T.TaxReturn.entity_type == p.entity_type, T.TaxReturn.status != "void").first()
        if r is None:
            returns.create(db, ctx, a, d["fy"], inputs)
        else:
            returns.set_inputs(db, ctx, a, r.id, inputs)


# ---------------------------------------------------------------------------------------------------------------------- Lodgment readiness
class LodgmentObligations(Importer):
    key, title = "lodgment_obligations", "Lodgment tracker (due dates and their status)"
    description = "Due dates for activity statements, returns and other obligations, including ones already lodged or paid. Imported rows are not touched when the calendar is regenerated."
    columns = [Col("kind", "enum", True, T.OBLIGATION_KINDS, "bas"), Col("title", "text", True, example="BAS Q1 Jul-Sep 2026"), Col("fy", "text", False, example="2026-27"),
               Col("period_start", "date", False, example="2026-07-01"), Col("period_end", "date", False, example="2026-09-30"), Col("due_date", "date", True, example="2026-10-28"),
               Col("original_due_date", "date", False), Col("status", "enum", True, T.OBLIGATION_STATUSES, "upcoming"), Col("lodged_on", "date", False, help="Required for lodged / paid"),
               Col("paid_on", "date", False, help="Required for paid"), Col("reference", "text", False, example="ATO-5521-77"), Col("amount", "money", False, example="4600.00"),
               Col("authority", "text", False, example="ATO"), Col("note", "text", False)]
    examples = [dict(kind="bas", title="BAS Q1 Jul-Sep 2026", fy="2026-27", period_start="2026-07-01", period_end="2026-09-30", due_date="2026-10-28", status="lodged", lodged_on="2026-10-20", reference="ATO-5521-77", amount="4600.00", authority="ATO")]

    def natural_key(self, d):
        return f"{d['kind']}|{d['due_date']}|{d['title']}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxObligation).filter(T.TaxObligation.org_id == ctx.org.id, T.TaxObligation.kind == d["kind"], T.TaxObligation.due_date == d["due_date"],
                                                T.TaxObligation.title == d["title"][:200]).first() is not None

    def insert(self, db, ctx, a, d):
        obligations.import_row(db, ctx, a, d)


class LodgmentRegistrations(Importer):
    key, title = "lodgment_registrations", "Tax registrations"
    cap = "config"
    description = "What the organisation is registered for (ABN, GST, PAYG withholding, FBT, state taxes...). Never a Tax File Number."
    columns = [Col("kind", "enum", True, T.REGISTRATION_KINDS, "gst"), Col("authority", "text", False, example="ATO"), Col("identifier", "text", False, example="51 824 753 556"),
               Col("registered_on", "date", False, example="2018-07-01"), Col("cancelled_on", "date", False), Col("notes", "text", False)]
    examples = [dict(kind="gst", authority="ATO", identifier="51 824 753 556", registered_on="2018-07-01")]

    def natural_key(self, d):
        return f"{d['kind']}|{d.get('identifier')}|{d.get('registered_on')}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxRegistration).filter_by(org_id=ctx.org.id, kind=d["kind"], identifier=(d.get("identifier") or None), registered_on=d.get("registered_on")).first() is not None

    def insert(self, db, ctx, a, d):
        obligations.save_registration(db, ctx, a, dict(kind=d["kind"], authority=d.get("authority"), identifier=d.get("identifier"), registered_on=d.get("registered_on"), cancelled_on=d.get("cancelled_on"), notes=d.get("notes")))


# ---------------------------------------------------------------------------------------------------------------------- Tax planning
class PlanningScenarios(Importer):
    key, title = "planning_scenarios", "Tax planning scenarios"
    description = "What-if scenarios. One row per lever; rows with the same fy + scenario_name form one scenario. The estimate is recalculated on import from your ledger and tax profile."
    columns = [Col("fy", "text", True, example="2026-27"), Col("scenario_name", "text", True, example="Prepay insurance + super top-up"), Col("projected_profit", "money", False, example="185000", help="Optional full-year profit; blank = project from the ledger"),
               Col("lever_label", "text", False, example="Prepay 12 months insurance"), Col("lever_amount", "money", False, example="9600"), Col("lever_direction", "enum", False, ("add", "deduct"), "deduct")]
    examples = [dict(fy="2026-27", scenario_name="Prepay insurance + super top-up", projected_profit="185000", lever_label="Prepay 12 months insurance", lever_amount="9600", lever_direction="deduct")]

    def group_key(self, d):
        return (d["fy"], d["scenario_name"])

    def natural_key(self, d):
        return f"{d['fy']}|{d['scenario_name']}|{d.get('lever_label')}|{d.get('lever_amount')}|{d.get('lever_direction')}"

    def _args(self, rows):
        pp = {str(r["projected_profit"]) for r in rows if r.get("projected_profit") is not None}
        if len(pp) > 1:
            raise TaxError("projected_profit differs between the rows of this scenario: give it once or the same on every row")
        levers = []
        for r in rows:
            if (r.get("lever_amount") is None) != (not r.get("lever_label")):
                raise TaxError("A lever needs both lever_label and lever_amount")
            if r.get("lever_amount") is not None:
                if not r.get("lever_direction"):
                    raise TaxError("lever_direction (add or deduct) is required for a lever")
                levers.append(dict(label=r["lever_label"], amount=str(r["lever_amount"]), direction=r["lever_direction"]))
        return rows[0]["fy"], rows[0]["scenario_name"], levers, (pp.pop() if pp else None)

    def group_exists(self, db, ctx, rows):
        return db.query(T.TaxScenario).filter_by(org_id=ctx.org.id, fy=rows[0]["fy"], name=rows[0]["scenario_name"][:120]).first() is not None

    def insert_group(self, db, ctx, a, rows):
        fy, name, levers, pp = self._args(rows)
        planning.save_scenario(db, ctx, a, fy, name, levers, pp)


# ---------------------------------------------------------------------------------------------------------------------- Workpapers
class Workpapers(Importer):
    key, title = "workpapers", "Workpapers"
    description = "Workpaper headers. Import the working lines and evidence with the two companion files, which refer to the workpaper by its reference. Only draft and prepared can be imported: review and approval need a second person."
    columns = [Col("fy", "text", True, example="2026-27"), Col("area", "enum", True, T.WORKPAPER_AREAS, "gst"), Col("title", "text", True, example="GST reconciliation Q1"), Col("reference", "text", True, example="WP-GST-Q1"),
               Col("status", "enum", False, ("draft", "prepared"), "draft"), Col("conclusion", "text", False, example="GST on sales agrees to the ledger within $1.", maxlen=4000)]
    examples = [dict(fy="2026-27", area="gst", title="GST reconciliation Q1", reference="WP-GST-Q1", status="draft", conclusion="GST on sales agrees to the ledger within $1.")]

    def natural_key(self, d):
        return f"{d['fy']}|{d['reference']}"

    def exists(self, db, ctx, d):
        return db.query(T.TaxWorkpaper).filter_by(org_id=ctx.org.id, fy=d["fy"], reference=d["reference"][:30]).first() is not None

    def insert(self, db, ctx, a, d):
        w = workpapers.save(db, ctx, a, dict(fy=d["fy"], area=d["area"], title=d["title"], reference=d["reference"], content=dict(lines=[], conclusion=d.get("conclusion") or "")))
        if (d.get("status") or "draft") == "prepared":
            workpapers.advance(db, ctx, a, w.id, "prepared")


def _wp(db, ctx, d):
    return db.query(T.TaxWorkpaper).filter_by(org_id=ctx.org.id, fy=d["fy"], reference=d["workpaper_reference"][:30]).first()


class WorkpaperLines(Importer):
    key, title = "workpaper_lines", "Workpaper lines"
    description = "The working lines of workpapers already imported or created (matched on fy + workpaper_reference). Lines are added in line_no order; a workpaper must still be a draft."
    columns = [Col("fy", "text", True, example="2026-27"), Col("workpaper_reference", "text", True, example="WP-GST-Q1"), Col("line_no", "int", True, example="1"),
               Col("label", "text", True, example="GST on sales per ledger (1A)"), Col("amount", "money", False, example="7500.00"),
               Col("kind", "enum", False, ("source", "calculated", "user_entered", "assumption", "estimate", "review"), "source"), Col("source", "text", False, example="Ledger GST report"), Col("note", "text", False)]
    examples = [dict(fy="2026-27", workpaper_reference="WP-GST-Q1", line_no="1", label="GST on sales per ledger (1A)", amount="7500.00", kind="source", source="Ledger GST report")]

    def group_key(self, d):
        return (d["fy"], d["workpaper_reference"])

    def natural_key(self, d):
        return f"{d['fy']}|{d['workpaper_reference']}|{d['line_no']}"

    def exists(self, db, ctx, d):
        w = _wp(db, ctx, d)
        return bool(w) and any((l.get("label") == d["label"] and (l.get("amount") in (None, "") and d.get("amount") is None or l.get("amount") == (str(d["amount"]) if d.get("amount") is not None else None)))
                               for l in (w.content or {}).get("lines", []))

    def insert_group(self, db, ctx, a, rows):
        w = _wp(db, ctx, dict(fy=rows[0]["fy"], workpaper_reference=rows[0]["workpaper_reference"]))
        if w is None:
            raise TaxError(f"Workpaper '{rows[0]['workpaper_reference']}' ({rows[0]['fy']}) was not found: import the workpapers first")
        if w.status != "draft":
            raise TaxError(f"Workpaper '{w.reference}' is {w.status}: only a draft can receive lines")
        content = dict(w.content or {})
        lines = list(content.get("lines", [])) + [dict(label=r["label"], amount=None if r.get("amount") is None else str(r["amount"]), kind=r.get("kind") or "source", source=r.get("source") or "", note=r.get("note") or "")
                                                  for r in sorted(rows, key=lambda r: r["line_no"])]
        workpapers.save(db, ctx, a, dict(fy=w.fy, area=w.area, title=w.title, reference=w.reference, linked_type=w.linked_type, linked_id=w.linked_id, content=dict(lines=lines, conclusion=content.get("conclusion", ""))), w.id)


class WorkpaperEvidence(Importer):
    key, title = "workpaper_evidence", "Workpaper evidence register"
    description = "Evidence records (notes, links and ledger references) attached to workpapers. Files cannot be imported from a CSV: upload them on the workpaper."
    columns = [Col("fy", "text", True, example="2026-27"), Col("workpaper_reference", "text", True, example="WP-GST-Q1"), Col("kind", "enum", True, ("note", "url", "ledger_ref"), "ledger_ref"),
               Col("title", "text", True, example="Q1 GST report from the ledger"), Col("note", "text", False), Col("url", "text", False, example="https://www.ato.gov.au/"), Col("ledger_ref", "text", False, example="report:gst:2026-07-01..2026-09-30")]
    examples = [dict(fy="2026-27", workpaper_reference="WP-GST-Q1", kind="ledger_ref", title="Q1 GST report from the ledger", ledger_ref="report:gst:2026-07-01..2026-09-30")]

    def exists(self, db, ctx, d):
        w = _wp(db, ctx, d)
        return bool(w) and db.query(T.TaxEvidence).filter_by(org_id=ctx.org.id, workpaper_id=w.id, kind=d["kind"], title=d["title"][:200]).first() is not None

    def natural_key(self, d):
        return f"{d['fy']}|{d['workpaper_reference']}|{d['kind']}|{d['title']}"

    def insert(self, db, ctx, a, d):
        w = _wp(db, ctx, d)
        if w is None:
            raise TaxError(f"Workpaper '{d['workpaper_reference']}' ({d['fy']}) was not found: import the workpapers first")
        workpapers.add_evidence(db, ctx, a, dict(workpaper_id=w.id, kind=d["kind"], title=d["title"], note=d.get("note"), url=d.get("url"), ledger_ref=d.get("ledger_ref")))


for _i in (GstAdjustments(), GstHistory(), CgtEvents(), CgtLosses(), FbtBenefits(), Div7aLoans(), Div7aPayments(), IncomeAdjustments(), IncomeReturnInputs(), LodgmentObligations(), LodgmentRegistrations(),
           PlanningScenarios(), Workpapers(), WorkpaperLines(), WorkpaperEvidence()):
    reg(_i)


# ---------------------------------------------------------------------------------------------------------------------- pipeline
def catalogue() -> List[dict]:
    return [dict(key=i.key, title=i.title, description=i.description, capability=i.cap, notes=i.notes, columns=[dict(name=c.name.upper() if c.name[0].isdigit() or c.name in ("g1", "g2", "g3", "g10", "g11") else c.name,
                                                                                                                     kind=c.kind, required=c.required, enum=list(c.enum), example=c.example, help=c.help) for c in i.columns])
            for i in IMPORTERS.values()]


def template_csv(key: str) -> str:
    i = _imp(key)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.name for c in i.columns])
    for ex in i.examples:
        w.writerow([ex.get(c.name, "") for c in i.columns])
    return buf.getvalue()


def _imp(key: str) -> Importer:
    if key not in IMPORTERS:
        raise core.NotFound("Import dataset")
    return IMPORTERS[key]


def _grid(raw: bytes) -> Tuple[List[str], List[List[str]]]:
    if not raw or not raw.strip():
        raise TaxError("The file is empty")
    if len(raw) > MAX_BYTES:
        raise TaxError(f"The file is larger than {MAX_BYTES // 1_000_000} MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise TaxError("The file is not text (use a CSV saved as UTF-8)")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = max((",", ";", "\t"), key=first.count)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise TaxError("The file needs a header row and at least one data row")
    if len(rows) - 1 > MAX_ROWS:
        raise TaxError(f"The file has more than {MAX_ROWS} data rows: split it")
    return [canon(h) for h in rows[0]], rows[1:]


def _dry(db, fn) -> Optional[str]:
    """Run the real operation and ALWAYS roll it back: the message of a TaxError (or a database refusal) is the validation result."""
    sp = db.begin_nested()
    try:
        fn()
        return None
    except TaxError as e:
        return e.message
    except Exception as e:                                                         # a constraint or conversion problem: report, never crash the preview
        return f"{type(e).__name__}: {str(getattr(e, 'orig', e))[:160]}"
    finally:
        sp.rollback()


def _display(d: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, date) else str(v)) for k, v in d.items() if v not in (None, "")}


def preview(db, ctx, a: core.Access, key: str, raw: bytes) -> dict:
    """Nothing is written. Same pipeline as commit()."""
    imp = _imp(key)
    a.require(imp.cap)
    headers, body = _grid(raw)
    res = _run(db, ctx, a, imp, headers, body, raw)
    known = {c.name for c in imp.columns}
    out = dict(module=key, title=imp.title, file_sha256=res["file_sha256"], total=res["total"], missing_columns=res.get("missing", []), unknown_columns=[h for h in headers if h and h not in known],
               ok=res["ok"], duplicates=res["duplicates"], errors=res["errors"], warnings=res["warnings"], rows=[])
    if res.get("file_error"):
        out.update(file_error=res["file_error"] + ". Download the CSV template for the exact layout.", can_commit=False)
        return out
    out["rows"] = [{k: v for k, v in r.items() if k != "_d"} for r in res["_rows"]]
    out["can_commit"] = out["ok"] > 0
    return out


def commit(db, ctx, a: core.Access, key: str, raw: bytes, mode: str = "valid_only") -> dict:
    imp = _imp(key)
    a.require(imp.cap)
    if mode not in ("valid_only", "all_or_nothing"):
        raise TaxError("mode must be valid_only or all_or_nothing")
    headers, body = _grid(raw)
    pv = _run(db, ctx, a, imp, headers, body, raw)
    if pv.get("file_error"):
        raise TaxError(pv["file_error"])
    if mode == "all_or_nothing" and pv["errors"]:
        raise core.Conflict(f"{pv['errors']} row(s) have errors: nothing was imported (mode: all or nothing). Fix the file or import the valid rows only.", "has_errors")
    imported, failed = 0, []
    done_groups = set()
    for row in pv["_rows"]:
        if row["status"] != "ok":
            continue
        d = row["_d"]
        sp = db.begin_nested()
        try:
            if imp.group_key is not None:
                gk = imp.group_key(d)
                if gk in done_groups:
                    sp.commit()
                    imported += 1
                    continue
                imp.insert_group(db, ctx, a, [r["_d"] for r in pv["_rows"] if r["status"] == "ok" and r["_d"] is not None and imp.group_key(r["_d"]) == gk])
                done_groups.add(gk)
            else:
                imp.insert(db, ctx, a, d)
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append(dict(line=row["line"], error=(e.message if isinstance(e, TaxError) else f"{type(e).__name__}: {str(getattr(e, 'orig', e))[:160]}")))
    core.record(db, ctx, f"import.{key}", "tax_import", key, f"CSV import '{imp.title}': {imported} imported, {pv['duplicates']} duplicate(s) skipped, {pv['errors']} rejected, {len(failed)} failed (file sha256 {pv['file_sha256'][:12]})",
                None, dict(mode=mode, imported=imported, duplicates=pv["duplicates"], rejected=pv["errors"], failed=len(failed), sha256=pv["file_sha256"]))
    for row in pv["_rows"]:
        row.pop("_d", None)
    return dict(module=key, title=imp.title, mode=mode, imported=imported, skipped_duplicates=pv["duplicates"], rejected=pv["errors"], failed=failed, total=pv["total"], file_sha256=pv["file_sha256"],
                rows=pv["_rows"], warnings=pv["warnings"])


def _run(db, ctx, a, imp, headers, body, raw):
    known = {c.name: c for c in imp.columns}
    missing = [c.name for c in imp.columns if c.required and c.name not in headers]
    out = dict(total=len(body), ok=0, duplicates=0, errors=0, warnings=0, file_sha256=hashlib.sha256(raw).hexdigest(), _rows=[])
    if missing:
        out["file_error"] = "Required column(s) missing: " + ", ".join(missing)
        out["missing"] = missing
        return out
    idx = {h: i for i, h in enumerate(headers) if h in known}
    seen, groups = {}, {}
    for n, r in enumerate(body, start=2):
        row = dict(line=n, status="ok", messages=[], data=None, _d=None)
        d, errs = {}, []
        for c in imp.columns:
            raw_v = r[idx[c.name]] if c.name in idx and idx[c.name] < len(r) else ""
            try:
                d[c.name] = coerce(c, raw_v)
            except ValueError as e:
                errs.append(str(e))
        row["data"] = _display(d)
        if errs:
            row["status"], row["messages"] = "error", [dict(level="error", text=t) for t in errs]
        else:
            k = imp.natural_key(d)
            if k in seen:
                row["status"], row["messages"] = "duplicate", [dict(level="info", text=f"Duplicate of line {seen[k]} in this file: skipped")]
            else:
                seen[k] = n
                if imp.group_key is None and imp.exists(db, ctx, d):
                    row["status"], row["messages"] = "duplicate", [dict(level="info", text="Already in the database: skipped")]
                else:
                    row["_d"] = d
                    if imp.group_key is not None:
                        groups.setdefault(imp.group_key(d), []).append(row)
        out["_rows"].append(row)
    for row in out["_rows"]:
        if row["status"] == "ok" and row["_d"] is not None and imp.group_key is None:
            msg = _dry(db, lambda: imp.insert(db, ctx, a, row["_d"]))
            if msg:
                row["status"], row["messages"] = "error", [dict(level="error", text=msg)]
            else:
                row["messages"] += [dict(level="warning", text=w) for w in imp.warn(row["_d"])]
    for gk, rows in groups.items():
        ds = [r["_d"] for r in rows]
        if imp.group_exists(db, ctx, ds):
            for r in rows:
                r["status"], r["messages"] = "duplicate", [dict(level="info", text="Already in the database: skipped")]
            continue
        msg = _dry(db, lambda: imp.insert_group(db, ctx, a, ds))
        if msg:
            for r in rows:
                r["status"], r["messages"] = "error", [dict(level="error", text=msg if len(rows) == 1 else f"{msg} (this record spans {len(rows)} rows)")]
        else:
            for r in rows:
                if imp.exists(db, ctx, r["_d"]):
                    r["status"], r["messages"] = "duplicate", [dict(level="info", text="Already in the database: skipped")]
    for row in out["_rows"]:
        out["ok"] += row["status"] == "ok"
        out["duplicates"] += row["status"] == "duplicate"
        out["errors"] += row["status"] == "error"
        out["warnings"] += any(m["level"] == "warning" for m in row["messages"])
    return out
