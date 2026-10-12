"""Bulk CSV import for Investments. PREVIEW writes nothing; COMMIT inserts the valid rows. Both run one pipeline: decode, check columns, coerce values, detect duplicates (inside the file and already in the database),
then validate every row by running the REAL service inside a savepoint that is always rolled back, so preview cannot disagree with the actual insert. Commit inserts one savepoint per row.
Identical transaction rows are treated as duplicates: give genuinely identical trades different references (contract note numbers). Every commit is one audit event with the file's SHA-256."""
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from accfino.modules.investments.engine.money import D, q2
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core, data, property_svc, valuations, wealth
from accfino.modules.investments.services.core import InvError

MAX_BYTES, MAX_ROWS = 2_000_000, 5000
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y/%m/%d")
TRUE, FALSE = {"true", "yes", "y", "1", "t"}, {"false", "no", "n", "0", "f", ""}


@dataclass
class Col:
    name: str
    kind: str = "text"
    required: bool = False
    enum: Tuple[str, ...] = ()
    example: str = ""
    help: str = ""
    maxlen: int = 300


def canon(h: str) -> str:
    return re.sub(r"[\s\-/]+", "_", (h or "").strip().lower().lstrip("\ufeff"))


def coerce(c: Col, raw):
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
    if c.kind in ("money", "qty", "percent"):
        neg = s.startswith("(") and s.endswith(")")
        t = s.strip("()").replace("$", "").replace("%", "").strip()
        if re.fullmatch(r"-?\d+,\d{1,2}", t):
            raise ValueError(f"{c.name} looks like it uses a decimal comma ('{s}'): use a full stop, for example 1320.00")
        t = t.replace(",", "")
        try:
            v = Decimal(t)
        except InvalidOperation:
            raise ValueError(f"{c.name} must be a number (got '{s}')")
        return -v if neg else v
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
    cap = "import"
    columns: List[Col] = []
    examples: List[dict] = []

    def natural_key(self, d: dict) -> str:
        return "|".join(str(d.get(c.name)) for c in self.columns if c.required)

    def exists(self, db, ctx, d: dict) -> bool:
        return False

    def insert(self, db, ctx, a, d: dict):
        raise NotImplementedError

    def warn(self, d: dict) -> List[str]:
        return []


IMPORTERS: Dict[str, Importer] = {}


def reg(i):
    IMPORTERS[i.key] = i
    return i


def _acc(db, ctx, name):
    x = db.query(M.InvAccount).filter_by(org_id=ctx.org.id).filter(M.InvAccount.name == name).first()
    if x is None:
        raise InvError(f"Account '{name}' not found: create it first (Accounts) or import accounts.csv")
    return x


def _sec(db, ctx, code, kinds=None):
    q = db.query(M.InvSecurity).filter_by(org_id=ctx.org.id, code=code.strip().upper())
    if kinds:
        q = q.filter(M.InvSecurity.kind.in_(kinds))
    rows = q.all()
    if not rows:
        raise InvError(f"Security '{code.upper()}' not found: import or add it first")
    if len(rows) > 1:
        raise InvError(f"'{code.upper()}' matches more than one kind of security: give the kind column")
    return rows[0]


def _skey(prefix: str, d: dict) -> str:
    return hashlib.sha256((prefix + json.dumps({k: str(v) for k, v in sorted(d.items()) if v is not None}, sort_keys=True)).encode()).hexdigest()[:40]


def _txn_exists(db, ctx, key):
    return db.query(M.InvTransaction.id).filter_by(org_id=ctx.org.id, source_key=key).first() is not None


# ---------------------------------------------------------------------------------------------------------------------- master data
class Accounts(Importer):
    key, title = "accounts", "Accounts (brokers, exchanges, platforms)"
    cap = "edit"
    description = "Where investments are held. Never a Tax File Number: only the last digits of a HIN or a wallet label."
    columns = [Col("name", "text", True, example="CommSec CDIA"), Col("kind", "enum", False, M.ACCOUNT_KINDS, "broker"), Col("institution", "text", False, example="Commonwealth Securities"), Col("identifier", "text", False, example="HIN ending 4821"), Col("holder_note", "text", False, example="Joint: M and S Haddad")]
    examples = [dict(name="CommSec CDIA", kind="broker", institution="Commonwealth Securities", identifier="HIN ending 4821")]

    def natural_key(self, d):
        return d["name"].strip().lower()

    def exists(self, db, ctx, d):
        return db.query(M.InvAccount.id).filter_by(org_id=ctx.org.id).filter(M.InvAccount.name == d["name"]).first() is not None

    def insert(self, db, ctx, a, d):
        data.save_account(db, ctx, a, d)


