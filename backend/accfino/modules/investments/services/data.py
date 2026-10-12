"""Settings, accounts, securities, prices and the transaction register. Business rules live here; the API only authorises and calls."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from accfino.modules.investments.engine import lots as LE
from accfino.modules.investments.engine.money import ZERO, D, q2, q8
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core
from accfino.modules.investments.services.core import Access, Conflict, InvError, NotFound

DEFAULT_LEDGER_MAP = dict(asset=dict(code="1640", name="Investments at cost", type="non_current_asset", key="inv_asset"), dividend=dict(code="4281", name="Dividend and distribution income", type="other_income", key="inv_dividend_income"),
                          interest=dict(code="4282", name="Investment interest income", type="other_income", key="inv_interest_income"), gain=dict(code="4283", name="Realised gain on investments", type="other_income", key="inv_gain"),
                          loss=dict(code="6490", name="Realised loss on investments", type="other_expense", key="inv_loss"), fees=dict(code="6491", name="Brokerage and investment fees", type="expense", key="inv_fees"))


# ---------------------------------------------------------------------------------------------------------------------- settings
def get_settings(db, ctx) -> M.InvSettings:
    s = db.get(M.InvSettings, ctx.org.id)
    if s is None:
        s = M.InvSettings(org_id=ctx.org.id, cgt_method="fifo", holder="individual", ledger_map=None)
        db.add(s)
        db.flush()
    return s


def settings_dict(s: M.InvSettings) -> dict:
    return dict(cgt_method=s.cgt_method, holder=s.holder, ledger_map=s.ledger_map or DEFAULT_LEDGER_MAP)


def save_settings(db, ctx, a: Access, body: dict) -> M.InvSettings:
    a.require("config")
    s = get_settings(db, ctx)
    before = settings_dict(s)
    if "cgt_method" in body:
        if body["cgt_method"] not in M.CGT_METHODS:
            raise InvError(f"cgt_method must be one of {', '.join(M.CGT_METHODS)}")
        s.cgt_method = body["cgt_method"]
    if "holder" in body:
        if body["holder"] not in M.HOLDERS:
            raise InvError(f"holder must be one of {', '.join(M.HOLDERS)}")
        s.holder = body["holder"]
    if "ledger_map" in body and body["ledger_map"]:
        lm = dict(DEFAULT_LEDGER_MAP)
        for k, v in body["ledger_map"].items():
            if k in lm and isinstance(v, dict) and v.get("code"):
                code = str(v["code"]).strip()
                if not __import__("re").fullmatch(r"[A-Za-z0-9._-]{1,12}", code):
                    raise InvError(f"The ledger account code for '{k}' must be 1 to 12 letters, digits, dots, dashes or underscores")
                lm[k] = dict(lm[k], code=code)
        s.ledger_map = lm
    core.record(db, ctx, "settings.save", "inv_settings", ctx.org.id, f"Method {s.cgt_method}, holder {s.holder}", before, settings_dict(s))
    return s


# ---------------------------------------------------------------------------------------------------------------------- accounts
def acc_dict(x: M.InvAccount) -> dict:
    return dict(id=x.id, name=x.name, kind=x.kind, institution=x.institution, identifier=x.identifier, holder_note=x.holder_note, active=x.active)


def accounts(db, ctx, active_only=False):
    q = db.query(M.InvAccount).filter_by(org_id=ctx.org.id)
    if active_only:
        q = q.filter_by(active=True)
    return [acc_dict(x) for x in q.order_by(M.InvAccount.name)]


def save_account(db, ctx, a: Access, body: dict, aid: Optional[int] = None) -> M.InvAccount:
    a.require("edit")
    name = (body.get("name") or "").strip()
    if not name:
        raise InvError("name is required")
    kind = body.get("kind") or "broker"
    if kind not in M.ACCOUNT_KINDS:
        raise InvError(f"kind must be one of {', '.join(M.ACCOUNT_KINDS)}")
    ident = (body.get("identifier") or "").strip()
    if ident.replace(" ", "").isdigit() and len(ident.replace(" ", "")) in (8, 9):
        raise InvError("Do not enter a Tax File Number. Record only the last digits of a HIN or a wallet label")
    x = db.query(M.InvAccount).filter_by(org_id=ctx.org.id, id=aid).first() if aid else M.InvAccount(org_id=ctx.org.id)
    if aid and x is None:
        raise NotFound("Account")
    dup = db.query(M.InvAccount).filter(M.InvAccount.org_id == ctx.org.id, func.lower(M.InvAccount.name) == name.lower(), M.InvAccount.id != (x.id or 0)).first()
    if dup:
        raise Conflict(f"An account named '{name}' already exists")
    before = acc_dict(x) if aid else None
    x.name, x.kind, x.institution, x.identifier, x.holder_note = name[:120], kind, (body.get("institution") or None), ident or None, (body.get("holder_note") or None)
    if "active" in body:
        x.active = bool(body["active"])
    if not aid:
        db.add(x)
    db.flush()
    core.record(db, ctx, "account.save", "inv_account", x.id, f"Account '{x.name}' ({x.kind})", before, acc_dict(x))
    return x


# ---------------------------------------------------------------------------------------------------------------------- securities
def sec_dict(s: M.InvSecurity) -> dict:
    return dict(id=s.id, kind=s.kind, code=s.code, name=s.name, exchange=s.exchange, isin=s.isin, asset_class=s.asset_class, sector=s.sector, country=s.country, currency=s.currency, mer_pct=None if s.mer_pct is None else str(s.mer_pct),
                amit=s.amit, face_value=None if s.face_value is None else str(s.face_value), coupon_rate=None if s.coupon_rate is None else str(s.coupon_rate), coupon_freq=s.coupon_freq,
                issue_date=core.plain(s.issue_date), maturity_date=core.plain(s.maturity_date), day_count=s.day_count, active=s.active)


DEFAULT_CLASS = {"share": "au_equity", "etf": "au_equity", "crypto": "crypto", "managed_fund": "au_equity", "bond": "fixed_interest", "term_deposit": "cash"}


def securities(db, ctx, kind="", q="", active_only=False):
    qs = db.query(M.InvSecurity).filter_by(org_id=ctx.org.id)
    if kind:
        qs = qs.filter(M.InvSecurity.kind.in_(kind.split(",")))
    if active_only:
        qs = qs.filter_by(active=True)
    rows = [sec_dict(s) for s in qs.order_by(M.InvSecurity.code)]
    if q:
        t = q.strip().lower()
        rows = [r for r in rows if t in r["code"].lower() or t in r["name"].lower() or t in (r["isin"] or "").lower()]
    return rows


def get_security(db, ctx, sid) -> M.InvSecurity:
    s = db.query(M.InvSecurity).filter_by(org_id=ctx.org.id, id=sid).first()
    if s is None:
        raise NotFound("Security")
    return s


def save_security(db, ctx, a: Access, body: dict, sid: Optional[int] = None) -> M.InvSecurity:
    a.require("edit")
    kind = body.get("kind")
    if kind not in M.SECURITY_KINDS:
        raise InvError(f"kind must be one of {', '.join(M.SECURITY_KINDS)}")
    code = (body.get("code") or "").strip().upper()
    name = (body.get("name") or "").strip()
    if not code or not name:
        raise InvError("code and name are required")
    cls = body.get("asset_class") or DEFAULT_CLASS[kind]
    if cls not in M.ASSET_CLASSES:
        raise InvError(f"asset_class must be one of {', '.join(M.ASSET_CLASSES)}")
    isin = (body.get("isin") or "").strip().upper() or None
    if isin and (len(isin) != 12 or not isin[:2].isalpha() or not isin[2:].isalnum()):
        raise InvError("isin must be 12 characters: a 2-letter country code, 9 letters or digits and a check digit")
    s = db.query(M.InvSecurity).filter_by(org_id=ctx.org.id, id=sid).first() if sid else M.InvSecurity(org_id=ctx.org.id)
    if sid and s is None:
        raise NotFound("Security")
    dup = db.query(M.InvSecurity).filter(M.InvSecurity.org_id == ctx.org.id, M.InvSecurity.kind == kind, M.InvSecurity.code == code, M.InvSecurity.id != (s.id or 0)).first()
    if dup:
        raise Conflict(f"{kind} {code} already exists")
    if sid and s.kind != kind and db.query(M.InvTransaction.id).filter_by(org_id=ctx.org.id, security_id=sid).first():
        raise Conflict("The kind of a security with transactions cannot change")
    fv = core.num(body.get("face_value"), "face_value")
    cr = core.num(body.get("coupon_rate"), "coupon_rate", places=8)
    cf = body.get("coupon_freq")
    mat, iss = core.parse_date(body.get("maturity_date"), "maturity_date"), core.parse_date(body.get("issue_date"), "issue_date")
    if kind in ("bond", "term_deposit"):
        if not mat:
            raise InvError("maturity_date is required for a bond or term deposit")
        if iss and mat <= iss:
            raise InvError("maturity_date must be after issue_date")
        if kind == "bond":
            if not fv or fv <= 0:
                raise InvError("face_value is required for a bond")
            if cr is None or cr > D("0.5"):
                raise InvError("coupon_rate is required for a bond and is a fraction (0.045 means 4.5%)")
            if int(cf or 0) not in (1, 2, 4, 12):
                raise InvError("coupon_freq must be 1, 2, 4 or 12 payments a year")
    dc = body.get("day_count") or "act/act"
    if dc not in ("act/act", "act/365"):
        raise InvError("day_count must be act/act or act/365")
    mer = core.num(body.get("mer_pct"), "mer_pct", places=8)
    if mer is not None and mer > 10:
        raise InvError("mer_pct is a percentage a year (0.20 means 0.20%)")
    before = sec_dict(s) if sid else None
    s.kind, s.code, s.name, s.isin, s.asset_class = kind, code[:24], name[:160], isin, cls
    s.exchange, s.sector, s.country, s.currency = (body.get("exchange") or None), (body.get("sector") or None), (body.get("country") or None), (body.get("currency") or "AUD").upper()[:3]
    s.mer_pct, s.amit, s.face_value, s.coupon_rate, s.coupon_freq = mer, bool(body.get("amit")), fv, cr, int(cf) if cf else None
    s.issue_date, s.maturity_date, s.day_count = iss, mat, dc
    if "active" in body:
        s.active = bool(body["active"])
    if not sid:
        db.add(s)
    db.flush()
    core.record(db, ctx, "security.save", "inv_security", s.id, f"{kind} {s.code} {s.name}", before, sec_dict(s))
    return s


# ---------------------------------------------------------------------------------------------------------------------- prices
def set_price(db, ctx, a: Access, security_id: int, price_date, price, source="manual") -> M.InvPrice:
    a.require("edit")
    get_security(db, ctx, security_id)
    d = core.parse_date(price_date, "price_date")
    if d is None or d > date.today():
        raise InvError("price_date is required and cannot be in the future")
    p = core.num(price, "price", required=True, places=8)
    row = db.query(M.InvPrice).filter_by(org_id=ctx.org.id, security_id=security_id, price_date=d).first()
    before = None if row is None else dict(price=str(row.price))
    if row is None:
        row = M.InvPrice(org_id=ctx.org.id, security_id=security_id, price_date=d, price=p, source=source)
        db.add(row)
    else:
        row.price, row.source = p, source
    db.flush()
    core.record(db, ctx, "price.set", "inv_security", security_id, f"Price {p} on {d}", before, dict(price=str(p), date=d))
    return row


def prices(db, ctx, security_id: int, limit=500):
    return [dict(id=r.id, date=r.price_date.isoformat(), price=str(r.price), source=r.source) for r in db.query(M.InvPrice).filter_by(org_id=ctx.org.id, security_id=security_id).order_by(M.InvPrice.price_date.desc()).limit(limit)]


def delete_price(db, ctx, a: Access, price_id: int):
    a.require("edit")
    r = db.query(M.InvPrice).filter_by(org_id=ctx.org.id, id=price_id).first()
    if r is None:
        raise NotFound("Price")
    core.record(db, ctx, "price.delete", "inv_security", r.security_id, f"Price {r.price} on {r.price_date} deleted", None, None)
    db.delete(r)
    db.flush()


def price_map(db, ctx, as_at: date) -> dict:
    """security_id -> (price, price_date): the latest price on or before as_at."""
    sub = db.query(M.InvPrice.security_id, func.max(M.InvPrice.price_date).label("d")).filter(M.InvPrice.org_id == ctx.org.id, M.InvPrice.price_date <= as_at).group_by(M.InvPrice.security_id).subquery()
    rows = db.query(M.InvPrice).join(sub, (M.InvPrice.security_id == sub.c.security_id) & (M.InvPrice.price_date == sub.c.d)).filter(M.InvPrice.org_id == ctx.org.id)
    return {r.security_id: (r.price, r.price_date) for r in rows}


# ---------------------------------------------------------------------------------------------------------------------- transactions
FEE_LIKE = ("fee",)
NEEDS_QTY = ("buy", "sell", "drp", "bonus", "income_in_kind", "transfer_out", "transfer_in")
INCOME_TYPES = ("dividend", "distribution", "interest", "drp")
MAX_CREDIT_RATIO = Decimal("30") / Decimal("70")          # franking credit can be at most 30/70 of the franked amount (30% company tax rate)


def txn_dict(t: M.InvTransaction, sec=None, acc=None) -> dict:
    return dict(id=t.id, account_id=t.account_id, account=getattr(acc, "name", None), security_id=t.security_id, code=getattr(sec, "code", None), security=getattr(sec, "name", None), kind=getattr(sec, "kind", None), trade_date=t.trade_date.isoformat(),
                txn_type=t.txn_type, quantity=str(t.quantity), price=None if t.price is None else str(t.price), amount=str(t.amount), fees=str(t.fees), franked=str(t.franked), unfranked=str(t.unfranked),
                franking_credits=str(t.franking_credits), foreign_income=str(t.foreign_income), foreign_tax_paid=str(t.foreign_tax_paid), cg_discount_part=str(t.cg_discount_part), cg_other_part=str(t.cg_other_part),
                tax_deferred=str(t.tax_deferred), cost_base_adj=str(t.cost_base_adj), withholding_tax=str(t.withholding_tax), lot_ref=t.lot_ref, reference=t.reference, notes=t.notes, source=t.source, voided=t.voided,
                void_reason=t.void_reason, linked_journal_id=t.linked_journal_id)


def _clean_txn(db, ctx, body: dict, existing: Optional[M.InvTransaction]) -> dict:
    typ = body.get("txn_type")
    if typ not in M.TXN_TYPES:
        raise InvError(f"txn_type must be one of {', '.join(M.TXN_TYPES)}")
    acc = db.query(M.InvAccount).filter_by(org_id=ctx.org.id, id=body.get("account_id")).first()
    if acc is None:
        raise InvError("Choose an account")
    sec = db.query(M.InvSecurity).filter_by(org_id=ctx.org.id, id=body.get("security_id")).first()
    if sec is None:
        raise InvError("Choose a security")
    d = core.parse_date(body.get("trade_date"), "trade_date")
    if d is None:
        raise InvError("trade_date is required")
    if d > date.today():
        raise InvError("trade_date cannot be in the future")
    if d.year < 1985:
        raise InvError("trade_date is before 20 September 1985: pre-CGT assets are not tracked here")
    f = {k: core.num(body.get(k), k) or ZERO for k in ("amount", "fees", "franked", "unfranked", "franking_credits", "foreign_income", "foreign_tax_paid", "cg_discount_part", "cg_other_part", "tax_deferred", "withholding_tax")}
    qty = core.num(body.get("quantity"), "quantity", places=8) or ZERO
    price = core.num(body.get("price"), "price", places=8)
    adj = core.num(body.get("cost_base_adj"), "cost_base_adj", allow_negative=True) or ZERO
    if typ in NEEDS_QTY and qty <= 0:
        raise InvError(f"quantity must be greater than zero for a {typ.replace('_', ' ')}")
    if typ in ("buy", "sell") and f["amount"] == 0 and price and qty:
        f["amount"] = q2(qty * price)
    if typ in ("buy", "sell") and f["amount"] <= 0:
        raise InvError("Enter the amount (or a price and quantity)")
    if typ == "split" and (qty <= 0 or not price or price <= 0):
        raise InvError("A split needs both parts of the ratio: new units (quantity) for old units (price), for example 2 for 1")
    if typ in ("transfer_out", "transfer_in") and not (body.get("reference") or "").strip():
        raise InvError("A transfer needs a reference shared by its two halves, so cost base and acquisition dates carry across")
    if typ == "return_of_capital" and f["amount"] <= 0:
        raise InvError("Enter the return of capital amount")
    if typ == "cost_base_adjustment" and adj == 0:
        raise InvError("Enter the AMIT cost base net amount (positive to increase, negative to decrease)")
    if typ in ("dividend", "distribution", "interest", "drp", "income_in_kind") and f["amount"] <= 0:
        raise InvError("Enter the amount")
    if typ in ("dividend", "drp"):
        comp = f["franked"] + f["unfranked"]
        if comp and abs(comp - f["amount"]) > D("0.02"):
            raise InvError(f"franked + unfranked ({comp}) must equal the dividend amount ({f['amount']})")
        if f["franking_credits"] > f["franked"] * MAX_CREDIT_RATIO + D("0.05"):
            raise InvError("Franking credits cannot be more than 30/70 of the franked amount")
    if typ == "distribution":
        comp = f["franked"] + f["unfranked"] + f["foreign_income"] + f["cg_discount_part"] + f["cg_other_part"] + f["tax_deferred"]
        if comp > f["amount"] + D("0.05"):
            raise InvError(f"The components of the distribution ({comp}) are more than the cash distribution ({f['amount']})")
        if f["franking_credits"] > f["franked"] * MAX_CREDIT_RATIO + D("0.05"):
            raise InvError("Franking credits cannot be more than 30/70 of the franked amount")
    lot_ref = body.get("lot_ref")
    if lot_ref not in (None, ""):
        if typ != "sell":
            raise InvError("lot_ref (specific identification) applies to a sale only")
        src = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, id=int(lot_ref), account_id=acc.id, security_id=sec.id).first()
        if src is None or src.txn_type not in ("buy", "drp", "income_in_kind", "bonus") or src.voided:
            raise InvError("lot_ref must be an acquisition (buy, reinvestment, staking or bonus) of this security in this account")
        lot_ref = int(lot_ref)
    else:
        lot_ref = None
    if sec.kind == "crypto" and typ in ("dividend", "distribution", "bonus"):
        raise InvError("Crypto has no dividends: record staking or airdrops as 'income in kind'")
    if sec.kind in ("share", "etf") and typ == "income_in_kind":
        raise InvError("'Income in kind' is for crypto staking and airdrops: record shares received as a bonus issue or reinvestment")
    return dict(account=acc, security=sec, trade_date=d, txn_type=typ, quantity=qty, price=price, cost_base_adj=adj, lot_ref=lot_ref, reference=(body.get("reference") or "").strip()[:80] or None,
                notes=(body.get("notes") or "").strip()[:500] or None, **f)


def _integrity(db, ctx, acc_id: int, sec_id: int, candidate: Optional[dict], replace_id: Optional[int], method: str):
    """Replay the account/security with the change applied: the register must stay consistent (never sell what is not held)."""
    rows = [t for t in db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, security_id=sec_id).filter(M.InvTransaction.voided.is_(False)) if t.id != replace_id]      # all accounts: a transfer spans two
    if candidate:
        rows.append(type("C", (), candidate)())
    res = LE.replay(rows, method)
    bad = [w for w in res.warnings if w["kind"] in ("oversold", "lot_not_found", "bad_ratio", "bad_quantity")]
    return res, bad


def save_txn(db, ctx, a: Access, body: dict, tid: Optional[int] = None, source: str = "manual", source_key: Optional[str] = None) -> M.InvTransaction:
    a.require("edit")
    t = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, id=tid).first() if tid else None
    if tid and t is None:
        raise NotFound("Transaction")
    if t and (t.voided or t.linked_journal_id):
        raise Conflict("A voided transaction, or one already posted to the ledger, cannot be edited: void it and enter it again" if t.linked_journal_id else "A voided transaction cannot be edited", "locked")
    c = _clean_txn(db, ctx, body, t)
    method = get_settings(db, ctx).cgt_method
    cand = dict(id=tid or 10 ** 9, account_id=c["account"].id, security_id=c["security"].id, trade_date=c["trade_date"], txn_type=c["txn_type"], quantity=c["quantity"], price=c["price"], amount=c["amount"], fees=c["fees"], franked=c["franked"],
                unfranked=c["unfranked"], franking_credits=c["franking_credits"], foreign_income=c["foreign_income"], foreign_tax_paid=c["foreign_tax_paid"], cg_discount_part=c["cg_discount_part"], cg_other_part=c["cg_other_part"],
                tax_deferred=c["tax_deferred"], cost_base_adj=c["cost_base_adj"], withholding_tax=c["withholding_tax"], lot_ref=c["lot_ref"], reference=c["reference"], voided=False)
    _, bad = _integrity(db, ctx, c["account"].id, c["security"].id, cand, tid, method)
    if bad:
        raise InvError(bad[0]["message"], 422, "register_inconsistent")
    before = txn_dict(t, c["security"], c["account"]) if t else None
    if t is None:
        t = M.InvTransaction(org_id=ctx.org.id, created_by=ctx.user_id, source=source, source_key=source_key)
        db.add(t)
    t.account_id, t.security_id, t.trade_date, t.txn_type, t.quantity, t.price = c["account"].id, c["security"].id, c["trade_date"], c["txn_type"], c["quantity"], c["price"]
    for k in ("amount", "fees", "franked", "unfranked", "franking_credits", "foreign_income", "foreign_tax_paid", "cg_discount_part", "cg_other_part", "tax_deferred", "withholding_tax", "cost_base_adj", "lot_ref", "reference", "notes"):
        setattr(t, k, c[k])
    db.flush()
    core.record(db, ctx, "txn.save", "inv_transaction", t.id, f"{t.txn_type} {c['security'].code} {t.quantity} on {t.trade_date}, amount {t.amount}", before, txn_dict(t, c["security"], c["account"]))
    return t


def void_txn(db, ctx, a: Access, tid: int, reason: str) -> M.InvTransaction:
    a.require("edit")
    t = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, id=tid).first()
    if t is None:
        raise NotFound("Transaction")
    if t.voided:
        raise Conflict("Already voided")
    if t.linked_journal_id:
        raise Conflict("This transaction is posted to the ledger: reverse its journal in Accounting, clear the link here, then void it", "posted")
    if not reason or len(reason.strip()) < 5:
        raise InvError("A reason (at least 5 characters) is required")
    method = get_settings(db, ctx).cgt_method
    _, bad = _integrity(db, ctx, t.account_id, t.security_id, None, t.id, method)
    if bad:
        raise Conflict(f"Voiding this would leave a later sale without the units it needs ({bad[0]['message']}). Void or edit that sale first.", "register_inconsistent")
    t.voided, t.void_reason = True, reason.strip()[:300]
    core.record(db, ctx, "txn.void", "inv_transaction", t.id, f"Voided {t.txn_type} {t.quantity} on {t.trade_date}: {reason.strip()[:120]}", None, None)
    return t


def list_txns(db, ctx, account_id=None, security_id=None, txn_type="", date_from=None, date_to=None, q="", include_voided=False, kind="", limit=2000):
    qs = db.query(M.InvTransaction, M.InvSecurity, M.InvAccount).join(M.InvSecurity, M.InvTransaction.security_id == M.InvSecurity.id).join(M.InvAccount, M.InvTransaction.account_id == M.InvAccount.id).filter(M.InvTransaction.org_id == ctx.org.id)
    if account_id:
        qs = qs.filter(M.InvTransaction.account_id == account_id)
    if security_id:
        qs = qs.filter(M.InvTransaction.security_id == security_id)
    if txn_type:
        qs = qs.filter(M.InvTransaction.txn_type.in_(txn_type.split(",")))
    if kind:
        qs = qs.filter(M.InvSecurity.kind.in_(kind.split(",")))
    if date_from:
        qs = qs.filter(M.InvTransaction.trade_date >= date_from)
    if date_to:
        qs = qs.filter(M.InvTransaction.trade_date <= date_to)
    if not include_voided:
        qs = qs.filter(M.InvTransaction.voided.is_(False))
    rows = [txn_dict(t, s, ac) for t, s, ac in qs.order_by(M.InvTransaction.trade_date.desc(), M.InvTransaction.id.desc()).limit(limit)]
    if q:
        w = q.strip().lower()
        rows = [r for r in rows if w in (r["code"] or "").lower() or w in (r["security"] or "").lower() or w in (r["reference"] or "").lower() or w in (r["notes"] or "").lower()]
    return rows


def crypto_swap(db, ctx, a: Access, account_id, trade_date, sell_security_id, sell_qty, buy_security_id, buy_qty, value_aud, fees=0, reference=None) -> dict:
    """A crypto-to-crypto swap is a disposal of what was sent AND an acquisition of what was received, both at the AUD market value at that time (ATO)."""
    a.require("edit")
    ref = reference or f"swap-{trade_date}"
    out = save_txn(db, ctx, a, dict(txn_type="sell", account_id=account_id, security_id=sell_security_id, trade_date=trade_date, quantity=sell_qty, amount=value_aud, fees=fees, reference=ref, notes="Swap: disposal leg"))
    inn = save_txn(db, ctx, a, dict(txn_type="buy", account_id=account_id, security_id=buy_security_id, trade_date=trade_date, quantity=buy_qty, amount=value_aud, fees=0, reference=ref, notes="Swap: acquisition leg"))
    return dict(sell=out.id, buy=inn.id)
