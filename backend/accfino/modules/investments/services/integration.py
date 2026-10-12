"""Integration with the rest of AccFino: the general ledger (posting + reconciliation), Taxation > CGT (disposals and property sales) and, through the ledger, banking and the financial reports."""
from collections import defaultdict
from datetime import date
from typing import List, Optional

import accfino.modules.accounting.public as acct
from accfino.modules.investments.engine import property as PR
from accfino.modules.investments.engine.money import ZERO, D, q2
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import core, data, portfolio, property_svc
from accfino.modules.investments.services.core import Access, Conflict, InvError, NotFound
import accfino.modules.taxation.public as tax

CGT_CLASS = {"share": "shares", "etf": "etf", "crypto": "crypto", "managed_fund": "other", "bond": "other", "term_deposit": "other"}
POSTABLE = {"buy", "sell", "dividend", "distribution", "interest", "drp", "fee", "return_of_capital", "income_in_kind"}
NOT_POSTABLE = {"split": "a split has no ledger effect", "bonus": "a bonus issue has no ledger effect", "cost_base_adjustment": "an AMIT cost base adjustment is a tax-only entry", "transfer_out": "a transfer between your own accounts has no ledger effect",
                "transfer_in": "a transfer between your own accounts has no ledger effect"}


# ---------------------------------------------------------------------------------------------------------------------- Taxation > CGT
def cgt_event_rows(db, ctx, fy: str = "", kind: str = "", security_id: Optional[int] = None) -> List[dict]:
    d = portfolio.disposals(db, ctx, fy, kind, security_id)
    out = []
    for r in d["rows"]:
        out.append(dict(asset_class=CGT_CLASS[r["kind"]], asset_name=f"{r['name']} ({r['code']})"[:200], quantity=str(r["qty"]), acquire_date=r["acquire_date"], dispose_date=r["dispose_date"], proceeds=str(r["proceeds"]),
                        acquisition_cost=str(r["cost_base"]), disposal_costs=str(r["selling_costs"]), pre_cgt=False, main_residence_exempt=False, source_ref=f"inv:{r['txn_id']}:{r['acquire_date']}:{r['qty']}",
                        notes=f"From Investments ({r['method'].upper()}, account {r['account']}). Cost base includes brokerage/fees."))
    return out


def send_cgt(db, ctx, a: Access, fy: str = "", kind: str = "", dry_run: bool = False) -> dict:
    a.require("edit")
    rows = cgt_event_rows(db, ctx, fy, kind)
    res = tax.record_cgt_events(db, ctx, rows, dry_run)
    res["events"] = len(rows)
    if not dry_run:
        core.record(db, ctx, "cgt.send", "inv_transaction", None, f"Sent {res['added']} disposal(s) to Taxation > CGT ({res['skipped_duplicates']} already there, {res['rejected']} rejected)", None, dict(fy=fy, kind=kind))
    return res


def send_property_sale(db, ctx, a: Access, pid: int, dry_run: bool = False) -> dict:
    a.require("edit")
    p = property_svc.get(db, ctx, pid)
    if not (p.sale_contract_date and p.sale_price):
        raise InvError("Record the sale contract date and price on the property first")
    d = property_svc.detail(db, ctx, pid, p.sale_contract_date)
    cb, est = d["cost_base"], d["cgt_estimate"]
    note = "From the Investments property register. "
    exempt = est["main_residence_fraction"] == 1
    if 0 < est["main_residence_fraction"] < 1:
        note += f"A partial main residence exemption (about {float(est['main_residence_fraction']):.0%} by days) is estimated but NOT applied here: a tax agent must adjust the event. "
    ev = dict(asset_class="property", asset_name=f"{p.name}"[:200], quantity="1", acquire_date=(p.contract_date or p.settlement_date).isoformat(), dispose_date=p.sale_contract_date.isoformat(), proceeds=str(est["capital_proceeds"]),
              acquisition_cost=str(cb["element1_price"]), incidental_costs=str(cb["element2_incidental"] - q2(p.selling_costs * p.ownership_pct / D(100))), ownership_costs=str(cb["element3_ownership"]),
              capital_improvements=str(cb["element4_improvements"] + cb["element5_title"] - cb["capital_works_claimed"]), disposal_costs=str(q2(p.selling_costs * p.ownership_pct / D(100))), pre_cgt=False, main_residence_exempt=exempt,
              source_ref=f"inv-property:{p.id}:{p.sale_contract_date}", notes=note + "Capital works deductions claimed have been subtracted from the improvements.")
    if not p.contract_date and not p.settlement_date:
        raise InvError("Record the purchase contract date on the property first")
    res = tax.record_cgt_events(db, ctx, [ev], dry_run)
    if not dry_run:
        core.record(db, ctx, "cgt.send_property", "inv_property", pid, f"Property sale sent to Taxation > CGT ({res['added']} added)", None, ev)
    return res