class Securities(Importer):
    key, title = "securities", "Securities (shares, ETFs, crypto, funds, bonds)"
    cap = "edit"
    description = "The instruments you hold. Bonds need face value, coupon rate (a fraction: 0.045 = 4.5%), frequency and maturity; funds can carry the MER and AMIT flag."
    columns = [Col("kind", "enum", True, M.SECURITY_KINDS, "etf"), Col("code", "text", True, example="VAS"), Col("name", "text", True, example="Vanguard Australian Shares Index ETF"), Col("exchange", "text", False, example="ASX"), Col("isin", "text", False, example="AU000000VAS1"),
               Col("asset_class", "enum", False, M.ASSET_CLASSES, "au_equity"), Col("sector", "text", False, example="Diversified"), Col("country", "text", False, example="Australia"), Col("currency", "text", False, example="AUD"),
               Col("mer_pct", "percent", False, example="0.07", help="% a year"), Col("amit", "bool", False, example="yes"), Col("face_value", "money", False, example="1000", help="Bonds: per unit"), Col("coupon_rate", "qty", False, example="0.0425", help="Annual, as a fraction"),
               Col("coupon_freq", "int", False, example="2"), Col("issue_date", "date", False), Col("maturity_date", "date", False, example="2032-06-21"), Col("day_count", "enum", False, ("act/act", "act/365"), "act/act")]
    examples = [dict(kind="etf", code="VAS", name="Vanguard Australian Shares Index ETF", exchange="ASX", asset_class="au_equity", sector="Diversified", country="Australia", mer_pct="0.07", amit="yes")]

    def natural_key(self, d):
        return f"{d['kind']}|{d['code'].strip().upper()}"

    def exists(self, db, ctx, d):
        return db.query(M.InvSecurity.id).filter_by(org_id=ctx.org.id, kind=d["kind"], code=d["code"].upper()).first() is not None

    def insert(self, db, ctx, a, d):
        data.save_security(db, ctx, a, dict(d, coupon_rate=d.get("coupon_rate")))


class Prices(Importer):
    key, title = "prices", "Prices (end-of-day or valuation prices)"
    cap = "edit"
    description = "A price per unit in AUD on a date. Used to value holdings; the latest price on or before a date is used."
    columns = [Col("code", "text", True, example="VAS"), Col("kind", "enum", False, M.SECURITY_KINDS), Col("price_date", "date", True, example="2026-09-30"), Col("price", "qty", True, example="101.38")]
    examples = [dict(code="VAS", price_date="2026-09-30", price="101.38")]

    def natural_key(self, d):
        return f"{d['code'].upper()}|{d.get('kind')}|{d['price_date']}"

    def exists(self, db, ctx, d):
        try:
            s = _sec(db, ctx, d["code"], [d["kind"]] if d.get("kind") else None)
        except InvError:
            return False
        r = db.query(M.InvPrice).filter_by(org_id=ctx.org.id, security_id=s.id, price_date=d["price_date"]).first()
        return r is not None and D(r.price) == D(d["price"])

    def insert(self, db, ctx, a, d):
        s = _sec(db, ctx, d["code"], [d["kind"]] if d.get("kind") else None)
        data.set_price(db, ctx, a, s.id, d["price_date"], d["price"], "import")


# ---------------------------------------------------------------------------------------------------------------------- transactions
_TXN = ("quantity", "price", "amount", "fees", "franked", "unfranked", "franking_credits", "foreign_income", "foreign_tax_paid", "cg_discount_part", "cg_other_part", "tax_deferred", "cost_base_adj", "withholding_tax")


