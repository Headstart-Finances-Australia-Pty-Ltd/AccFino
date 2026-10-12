"""Assets, Investments & Wealth HTTP API (mounted at /invest). The API layer only validates, authorises and calls services; the rules live in services/ and engine/."""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from accfino.core.security.context import OrgContext, current_org
import accfino.modules.accounting.public as acct
from accfino.modules.investments.api.deps import access
from accfino.modules.investments.models import inv as M
from accfino.modules.investments.services import (core, data, documents, imports, integration, portfolio, property_svc, reports, valuations, wealth)
from accfino.modules.investments.services.core import Access
from accfino.shared.db.database import get_db

router = APIRouter()
Ctx, Db, Acc = Depends(current_org), Depends(get_db), Depends(access)
P = core.plain


def _d(v, name):
    return core.parse_date(v, name)


@router.get("/me")
def me(a: Access = Acc):
    return a.summary()


@router.get("/reference")
def reference(a: Access = Acc):
    return dict(security_kinds=list(M.SECURITY_KINDS), asset_classes=list(M.ASSET_CLASSES), account_kinds=list(M.ACCOUNT_KINDS), txn_types=list(M.TXN_TYPES), cgt_methods=list(M.CGT_METHODS), holders=list(M.HOLDERS), property_types=list(M.PROPERTY_TYPES),
                property_uses=list(M.PROPERTY_USES), entry_kinds=list(M.ENTRY_KINDS), expense_categories=list(M.EXPENSE_CATEGORIES), liability_kinds=list(M.LIABILITY_KINDS), other_asset_kinds=list(M.OTHER_ASSET_KINDS), states=list(property_svc.STATES))