# ---------------------------------------------------------------------------------------------------------------------- ledger
def _acct(db, ctx, key):
    m = (data.get_settings(db, ctx).ledger_map or data.DEFAULT_LEDGER_MAP)[key]
    return acct.ensure_ledger_account(db, ctx.org.id, code=m["code"], name=m["name"], account_type=m["type"], system_key=m["key"])["id"]


def _lines(db, ctx, t: M.InvTransaction, bank_id: int, costs: dict) -> List[dict]:
    fees, amt = D(t.fees), D(t.amount)
    Dr = lambda acc, v: dict(account_id=acc, debit=v, credit=ZERO)
    Cr = lambda acc, v: dict(account_id=acc, debit=ZERO, credit=v)
    inv, ty = _acct(db, ctx, "asset"), t.txn_type
    if ty == "buy":
        return [Dr(inv, amt + fees), Cr(bank_id, amt + fees)]
    if ty == "sell":
        net, cost = amt - fees, costs.get(t.id, ZERO)
        gain = net - cost
        lines = [Dr(bank_id, net), Cr(inv, cost)]
        if gain > 0:
            lines.append(Cr(_acct(db, ctx, "gain"), gain))
        elif gain < 0:
            lines.append(Dr(_acct(db, ctx, "loss"), -gain))
        return lines
    if ty in ("dividend", "distribution"):
        return [Dr(bank_id, amt), Cr(_acct(db, ctx, "dividend"), amt)]
    if ty == "interest":
        return [Dr(bank_id, amt), Cr(_acct(db, ctx, "interest"), amt)]
    if ty == "drp":
        return [Dr(inv, amt + fees), Cr(_acct(db, ctx, "dividend"), amt)] + ([Cr(bank_id, fees)] if fees else [])
    if ty == "income_in_kind":
        return [Dr(inv, amt), Cr(_acct(db, ctx, "dividend"), amt)]
    if ty == "fee":
        return [Dr(_acct(db, ctx, "fees"), amt + fees), Cr(bank_id, amt + fees)]
    if ty == "return_of_capital":
        return [Dr(bank_id, amt), Cr(inv, amt)]
    raise InvError(f"{ty} cannot be posted")


def post_to_ledger(db, ctx, a: Access, txn_ids: List[int], bank_account_id: int) -> dict:
    """Post each transaction as ONE balanced journal through the ledger service (period locks and validation apply). Cash goes to the bank account you choose, so the existing bank reconciliation
    matches it against the statement. Investments are carried at COST; a sale posts the realised gain or loss. Transactions with withholding tax are refused (record those by hand)."""
    a.require("post")
    banks = {x["id"] for x in acct.ledger_accounts(db, ctx.org.id) if x["type"] == "bank"}
    if bank_account_id not in banks:
        raise InvError("Choose a bank account from your ledger")
    res = portfolio.replay(db, ctx)
    costs = defaultdict(lambda: ZERO)
    for d in res.disposals:
        costs[d.txn_id] += d.cost_base
    done, skipped, failed = [], [], []
    for tid in txn_ids:
        t = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, id=tid).first()
        if t is None:
            failed.append(dict(id=tid, error="Transaction not found")); continue
        if t.voided:
            skipped.append(dict(id=tid, reason="voided")); continue
        if t.linked_journal_id:
            skipped.append(dict(id=tid, reason="already posted")); continue
        if t.txn_type in NOT_POSTABLE:
            skipped.append(dict(id=tid, reason=NOT_POSTABLE[t.txn_type])); continue
        if D(t.withholding_tax) > 0:
            failed.append(dict(id=tid, error="Withholding tax: record this one in the ledger by hand")); continue
        sp = db.begin_nested()
        try:
            sec = db.get(M.InvSecurity, t.security_id)
            j = acct.post_journal(db, ctx.org, journal_date=t.trade_date, narration=f"{t.txn_type} {sec.code} {t.quantity}", lines=_lines(db, ctx, t, bank_account_id, costs), created_by=ctx.user_id, source_type="investments", source_ref=f"inv:{t.id}", reference=t.reference)
            t.linked_journal_id = j.id                                         # the ledger's own Journal object (the same facade function Payroll uses)
            sp.commit()
            done.append(dict(id=tid, journal_id=j.id, journal_no=getattr(j, "journal_no", None)))
        except acct.LedgerError as e:
            sp.rollback()
            failed.append(dict(id=tid, error=str(e)))
        except Exception as e:
            sp.rollback()
            failed.append(dict(id=tid, error=getattr(e, "message", None) or str(e)))
    core.record(db, ctx, "ledger.post", "inv_transaction", None, f"Posted {len(done)} transaction(s) to the ledger, {len(skipped)} skipped, {len(failed)} failed", None, dict(bank_account_id=bank_account_id))
    return dict(posted=done, skipped=skipped, failed=failed)