class Transactions(Importer):
    key, title = "transactions", "Transactions (AccFino standard layout)"
    description = "Any transaction type. Buys and sells need quantity and amount (or price); dividends and distributions carry their franking and tax components; see the column help. Identical rows are duplicates: give identical trades different references."
    columns = ([Col("account", "text", True, example="CommSec CDIA"), Col("code", "text", True, example="BHP"), Col("kind", "enum", False, M.SECURITY_KINDS), Col("txn_type", "enum", True, M.TXN_TYPES, "buy"), Col("trade_date", "date", True, example="2025-03-12")] +
               [Col(k, "qty" if k in ("quantity", "price") else "money", False, example=ex, help=h) for k, ex, h in (("quantity", "100", "units; split: new units; bonus: bonus units"), ("price", "46.20", "unit price; split: old units"), ("amount", "4620.00", "AUD excl. fees"), ("fees", "19.95", "brokerage and fees"),
                                                                                                                    ("franked", "", "dividend / distribution"), ("unfranked", "", ""), ("franking_credits", "", "max 30/70 of franked"), ("foreign_income", "", "distributions"), ("foreign_tax_paid", "", ""),
                                                                                                                    ("cg_discount_part", "", "distribution capital gain, discountable"), ("cg_other_part", "", ""), ("tax_deferred", "", "reduces cost base"), ("cost_base_adj", "", "AMIT net amount: + or -"), ("withholding_tax", "", ""))] +
               [Col("reference", "text", False, example="CN-100231", help="contract note / transfer pair"), Col("notes", "text", False)])
    examples = [dict(account="CommSec CDIA", code="BHP", txn_type="buy", trade_date="2025-03-12", quantity="100", price="46.20", amount="4620.00", fees="19.95", reference="CN-100231")]

    def _body(self, db, ctx, d, kinds=None):
        acc, sec = _acc(db, ctx, d["account"]), _sec(db, ctx, d["code"], [d["kind"]] if d.get("kind") else kinds)
        b = {k: d.get(k) for k in _TXN}
        b.update(account_id=acc.id, security_id=sec.id, txn_type=d["txn_type"], trade_date=d["trade_date"], reference=d.get("reference"), notes=d.get("notes"))
        return b

    def natural_key(self, d):
        return _skey("t", {k: d.get(k) for k in ("account", "code", "kind", "txn_type", "trade_date", *_TXN, "reference")})

    def exists(self, db, ctx, d):
        return _txn_exists(db, ctx, self.natural_key(d))

    def insert(self, db, ctx, a, d):
        data.save_txn(db, ctx, a, self._body(db, ctx, d), source="import", source_key=self.natural_key(d))

    def warn(self, d):
        w = []
        if d["txn_type"] in ("buy", "sell") and d.get("quantity") and d.get("price") and d.get("amount") and abs(D(d["quantity"]) * D(d["price"]) - D(d["amount"])) > D("1"):
            w.append("amount differs from quantity x price by more than $1: check the trade")
        return w


class BrokerTrades(Transactions):
    key, title = "broker_trades", "Broker trades (contract notes)"
    description = "Share and ETF trades as brokers report them: side, quantity, price, brokerage and GST. Fees = brokerage + GST (part of the cost base on a buy, deducted from proceeds on a sell)."
    columns = [Col("account", "text", True, example="CommSec CDIA"), Col("code", "text", True, example="BHP"), Col("side", "enum", True, ("buy", "sell"), "buy"), Col("trade_date", "date", True, example="2025-03-12"), Col("quantity", "qty", True, example="100"), Col("price", "qty", True, example="46.20"),
               Col("brokerage", "money", False, example="18.14"), Col("gst", "money", False, example="1.81"), Col("reference", "text", False, example="CN-100231")]
    examples = [dict(account="CommSec CDIA", code="BHP", side="buy", trade_date="2025-03-12", quantity="100", price="46.20", brokerage="18.14", gst="1.81", reference="CN-100231")]

    def natural_key(self, d):
        return _skey("b", {k: d.get(k) for k in ("account", "code", "side", "trade_date", "quantity", "price", "brokerage", "gst", "reference")})

    def insert(self, db, ctx, a, d):
        acc, sec = _acc(db, ctx, d["account"]), _sec(db, ctx, d["code"], ["share", "etf"])
        data.save_txn(db, ctx, a, dict(account_id=acc.id, security_id=sec.id, txn_type=d["side"], trade_date=d["trade_date"], quantity=d["quantity"], price=d["price"], amount=q2(D(d["quantity"]) * D(d["price"])),
                                       fees=q2(D(d.get("brokerage")) + D(d.get("gst"))), reference=d.get("reference")), source="import", source_key=self.natural_key(d))

    def warn(self, d):
        return []