@router.get("/settings")
def get_settings(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return data.settings_dict(data.get_settings(db, ctx))


@router.put("/settings")
def put_settings(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = data.save_settings(db, ctx, a, body)
    db.commit()
    return data.settings_dict(s)


# ---- accounts, securities, prices ---------------------------------------------------------------------------------------------------------
@router.get("/accounts")
def accounts(active_only: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return data.accounts(db, ctx, active_only)


@router.post("/accounts")
def account_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = data.save_account(db, ctx, a, body)
    db.commit()
    return data.acc_dict(x)


@router.put("/accounts/{aid}")
def account_upd(aid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = data.save_account(db, ctx, a, body, aid)
    db.commit()
    return data.acc_dict(x)


@router.get("/securities")
def securities(kind: str = "", q: str = "", active_only: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return data.securities(db, ctx, kind, q, active_only)


@router.post("/securities")
def security_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = data.save_security(db, ctx, a, body)
    db.commit()
    return data.sec_dict(s)


@router.put("/securities/{sid}")
def security_upd(sid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = data.save_security(db, ctx, a, body, sid)
    db.commit()
    return data.sec_dict(s)


@router.get("/securities/{sid}/detail")
def security_detail(sid: int, as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(portfolio.security_detail(db, ctx, sid, _d(as_at, "as_at")))


@router.post("/securities/{sid}/prices")
def price_set(sid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    r = data.set_price(db, ctx, a, sid, body.get("price_date"), body.get("price"))
    db.commit()
    return dict(id=r.id, date=r.price_date.isoformat(), price=str(r.price))


@router.get("/securities/{sid}/prices")
def prices(sid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    data.get_security(db, ctx, sid)
    return data.prices(db, ctx, sid)


@router.delete("/prices/{pid}")
def price_del(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    data.delete_price(db, ctx, a, pid)
    db.commit()
    return {"ok": True}


# ---- transactions ---------------------------------------------------------------------------------------------------------------------------
@router.get("/transactions")
def txns(account_id: Optional[int] = None, security_id: Optional[int] = None, txn_type: str = "", kind: str = "", date_from: str = "", date_to: str = "", q: str = "", include_voided: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return data.list_txns(db, ctx, account_id, security_id, txn_type, _d(date_from, "date_from"), _d(date_to, "date_to"), q, include_voided, kind)


@router.post("/transactions")
def txn_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    t = data.save_txn(db, ctx, a, body)
    db.commit()
    return data.txn_dict(t)


@router.put("/transactions/{tid}")
def txn_upd(tid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    t = data.save_txn(db, ctx, a, body, tid)
    db.commit()
    return data.txn_dict(t)


@router.post("/transactions/{tid}/void")
def txn_void(tid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    t = data.void_txn(db, ctx, a, tid, body.get("reason", ""))
    db.commit()
    return data.txn_dict(t)


@router.post("/crypto/swap")
def crypto_swap(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = data.crypto_swap(db, ctx, a, body.get("account_id"), body.get("trade_date"), body.get("sell_security_id"), body.get("sell_qty"), body.get("buy_security_id"), body.get("buy_qty"), body.get("value_aud"), body.get("fees") or 0, body.get("reference"))
    db.commit()
    return out


# ---- portfolio ------------------------------------------------------------------------------------------------------------------------------
@router.get("/portfolio/holdings")
def p_holdings(as_at: str = "", kind: str = "", account_id: Optional[int] = None, merge: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    h = portfolio.holdings(db, ctx, _d(as_at, "as_at"), kind, account_id)
    if merge:
        h = dict(h, rows=portfolio.by_security(h))
    return P(h)


@router.get("/portfolio/disposals")
def p_disposals(fy: str = "", kind: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(portfolio.disposals(db, ctx, fy, kind))


@router.get("/portfolio/income")
def p_income(fy: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(portfolio.income(db, ctx, fy))


@router.get("/portfolio/performance")
def p_perf(as_at: str = "", security_id: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(portfolio.performance(db, ctx, _d(as_at, "as_at"), security_id))


@router.get("/portfolio/allocation")
def p_alloc(as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(portfolio.allocation(db, ctx, _d(as_at, "as_at")))


@router.get("/portfolio/history")
def p_hist(months: int = 24, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(portfolio.history(db, ctx, months))


# ---- property -------------------------------------------------------------------------------------------------------------------------------
@router.get("/properties")
def props(as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(property_svc.overview(db, ctx, _d(as_at, "as_at")))


@router.post("/properties")
def prop_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    p = property_svc.save(db, ctx, a, body)
    db.commit()
    return property_svc.p_dict(p)


@router.put("/properties/{pid}")
def prop_upd(pid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    p = property_svc.save(db, ctx, a, body, pid)
    db.commit()
    return property_svc.p_dict(p)


@router.delete("/properties/{pid}")
def prop_del(pid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    property_svc.delete(db, ctx, a, pid)
    db.commit()
    return {"ok": True}


@router.get("/properties/{pid}")
def prop_detail(pid: int, as_at: str = "", sale_price: str = "", sale_date: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(property_svc.detail(db, ctx, pid, _d(as_at, "as_at"), sale_price or None, sale_date or None))


@router.get("/properties/{pid}/entries")
def prop_entries(pid: int, kind: str = "", fy: str = "", category: str = "", include_voided: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    property_svc.get(db, ctx, pid)
    return property_svc.entries(db, ctx, pid, kind, fy, category, include_voided)


@router.post("/properties/{pid}/entries")
def prop_entry_add(pid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = property_svc.save_entry(db, ctx, a, pid, body)
    db.commit()
    return property_svc.e_dict(e)


@router.put("/properties/{pid}/entries/{eid}")
def prop_entry_upd(pid: int, eid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    e = property_svc.save_entry(db, ctx, a, pid, body, eid)
    db.commit()
    return property_svc.e_dict(e)


@router.post("/properties/{pid}/entries/{eid}/void")
def prop_entry_void(pid: int, eid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    property_svc.void_entry(db, ctx, a, pid, eid, body.get("reason", ""))
    db.commit()
    return {"ok": True}


@router.post("/properties/{pid}/cgt/send")
def prop_cgt(pid: int, dry_run: bool = False, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = integration.send_property_sale(db, ctx, a, pid, dry_run)
    db.commit() if not dry_run else db.rollback()
    return out


# ---- valuations, other assets, liabilities, net worth ---------------------------------------------------------------------------------------
@router.post("/valuations")
def val_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    v = valuations.add(db, ctx, a, body.get("owner_type", ""), body.get("owner_id") or 0, body.get("as_at"), body.get("value"), body.get("basis", ""))
    db.commit()
    return dict(id=v.id, as_at=v.as_at.isoformat(), value=str(v.value))


@router.get("/valuations/{owner_type}/{owner_id}")
def val_list(owner_type: str, owner_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return valuations.history(db, ctx, owner_type, owner_id)


@router.delete("/valuations/{vid}")
def val_del(vid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    valuations.remove(db, ctx, a, vid)
    db.commit()
    return {"ok": True}


@router.get("/other-assets")
def oa_list(as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return wealth.other_assets(db, ctx, _d(as_at, "as_at"))


@router.post("/other-assets")
def oa_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = wealth.save_other_asset(db, ctx, a, body)
    db.commit()
    return wealth.oa_dict(x)


@router.put("/other-assets/{oid}")
def oa_upd(oid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = wealth.save_other_asset(db, ctx, a, body, oid)
    db.commit()
    return wealth.oa_dict(x)


@router.get("/liabilities")
def li_list(as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return wealth.liabilities(db, ctx, _d(as_at, "as_at"))


@router.post("/liabilities")
def li_add(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = wealth.save_liability(db, ctx, a, body)
    db.commit()
    return wealth.li_dict(x)


@router.put("/liabilities/{lid}")
def li_upd(lid: int, body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = wealth.save_liability(db, ctx, a, body, lid)
    db.commit()
    return wealth.li_dict(x)


@router.get("/networth")
def nw(as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(wealth.networth(db, ctx, _d(as_at, "as_at")))


@router.get("/networth/history")
def nw_hist(months: int = 24, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(wealth.history(db, ctx, months))


@router.get("/networth/snapshots")
def nw_snaps(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return wealth.snapshots(db, ctx)


@router.post("/networth/snapshots")
def nw_snap(body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    s = wealth.take_snapshot(db, ctx, a, body.get("as_at"))
    db.commit()
    return dict(id=s.id, as_at=s.as_at.isoformat(), net_worth=str(s.net_worth))


# ---- documents ------------------------------------------------------------------------------------------------------------------------------
@router.post("/documents")
async def doc_upload(file: UploadFile = File(...), owner_type: str = Form(...), owner_id: int = Form(...), title: str = Form(""), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    raw = await file.read()
    x = documents.upload(db, ctx, a, owner_type, owner_id, title, file.filename or "", file.content_type or "", raw)
    db.commit()
    return documents.d_dict(x)


async def _bulk_files(files: List[UploadFile]) -> dict:
    out = {}
    for f in files:
        out[f.filename or ""] = await f.read()
    return out


@router.get("/documents/bulk/template")
def doc_bulk_template(a: Access = Acc):
    return Response(documents.MANIFEST_TEMPLATE, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="template_documents_manifest.csv"'})


@router.post("/documents/bulk/preview")
async def doc_bulk_preview(manifest: UploadFile = File(...), files: List[UploadFile] = File(default=[]), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = documents.bulk_preview(db, ctx, a, await manifest.read(), await _bulk_files(files))
    db.rollback()
    return out


@router.post("/documents/bulk/commit")
async def doc_bulk_commit(manifest: UploadFile = File(...), files: List[UploadFile] = File(default=[]), mode: str = Form("valid_only"), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = documents.bulk_commit(db, ctx, a, await manifest.read(), await _bulk_files(files), mode)
    db.commit()
    return out


@router.get("/documents")
def doc_list(owner_type: str, owner_id: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return documents.listing(db, ctx, owner_type, owner_id)


@router.get("/documents/{did}/download")
def doc_download(did: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    x = documents.download(db, ctx, did)
    return Response(x.data, media_type=x.content_type, headers={"Content-Disposition": f'attachment; filename="{(x.file_name or "document").replace(chr(34), "")}"', "X-Content-Type-Options": "nosniff"})


@router.delete("/documents/{did}")
def doc_del(did: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    documents.delete(db, ctx, a, did)
    db.commit()
    return {"ok": True}


# ---- integration: Taxation > CGT, ledger ----------------------------------------------------------------------------------------------------
@router.get("/cgt/preview")
def cgt_preview(fy: str = "", kind: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return integration.cgt_event_rows(db, ctx, fy, kind)


@router.post("/cgt/send")
def cgt_send(body: dict = Body(default={}), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = integration.send_cgt(db, ctx, a, body.get("fy", ""), body.get("kind", ""), bool(body.get("dry_run")))
    db.rollback() if body.get("dry_run") else db.commit()
    return out


@router.get("/ledger/bank-accounts")
def bank_accounts(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return [x for x in acct.ledger_accounts(db, ctx.org.id) if x["type"] == "bank"]


@router.post("/ledger/post")
def ledger_post(body: dict = Body(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = integration.post_to_ledger(db, ctx, a, [int(x) for x in body.get("txn_ids", [])], int(body.get("bank_account_id") or 0))
    db.commit()
    return out


@router.post("/ledger/unlink/{tid}")
def ledger_unlink(tid: int, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    integration.unlink(db, ctx, a, tid)
    db.commit()
    return {"ok": True}


@router.get("/ledger/reconciliation")
def ledger_rec(as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return P(integration.reconciliation(db, ctx, _d(as_at, "as_at")))


# ---- imports, reports, audit ----------------------------------------------------------------------------------------------------------------
@router.get("/import/catalogue")
def imp_cat(a: Access = Acc):
    return imports.catalogue()


@router.get("/import/{key}/template")
def imp_template(key: str, a: Access = Acc):
    return Response(imports.template_csv(key), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="template_{key}.csv"'})


async def _csv(file: UploadFile) -> bytes:
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(422, "The file is larger than 2 MB")
    return raw


@router.post("/import/{key}/preview")
async def imp_preview(key: str, file: UploadFile = File(...), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = imports.preview(db, ctx, a, key, await _csv(file))
    db.rollback()
    return out


@router.post("/import/{key}/commit")
async def imp_commit(key: str, file: UploadFile = File(...), mode: str = Form("valid_only"), ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    out = imports.commit(db, ctx, a, key, await _csv(file), mode)
    db.commit()
    return out


@router.get("/reports/{name}.csv")
def report_csv(name: str, fy: str = "", kind: str = "", as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    fn, text = reports.csv_for(db, ctx, name, fy, kind, _d(as_at, "as_at"))
    return Response(text, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{fn}"', "X-Content-Type-Options": "nosniff"})


@router.get("/reports/pack.xlsx")
def report_pack(fy: str = "", as_at: str = "", ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    return Response(reports.xlsx_pack(db, ctx, fy, _d(as_at, "as_at")), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="investments_pack.xlsx"'})


@router.get("/audit")
def audit(limit: int = Query(100, ge=1, le=500), entity_type: str = "", entity_id: Optional[str] = None, before_seq: Optional[int] = None, ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("audit_view")
    return core.audit_rows(db, ctx, limit, entity_type, entity_id, before_seq)


@router.get("/audit/verify")
def audit_verify(ctx: OrgContext = Ctx, db: Session = Db, a: Access = Acc):
    a.require("audit_view")
    return core.verify_audit(db, ctx.org.id)