def unlink(db, ctx, a: Access, tid: int):
    """Clear the ledger link after the journal was reversed in Accounting. AccFino does not reverse journals for you."""
    a.require("post")
    t = db.query(M.InvTransaction).filter_by(org_id=ctx.org.id, id=tid).first()
    if t is None:
        raise NotFound("Transaction")
    if not t.linked_journal_id:
        raise Conflict("This transaction is not linked to a journal")
    j = acct.journal_summary(db, ctx.org.id, t.linked_journal_id)
    if j and j.get("status") not in ("reversed", "void", "voided"):
        raise Conflict("The journal is still active in the ledger: reverse it in Accounting first, then clear the link here", "journal_active")
    old = t.linked_journal_id
    t.linked_journal_id = None
    core.record(db, ctx, "ledger.unlink", "inv_transaction", tid, f"Cleared the link to journal {old}", dict(journal=old), None)
    return t


def reconciliation(db, ctx, as_at: Optional[date] = None) -> dict:
    """Register against ledger: the cost base of the register's holdings vs the ledger's investments account, and what has and has not been posted."""
    as_at = as_at or date.today()
    h = portfolio.holdings(db, ctx, as_at)
    m = (data.get_settings(db, ctx).ledger_map or data.DEFAULT_LEDGER_MAP)["asset"]
    bal = {b["code"]: D(b["balance"]) for b in acct.balances_by_account(db, ctx.org, as_at)}
    ledger = bal.get(m["code"])
    posted = db.query(M.InvTransaction).filter(M.InvTransaction.org_id == ctx.org.id, M.InvTransaction.voided.is_(False), M.InvTransaction.linked_journal_id.isnot(None)).count()
    postable = db.query(M.InvTransaction).filter(M.InvTransaction.org_id == ctx.org.id, M.InvTransaction.voided.is_(False), M.InvTransaction.linked_journal_id.is_(None), M.InvTransaction.txn_type.in_(list(POSTABLE))).count()
    reg = h["total_cost"]
    diff = None if ledger is None else q2(reg - ledger)
    # Tax-only cost base changes are not ledger entries: the tax-deferred part of a POSTED distribution and the AMIT cost base net amount reduce (or raise) the register's cost base while the ledger carries the cash as income and the
    # investment at cost; an AMIT adjustment entered on its own is never posted. They explain a difference; anything beyond them does not.
    live = db.query(M.InvTransaction).filter(M.InvTransaction.org_id == ctx.org.id, M.InvTransaction.voided.is_(False)).all()
    tax_only = q2(sum((D(t.cost_base_adj) - (D(t.tax_deferred) if t.txn_type in ("distribution", "dividend") else ZERO)) for t in live if t.linked_journal_id or t.txn_type == "cost_base_adjustment") or ZERO)
    unexplained = None if diff is None else q2(diff - tax_only)
    if ledger is None:
        status = "no_ledger_account"
    elif diff == 0:
        status = "agrees"
    elif tax_only != 0 and unexplained == 0:
        status = "agrees_after_tax_adjustments"
    else:
        status = "differs"
    return dict(as_at=as_at.isoformat(), register_cost_base=reg, ledger_account=dict(code=m["code"], name=m["name"], balance=None if ledger is None else q2(ledger)), difference=diff, tax_only_adjustments=tax_only, unexplained_difference=unexplained, status=status,
                posted_transactions=posted, unposted_postable=postable,
                explanation={"agrees": "The register's cost base equals the ledger's investments account.",
                             "agrees_after_tax_adjustments": "The only difference is tax-only cost base changes (the tax-deferred part of distributions and AMIT adjustments). They reduce the tax cost base but are not ledger entries, so the ledger correctly carries them at cost.",
                             "differs": "They differ beyond any tax-only cost base changes: transactions not yet posted, entries made in the ledger by hand, or a cost base change (return of capital, bonus issue) that has no ledger journal.",
                             "no_ledger_account": "Nothing has been posted to the ledger yet."}[status])