class CryptoExchange(Importer):
    key, title = "crypto_exchange", "Crypto exchange export"
    description = ("Buys, sells, swaps, staking and airdrops, transfers between your wallets and fees, with the AUD value at the time. A swap is a disposal AND an acquisition (both at the AUD market value). Staking and airdrops are income at the AUD value on receipt "
                   "and set the cost base. Transfers between your own wallets are not disposals: give both halves the same reference.")
    columns = [Col("account", "text", True, example="Swyftx"), Col("trade_date", "date", True, example="2026-02-14"), Col("type", "enum", True, ("buy", "sell", "swap", "staking", "airdrop", "transfer_out", "transfer_in", "fee"), "buy"),
               Col("asset", "text", True, example="BTC"), Col("quantity", "qty", True, example="0.15"), Col("aud_value", "money", False, example="9900.00", help="AUD value excl. fee (buy cost, sale proceeds, swap market value, income value)"),
               Col("fee_aud", "money", False, example="35.00"), Col("to_asset", "text", False, example="ETH", help="swap: asset received"), Col("to_quantity", "qty", False, example="3.2", help="swap: quantity received"),
               Col("reference", "text", False, example="TX-88123", help="exchange id / tx hash / transfer pair")]
    examples = [dict(account="Swyftx", trade_date="2026-02-14", type="buy", asset="BTC", quantity="0.15", aud_value="9900.00", fee_aud="35.00", reference="ORD-1")]

    def natural_key(self, d):
        return _skey("c", {k: d.get(k) for k in ("account", "trade_date", "type", "asset", "quantity", "aud_value", "fee_aud", "to_asset", "to_quantity", "reference")})

    def exists(self, db, ctx, d):
        return _txn_exists(db, ctx, self.natural_key(d))

    def insert(self, db, ctx, a, d):
        acc, sec, t = _acc(db, ctx, d["account"]), _sec(db, ctx, d["asset"], ["crypto"]), d["type"]
        key, ref = self.natural_key(d), d.get("reference")
        common = dict(account_id=acc.id, trade_date=d["trade_date"], reference=ref)
        if t in ("buy", "sell"):
            data.save_txn(db, ctx, a, dict(common, security_id=sec.id, txn_type=t, quantity=d["quantity"], amount=d.get("aud_value"), fees=d.get("fee_aud")), source="import", source_key=key)
        elif t in ("staking", "airdrop"):
            data.save_txn(db, ctx, a, dict(common, security_id=sec.id, txn_type="income_in_kind", quantity=d["quantity"], amount=d.get("aud_value"), fees=d.get("fee_aud"), notes=t), source="import", source_key=key)
        elif t in ("transfer_out", "transfer_in"):
            data.save_txn(db, ctx, a, dict(common, security_id=sec.id, txn_type=t, quantity=d["quantity"], amount=d.get("aud_value"), fees=d.get("fee_aud")), source="import", source_key=key)
        elif t == "fee":
            data.save_txn(db, ctx, a, dict(common, security_id=sec.id, txn_type="fee", amount=d.get("aud_value") or d.get("fee_aud")), source="import", source_key=key)
        else:
            if not d.get("to_asset") or not d.get("to_quantity") or not d.get("aud_value"):
                raise InvError("A swap needs to_asset, to_quantity and aud_value (the AUD market value at the time)")
            to = _sec(db, ctx, d["to_asset"], ["crypto"])
            data.save_txn(db, ctx, a, dict(common, security_id=sec.id, txn_type="sell", quantity=d["quantity"], amount=d["aud_value"], fees=d.get("fee_aud"), notes=f"Swap to {to.code}"), source="import", source_key=key)
            data.save_txn(db, ctx, a, dict(common, security_id=to.id, txn_type="buy", quantity=d["to_quantity"], amount=d["aud_value"], notes=f"Swap from {sec.code}"), source="import", source_key=key + "b")

    def warn(self, d):
        return ["No AUD value given: a buy or sale needs it for the cost base and proceeds"] if d["type"] in ("buy", "sell") and not d.get("aud_value") else []


class FundDistributions(Importer):
    key, title = "fund_distributions", "Fund and ETF distributions (from distribution / AMMA statements)"
    description = "One row per distribution with its tax components. Tax-deferred amounts reduce the cost base; the AMIT cost base net amount (from an AMMA statement) increases (+) or decreases (-) it."
    columns = [Col("account", "text", True, example="Vanguard Personal"), Col("code", "text", True, example="VAS"), Col("pay_date", "date", True, example="2026-07-17"), Col("cash_distribution", "money", True, example="640.00"), Col("franked", "money", False, example="410.00"),
               Col("unfranked", "money", False, example="20.00"), Col("franking_credits", "money", False, example="175.71"), Col("foreign_income", "money", False, example="0"), Col("foreign_tax_paid", "money", False, example="0"), Col("cg_discount_part", "money", False, example="120.00"),
               Col("cg_other_part", "money", False, example="0"), Col("tax_deferred", "money", False, example="90.00"), Col("amit_cost_base_net", "money", False, example="-5.00", help="+ increase / - decrease"), Col("reference", "text", False, example="AMMA FY26")]
    examples = [dict(account="Vanguard Personal", code="VAS", pay_date="2026-07-17", cash_distribution="640.00", franked="410.00", unfranked="20.00", franking_credits="175.71", cg_discount_part="120.00", tax_deferred="90.00", reference="Q4 FY26")]

    def natural_key(self, d):
        return _skey("f", {k: d.get(k) for k in ("account", "code", "pay_date", "cash_distribution", "franked", "unfranked", "franking_credits", "cg_discount_part", "tax_deferred", "amit_cost_base_net", "reference")})

    def exists(self, db, ctx, d):
        return _txn_exists(db, ctx, self.natural_key(d))

    def insert(self, db, ctx, a, d):
        acc, sec = _acc(db, ctx, d["account"]), _sec(db, ctx, d["code"], ["etf", "managed_fund", "share"])
        data.save_txn(db, ctx, a, dict(account_id=acc.id, security_id=sec.id, txn_type="distribution", trade_date=d["pay_date"], amount=d["cash_distribution"], franked=d.get("franked"), unfranked=d.get("unfranked"), franking_credits=d.get("franking_credits"),
                                       foreign_income=d.get("foreign_income"), foreign_tax_paid=d.get("foreign_tax_paid"), cg_discount_part=d.get("cg_discount_part"), cg_other_part=d.get("cg_other_part"), tax_deferred=d.get("tax_deferred"),
                                       cost_base_adj=d.get("amit_cost_base_net"), reference=d.get("reference")), source="import", source_key=self.natural_key(d))


# ---------------------------------------------------------------------------------------------------------------------- property and wealth
class Properties(Importer):
    key, title = "properties", "Properties"
    cap = "edit"
    description = "The property register: purchase, cost base elements, use and (if sold) the sale. Dates are the CONTRACT dates."
    columns = [Col("name", "text", True, example="14 Wattle Rd, Manly"), Col("address", "text", False, example="14 Wattle Rd"), Col("suburb", "text", False, example="Manly"), Col("state", "text", False, example="NSW"), Col("postcode", "text", False, example="2095"),
               Col("property_type", "enum", False, M.PROPERTY_TYPES, "house"), Col("use", "enum", False, M.PROPERTY_USES, "investment"), Col("ownership_pct", "money", False, example="100"), Col("contract_date", "date", True, example="2018-09-14"),
               Col("settlement_date", "date", False, example="2018-11-02"), Col("purchase_price", "money", True, example="1150000"), Col("stamp_duty", "money", False, example="46000"), Col("legal_costs", "money", False, example="2200"),
               Col("other_acq_costs", "money", False, example="1100"), Col("depreciating_assets_value", "money", False, example="0"), Col("construction_cost", "money", False, example="260000"), Col("construction_date", "date", False, example="2012-01-01"),
               Col("first_income_date", "date", False, example="2018-12-01"), Col("loan", "text", False, example="Manly loan", help="Name of a liability (import liabilities first)"), Col("main_residence_from", "date", False), Col("main_residence_until", "date", False), Col("sale_contract_date", "date", False), Col("sale_price", "money", False), Col("selling_costs", "money", False)]
    examples = [dict(name="14 Wattle Rd, Manly", suburb="Manly", state="NSW", postcode="2095", use="investment", contract_date="2018-09-14", purchase_price="1150000", stamp_duty="46000", legal_costs="2200")]

    def natural_key(self, d):
        return d["name"].strip().lower()

    def exists(self, db, ctx, d):
        return db.query(M.InvProperty.id).filter_by(org_id=ctx.org.id, name=d["name"]).first() is not None

    def insert(self, db, ctx, a, d):
        loan_id = None
        if d.get("loan"):
            li = db.query(M.InvLiability).filter_by(org_id=ctx.org.id, name=d["loan"]).first()
            if li is None:
                raise InvError(f"Loan '{d['loan']}' not found: import the liabilities first")
            loan_id = li.id
        property_svc.save(db, ctx, a, dict(d, ownership_pct=d.get("ownership_pct") or 100, loan_liability_id=loan_id))


class PropertyEntries(Importer):
    key, title = "property_entries", "Property income, expenses and capital items"
    cap = "edit"
    description = "Rent received, running costs, loan interest, capital improvements and annual capital works / depreciation claimed. Amounts are positive; the kind says which way they go."
    columns = [Col("property", "text", True, example="14 Wattle Rd, Manly"), Col("entry_date", "date", True, example="2026-07-31"), Col("kind", "enum", True, M.ENTRY_KINDS, "rent_income"), Col("category", "enum", False, M.EXPENSE_CATEGORIES, "agent_fees", "required for an expense"),
               Col("amount", "money", True, example="2870.00"), Col("description", "text", False, example="July rent"), Col("reference", "text", False, example="RENT-2026-07")]
    examples = [dict(property="14 Wattle Rd, Manly", entry_date="2026-07-31", kind="rent_income", amount="2870.00", description="July rent", reference="RENT-2026-07")]

    def natural_key(self, d):
        return _skey("p", {k: d.get(k) for k in ("property", "entry_date", "kind", "category", "amount", "description", "reference")})

    def exists(self, db, ctx, d):
        return db.query(M.InvPropertyEntry.id).filter_by(org_id=ctx.org.id, source_key=self.natural_key(d)).first() is not None

    def insert(self, db, ctx, a, d):
        p = db.query(M.InvProperty).filter_by(org_id=ctx.org.id, name=d["property"]).first()
        if p is None:
            raise InvError(f"Property '{d['property']}' not found: import the properties first")
        property_svc.save_entry(db, ctx, a, p.id, d, source="import", source_key=self.natural_key(d))


class Liabilities(Importer):
    key, title = "liabilities", "Liabilities (loans, margin loans, cards)"
    cap = "edit"
    description = "Loans not already in the ledger. Balances come from the valuations file."
    columns = [Col("name", "text", True, example="Manly investment loan"), Col("kind", "enum", False, M.LIABILITY_KINDS, "mortgage"), Col("lender", "text", False, example="CBA"), Col("limit_amount", "money", False, example="520000"), Col("interest_rate", "percent", False, example="6.19", help="% a year")]
    examples = [dict(name="Manly investment loan", kind="investment_loan", lender="CBA", limit_amount="520000", interest_rate="6.19")]

    def natural_key(self, d):
        return d["name"].strip().lower()

    def exists(self, db, ctx, d):
        return db.query(M.InvLiability.id).filter_by(org_id=ctx.org.id, name=d["name"]).first() is not None

    def insert(self, db, ctx, a, d):
        wealth.save_liability(db, ctx, a, d)


class OtherAssets(Importer):
    key, title = "other_assets", "Other assets (vehicles, collectables, super, business interests)"
    cap = "edit"
    description = "Assets that are not investments or property. Values come from the valuations file."
    columns = [Col("name", "text", True, example="2023 Toyota Hilux"), Col("kind", "enum", False, M.OTHER_ASSET_KINDS, "vehicle"), Col("notes", "text", False)]
    examples = [dict(name="2023 Toyota Hilux", kind="vehicle")]

    def natural_key(self, d):
        return d["name"].strip().lower()

    def exists(self, db, ctx, d):
        return db.query(M.InvOtherAsset.id).filter_by(org_id=ctx.org.id, name=d["name"]).first() is not None

    def insert(self, db, ctx, a, d):
        wealth.save_other_asset(db, ctx, a, d)


class Valuations(Importer):
    key, title = "valuations", "Valuations and balances (property, other assets, liabilities)"
    cap = "edit"
    description = "A dated value for a property or other asset, or a dated balance for a liability, matched by name."
    columns = [Col("owner_type", "enum", True, M.VALUATION_OWNERS, "property"), Col("name", "text", True, example="14 Wattle Rd, Manly"), Col("as_at", "date", True, example="2026-06-30"), Col("value", "money", True, example="1480000"), Col("basis", "text", False, example="Agent appraisal")]
    examples = [dict(owner_type="property", name="14 Wattle Rd, Manly", as_at="2026-06-30", value="1480000", basis="Agent appraisal")]

    def _owner(self, db, ctx, d):
        model = {"property": M.InvProperty, "other_asset": M.InvOtherAsset, "liability": M.InvLiability}[d["owner_type"]]
        o = db.query(model).filter_by(org_id=ctx.org.id, name=d["name"]).first()
        if o is None:
            raise InvError(f"{d['owner_type'].replace('_', ' ')} '{d['name']}' not found: import it first")
        return o

    def exists(self, db, ctx, d):
        try:
            o = self._owner(db, ctx, d)
        except InvError:
            return False
        r = db.query(M.InvValuation).filter_by(org_id=ctx.org.id, owner_type=d["owner_type"], owner_id=o.id, as_at=d["as_at"]).first()
        return r is not None and D(r.value) == q2(d["value"])

    def insert(self, db, ctx, a, d):
        valuations.add(db, ctx, a, d["owner_type"], self._owner(db, ctx, d).id, d["as_at"], d["value"], d.get("basis") or "", "import")


class SettingsImp(Importer):
    key, title = "settings", "Investment settings"
    cap = "config"
    description = "ONE row: the parcel (CGT) method, who holds the investments (this drives the CGT discount) and, optionally, the ledger account codes used when posting. If a file has several rows they are applied in order and the last one stays. Needs the configuration permission."
    columns = [Col("cgt_method", "enum", True, M.CGT_METHODS, "fifo", "fifo is the default; lifo and hifo need records that support them"), Col("holder", "enum", True, M.HOLDERS, "individual", "individual / trust 50% discount, super one third, company none"),
               Col("asset_code", "text", False, example="1640", help="Investments at cost"), Col("dividend_code", "text", False, example="4281", help="Dividend and distribution income"), Col("interest_code", "text", False, example="4282"),
               Col("gain_code", "text", False, example="4283", help="Realised gain"), Col("loss_code", "text", False, example="6490", help="Realised loss"), Col("fees_code", "text", False, example="6491", help="Brokerage and fees")]
    examples = [dict(cgt_method="fifo", holder="individual", asset_code="1640", dividend_code="4281", interest_code="4282", gain_code="4283", loss_code="6490", fees_code="6491")]

    def natural_key(self, d):
        return "|".join(str(d.get(c.name) or "") for c in self.columns)                  # rows are compared by content, so a valid row is never called the duplicate of a rejected one

    def _body(self, d):
        lm = {k: dict(code=d[f"{k}_code"]) for k in ("asset", "dividend", "interest", "gain", "loss", "fees") if d.get(f"{k}_code")}
        return dict(cgt_method=d["cgt_method"], holder=d["holder"], **({"ledger_map": lm} if lm else {}))

    def exists(self, db, ctx, d):
        cur = data.settings_dict(data.get_settings(db, ctx))
        same_codes = all(cur["ledger_map"][k]["code"] == d[f"{k}_code"] for k in ("asset", "dividend", "interest", "gain", "loss", "fees") if d.get(f"{k}_code"))
        return cur["cgt_method"] == d["cgt_method"] and cur["holder"] == d["holder"] and same_codes

    def insert(self, db, ctx, a, d):
        data.save_settings(db, ctx, a, self._body(d))


class NetworthSnapshots(Importer):
    key, title = "networth_snapshots", "Net worth history (snapshots)"
    cap = "edit"
    description = "Net worth figures for past dates (month-ends or each 30 June) from statements or an earlier system. Where AccFino holds no records for a month, the history chart uses the snapshot taken in it. A snapshot on a date already saved replaces it."
    columns = [Col("as_at", "date", True, example="2025-06-30"), Col("total_assets", "money", True, example="1850000.00"), Col("total_liabilities", "money", True, example="1020000.00"),
               Col("net_worth", "money", True, example="830000.00", help="Must equal total_assets less total_liabilities"), Col("note", "text", False, example="Per accountant's June 2025 statement of position")]
    examples = [dict(as_at="2025-06-30", total_assets="1850000.00", total_liabilities="1020000.00", net_worth="830000.00", note="Per accountant statement of position")]

    def natural_key(self, d):
        return str(d["as_at"])

    def exists(self, db, ctx, d):
        s = db.query(M.InvSnapshot).filter_by(org_id=ctx.org.id, as_at=d["as_at"]).first()
        return s is not None and (s.total_assets, s.total_liabilities, s.net_worth) == (q2(d["total_assets"]), q2(d["total_liabilities"]), q2(d["net_worth"]))

    def insert(self, db, ctx, a, d):
        wealth.import_snapshot(db, ctx, a, d["as_at"], d["total_assets"], d["total_liabilities"], d["net_worth"], d.get("note") or "")


for _i in (SettingsImp(), Accounts(), Securities(), Prices(), Transactions(), BrokerTrades(), CryptoExchange(), FundDistributions(), Properties(), PropertyEntries(), Liabilities(), OtherAssets(), Valuations(), NetworthSnapshots()):
    reg(_i)


# ---------------------------------------------------------------------------------------------------------------------- pipeline
def catalogue() -> List[dict]:
    return [dict(key=i.key, title=i.title, description=i.description, capability=i.cap, columns=[dict(name=c.name, kind=c.kind, required=c.required, enum=list(c.enum), example=c.example, help=c.help) for c in i.columns]) for i in IMPORTERS.values()]


def _imp(key):
    if key not in IMPORTERS:
        raise core.NotFound("Import dataset")
    return IMPORTERS[key]


def template_csv(key: str) -> str:
    i = _imp(key)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c.name for c in i.columns])
    for ex in i.examples:
        w.writerow([ex.get(c.name, "") for c in i.columns])
    return buf.getvalue()


def _grid(raw: bytes):
    if not raw or not raw.strip():
        raise InvError("The file is empty")
    if len(raw) > MAX_BYTES:
        raise InvError(f"The file is larger than {MAX_BYTES // 1_000_000} MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise InvError("The file is not text (use a CSV saved as UTF-8)")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = max((",", ";", "\t"), key=first.count)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise InvError("The file needs a header row and at least one data row")
    if len(rows) - 1 > MAX_ROWS:
        raise InvError(f"The file has more than {MAX_ROWS} data rows: split it")
    return [canon(h) for h in rows[0]], rows[1:]


def _dry(db, fn) -> Optional[str]:
    sp = db.begin_nested()
    try:
        fn()
        return None
    except InvError as e:
        return e.message
    except Exception as e:
        return f"{type(e).__name__}: {str(getattr(e, 'orig', e))[:160]}"
    finally:
        sp.rollback()


def _display(d):
    return {k: (v.isoformat() if isinstance(v, date) else str(v)) for k, v in d.items() if v not in (None, "")}


def _run(db, ctx, a, imp: Importer, headers, body, raw):
    known = {c.name: c for c in imp.columns}
    missing = [c.name for c in imp.columns if c.required and c.name not in headers]
    out = dict(total=len(body), ok=0, duplicates=0, errors=0, warnings=0, file_sha256=hashlib.sha256(raw).hexdigest(), _rows=[], missing=missing)
    if missing:
        out["file_error"] = "Required column(s) missing: " + ", ".join(missing)
        return out
    idx = {h: i for i, h in enumerate(headers) if h in known}
    seen = {}
    for n, r in enumerate(body, start=2):
        row = dict(line=n, status="ok", messages=[], data=None, _d=None)
        d, errs = {}, []
        for c in imp.columns:
            try:
                d[c.name] = coerce(c, r[idx[c.name]] if c.name in idx and idx[c.name] < len(r) else "")
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
                if imp.exists(db, ctx, d):
                    row["status"], row["messages"] = "duplicate", [dict(level="info", text="Already in the database: skipped")]
                else:
                    row["_d"] = d
        out["_rows"].append(row)
    # Validate the rows IN ORDER inside ONE outer savepoint that is always rolled back: each valid row stays applied for the rows after it (a buy must be visible to the sale that follows it in the
    # same file), an invalid row is undone on its own, and nothing is ever kept.
    outer = db.begin_nested()
    try:
        for row in out["_rows"]:
            if row["status"] == "ok" and row["_d"] is not None:
                inner = db.begin_nested()
                try:
                    imp.insert(db, ctx, a, row["_d"])
                    inner.commit()
                    row["messages"] += [dict(level="warning", text=w) for w in imp.warn(row["_d"])]
                except Exception as e:
                    inner.rollback()
                    row["status"] = "error"
                    row["messages"] = [dict(level="error", text=e.message if isinstance(e, InvError) else f"{type(e).__name__}: {str(getattr(e, 'orig', e))[:160]}")]
    finally:
        outer.rollback()
    for row in out["_rows"]:
        out["ok"] += row["status"] == "ok"
        out["duplicates"] += row["status"] == "duplicate"
        out["errors"] += row["status"] == "error"
        out["warnings"] += any(m["level"] == "warning" for m in row["messages"])
    return out


def preview(db, ctx, a, key: str, raw: bytes) -> dict:
    imp = _imp(key)
    a.require(imp.cap)
    headers, body = _grid(raw)
    res = _run(db, ctx, a, imp, headers, body, raw)
    known = {c.name for c in imp.columns}
    out = dict(module=key, title=imp.title, file_sha256=res["file_sha256"], total=res["total"], missing_columns=res["missing"], unknown_columns=[h for h in headers if h and h not in known], ok=res["ok"], duplicates=res["duplicates"],
               errors=res["errors"], warnings=res["warnings"], rows=[])
    if res.get("file_error"):
        out.update(file_error=res["file_error"] + ". Download the CSV template for the exact layout.", can_commit=False)
        return out
    out["rows"] = [{k: v for k, v in r.items() if k != "_d"} for r in res["_rows"]]
    out["can_commit"] = out["ok"] > 0
    return out


def commit(db, ctx, a, key: str, raw: bytes, mode: str = "valid_only") -> dict:
    imp = _imp(key)
    a.require(imp.cap)
    if mode not in ("valid_only", "all_or_nothing"):
        raise InvError("mode must be valid_only or all_or_nothing")
    headers, body = _grid(raw)
    pv = _run(db, ctx, a, imp, headers, body, raw)
    if pv.get("file_error"):
        raise InvError(pv["file_error"])
    if mode == "all_or_nothing" and pv["errors"]:
        raise core.Conflict(f"{pv['errors']} row(s) have errors: nothing was imported (mode: all or nothing). Fix the file or import the valid rows only.", "has_errors")
    imported, failed = 0, []
    for row in pv["_rows"]:
        if row["status"] != "ok":
            continue
        sp = db.begin_nested()
        try:
            imp.insert(db, ctx, a, row["_d"])
            sp.commit()
            imported += 1
        except Exception as e:
            sp.rollback()
            failed.append(dict(line=row["line"], error=(e.message if isinstance(e, InvError) else f"{type(e).__name__}: {str(getattr(e, 'orig', e))[:160]}")))
    core.record(db, ctx, f"import.{key}", "inv_import", key, f"CSV import '{imp.title}': {imported} imported, {pv['duplicates']} duplicate(s) skipped, {pv['errors']} rejected, {len(failed)} failed (file sha256 {pv['file_sha256'][:12]})", None,
                dict(mode=mode, imported=imported, duplicates=pv["duplicates"], rejected=pv["errors"], failed=len(failed), sha256=pv["file_sha256"]))
    for r in pv["_rows"]:
        r.pop("_d", None)
    return dict(module=key, title=imp.title, mode=mode, imported=imported, skipped_duplicates=pv["duplicates"], rejected=pv["errors"], failed=failed, total=pv["total"], file_sha256=pv["file_sha256"], rows=pv["_rows"], warnings=pv["warnings"])
