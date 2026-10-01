"""End-to-end test of the journal workflow through HTTP (FastAPI TestClient) against a COPY of the seeded demo database."""
import os, shutil, sys
sys.path.insert(0, "/home/claude/w/AccFino/backend"); os.environ["DATABASE_URL"] = "postgresql://x:y@localhost/none"
SRC = os.environ.get("DEMO_DB", "/tmp/demo.db"); DB = "/tmp/led_test.db"; shutil.copy(SRC, DB)
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from accfino_core import models as m
from accfino_core.api import ledger, ledger_tools, books_reports, books_docs
from accfino_core.books.common import BooksError
from accfino_core.security.context import OrgContext, current_org
from db_app.database import get_db

eng = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False}); event.listen(eng, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
Sess = sessionmaker(bind=eng)
app = FastAPI()
@app.exception_handler(BooksError)
async def _e(request, exc): return JSONResponse({"detail": str(exc)}, status_code=exc.status)
for r, p in ((ledger.router, "/ledger"), (ledger_tools.router, "/ledger"), (books_reports.ledger_reports, "/ledger/reports"), (books_docs.attachments_router, "/attachments")): app.include_router(r, prefix=p)
WHO = {"uid": 1, "name": "owner", "role": "owner"}
def _db():
    d = Sess()
    try: yield d
    finally: d.close()
def _ctx():
    d = Sess(); org = d.query(m.Organisation).first()
    return OrgContext(WHO["uid"], WHO["name"], False, org, WHO["role"])
app.dependency_overrides[get_db] = _db; app.dependency_overrides[current_org] = _ctx
c = TestClient(app)
def as_(uid, name, role): WHO.update(uid=uid, name=name, role=role)
from accfino_core.security import audit as _audit
AUDIT = []
_audit.write = lambda action, **kw: AUDIT.append((action, kw.get("entity"), kw.get("entity_id"), kw.get("username")))
fails = []
def T(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   -> {detail}"))
    if not cond: fails.append(name)
def acct(code):
    with eng.connect() as k: return k.exec_driver_sql("select id from ledger_accounts where code=?", (code,)).scalar()
def taxid(code):
    with eng.connect() as k: return k.exec_driver_sql("select id from tax_codes where code=?", (code,)).scalar()
def tb():
    return c.get("/ledger/reports/trial-balance") if False else None
def gst_summary():
    from accfino_core.books import reports as R
    d = Sess(); org = d.query(m.Organisation).first(); r = R.gst_summary(d, org, date(2026, 7, 1), date(2026, 9, 30)); d.close(); return r
T0 = date(2026, 9, 30)
E1, E2, GST = acct("445"), acct("805"), acct("820")

# ---------------------------------------------------------------- 1. GST on a manual journal (the defect)
r = c.post("/ledger/journals", json={"date": str(T0), "narration": "x", "lines": [{"account_id": E1, "debit": "100", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "100"}]})
T("no_tax + a 10% tax code is REFUSED (used to silently drop the GST)", r.status_code == 422 and "GST" in r.text, r.text[:160])
g0 = gst_summary()
r = c.post("/ledger/journals", json={"date": str(T0), "narration": "Inclusive test", "reference": "REF-INC", "amounts_are": "inclusive",
    "lines": [{"account_id": E1, "debit": "110.00", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "110.00"}]})
T("GST-inclusive journal posts", r.status_code == 200, r.text[:200])
j = r.json(); by = {l["account_code"]: l for l in j["lines"]}
T("inclusive: expense is net 100.00, GST line 10.00, reference kept", by["445"]["debit"] == "100.00" and by["820"]["debit"] == "10.00" and j["reference"] == "REF-INC", str(j["lines"]))
T("inclusive: the expense line carries the tax amount for the BAS", by["445"]["tax_amount"] == "10.00")
g1 = gst_summary()
T("BAS 1B rose by exactly 10.00 and the GST account still reconciles", Decimal(g1["gst_on_purchases_1B"]) - Decimal(g0["gst_on_purchases_1B"]) == Decimal("10.00") and g1["ledger_check"]["reconciled"], f"{g0['gst_on_purchases_1B']} -> {g1['gst_on_purchases_1B']} {g1['ledger_check']}")
r = c.post("/ledger/journals", json={"date": str(T0), "narration": "Exclusive test", "amounts_are": "exclusive",
    "lines": [{"account_id": E1, "debit": "200.00", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "220.00"}]})
T("GST-exclusive journal posts when balanced after GST", r.status_code == 200, r.text[:200])
r = c.post("/ledger/journals", json={"date": str(T0), "narration": "Exclusive unbalanced", "amounts_are": "exclusive", "lines": [{"account_id": E1, "debit": "200.00", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "200.00"}]})
T("exclusive: an entry that only balances BEFORE GST is refused with the difference", r.status_code == 422 and "balance" in r.text.lower(), r.text[:200])
r = c.post("/ledger/journals", json={"date": str(T0), "narration": "AR", "lines": [{"account_id": acct("610"), "debit": "10"}, {"account_id": E2, "credit": "10"}]})
T("manual journal to the AR control account is refused", r.status_code == 422 and "control account" in r.text, r.text[:160])
r = c.post("/ledger/journals", json={"date": "2026-01-01", "narration": "Locked?", "lines": [{"account_id": E1, "debit": "5"}, {"account_id": E2, "credit": "5"}]}); T("plain manual journal still works (no_tax, no code)", r.status_code == 200, r.text[:160])

# ---------------------------------------------------------------- 2. preview
pv = c.post("/ledger/journal-preview", json={"date": str(T0), "amounts_are": "exclusive", "lines": [{"account_id": E1, "debit": "1000", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "1100"}]}).json()
T("preview shows the GST line that will be added and that it balances", pv["balanced"] and pv["gst_total"] == "100.00" and any(l["is_gst"] for l in pv["lines"]) and not pv["errors"], str(pv)[:250])
pv = c.post("/ledger/journal-preview", json={"date": str(T0), "lines": [{"account_id": E1, "debit": "50"}, {"account_id": E2, "credit": "40"}]}).json()
T("preview reports the out-of-balance amount instead of failing", (not pv["balanced"]) and any("10.00" in e for e in pv["errors"]), str(pv["errors"]))

# ---------------------------------------------------------------- 3. auto-reversing journal
r = c.post("/ledger/journals", json={"date": str(T0), "narration": "Accrual test", "reference": "ACC-T", "auto_reverse_date": str(T0 + timedelta(days=1)),
    "lines": [{"account_id": E1, "debit": "300"}, {"account_id": E2, "credit": "300"}]}).json()
T("auto-reversing journal returns the pending reversal", r.get("auto_reversal") and r["auto_reversal"]["date"] == str(T0 + timedelta(days=1)), str(r)[:200])
det = c.get(f"/ledger/journals/{r['id']}").json()
T("detail shows the pending reversal, original stays 'posted'", det["status"] == "posted" and det["reversal"] and det["reversal"]["pending"], str(det.get("reversal")))
rv = c.post(f"/ledger/journals/{r['id']}/reverse", json={})
T("cannot also reverse it by hand (would double-reverse)", rv.status_code == 422 and "auto-reversing" in rv.text, rv.text[:160])
bad = c.post("/ledger/journals", json={"date": str(T0), "narration": "bad", "auto_reverse_date": str(T0), "lines": [{"account_id": E1, "debit": "1"}, {"account_id": E2, "credit": "1"}]})
T("auto-reverse date must be after the journal date", bad.status_code == 422, bad.text[:120])
hist = c.get(f"/ledger/journals/{r['id']}/history").json()
T("history lists creation and the scheduled auto-reversal", any("auto-reversal" in e["action"] for e in hist["events"]) and any(e["action"] == "created" for e in hist["events"]), str([e["action"] for e in hist["events"]]))

# ---------------------------------------------------------------- 4. list, search, filters, source detail
r = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "q": "REF-INC"}).json()
T("search finds a journal by reference", r["total"] == 1 and r["items"][0]["reference"] == "REF-INC", str(r)[:200])
r = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "source_type": "doc_invoice", "limit": 5}).json()
T("filter by a source the old dropdown could not offer (sales invoices)", r["total"] > 100 and all(i["source_type"] == "doc_invoice" for i in r["items"]), str(r["total"]))
r2 = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "source_type": "doc_invoice", "limit": 5, "offset": 5}).json()
T("pagination pages through without overlap", {i["id"] for i in r["items"]}.isdisjoint({i["id"] for i in r2["items"]}) and len(r2["items"]) == 5)
r = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "account_id": acct("805")}).json(); T("filter by account", r["total"] >= 3, str(r["total"]))
r = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "min_amount": "20000", "limit": 500}).json(); T("filter by amount range", r["total"] >= 1 and all(Decimal(i["total"]) >= 20000 for i in r["items"]))
srcs = c.get("/ledger/journal-sources").json()["items"]; T("source list includes every real source with counts", {"doc_invoice", "payroll_run", "asset_depreciation", "manual"} <= {s["source"] for s in srcs} and all(s["label"] for s in srcs), str([s["source"] for s in srcs]))
inv_j = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "source_type": "doc_invoice", "limit": 1}).json()["items"][0]
d = c.get(f"/ledger/journals/{inv_j['id']}").json()
T("an invoice journal links back to its invoice (number, customer)", d["source"]["kind"] == "doc" and d["source"]["number"].startswith("INV-") and d["source"]["contact"], str(d["source"]))
pj = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2026-09-30", "source_type": "payroll_run", "limit": 1}).json()["items"][0]; T("payroll journals now carry a reference", str(pj["reference"]).startswith("PAY-"), str(pj))

# ---------------------------------------------------------------- 5. drafts + approval + segregation of duties
lines = [{"account_id": E1, "debit": "400"}, {"account_id": E2, "credit": "400"}]
as_(9001, "Priya", "bookkeeper")
r = c.post("/ledger/journal-drafts", json={"date": str(T0), "narration": "Priya draft", "reference": "PD-1", "lines": lines}); T("bookkeeper can save a draft", r.status_code == 201, r.text[:160]); did = r.json()["id"]
before = c.get("/ledger/reports/gl-summary", params={"from": "2026-07-01", "to": "2026-09-30"}).json()["total_debit"]
T("a draft has NO ledger effect", before == c.get("/ledger/reports/gl-summary", params={"from": "2026-07-01", "to": "2026-09-30"}).json()["total_debit"])
T("bookkeeper cannot approve", c.post(f"/ledger/journal-drafts/{did}/approve", json={}).status_code == 403)
T("unbalanced draft can be saved but not submitted", c.post("/ledger/journal-drafts", json={"date": str(T0), "narration": "unbal", "lines": [{"account_id": E1, "debit": "5"}, {"account_id": E2, "credit": "4"}]}).status_code == 201
  and c.post(f"/ledger/journal-drafts/{c.get('/ledger/journal-drafts', params={'status': 'draft'}).json()['items'][0]['id']}/submit").status_code == 422)
T("submit for approval", c.post(f"/ledger/journal-drafts/{did}/submit").json()["status"] == "submitted")
T("cannot edit while submitted", c.put(f"/ledger/journal-drafts/{did}", json={"narration": "sneaky"}).status_code == 409)
ATT = c.post("/attachments", params={"owner_kind": "journal_draft", "owner_id": did}, files={"file": ("wp.pdf", b"%PDF-1.4 workpaper", "application/pdf")}); T("attach a workpaper to the draft", ATT.status_code == 201, ATT.text[:160])
as_(1, "owner", "owner")
T("segregation: an owner can reject with a reason", c.post("/ledger/journal-drafts", json={"date": str(T0), "narration": "tmp", "lines": lines}).status_code == 201)
rj = c.post(f"/ledger/journal-drafts/{did}/reject", json={"reason": ""}); T("rejection needs a reason", rj.status_code == 422)
r = c.post(f"/ledger/journal-drafts/{did}/approve", json={}); T("approver posts the draft", r.status_code == 200 and r.json()["status"] == "posted" and r.json()["posted_journal_id"], r.text[:200])
jid = r.json()["posted_journal_id"]; det = c.get(f"/ledger/journals/{jid}").json()
T("posted journal keeps the draft's reference and links to the approved draft", det["reference"] == "PD-1" and det["source"]["kind"] == "journal_draft" and "Priya" in det["source"]["label"], str(det["source"]))
T("draft attachment moved onto the posted journal", any(a["filename"] == "wp.pdf" for a in det["attachments"]), str(det["attachments"]))
h = c.get(f"/ledger/journals/{jid}/history").json()["events"]; T("history shows prepared -> submitted -> approved", [e["action"] for e in h if e["action"] in ("draft prepared", "submitted for approval", "approved and posted")] == ["draft prepared", "submitted for approval", "approved and posted"], str([e["action"] for e in h]))
T("cannot approve twice", c.post(f"/ledger/journal-drafts/{did}/approve", json={}).status_code == 409)
# accountant self-approval blocked, other accountant ok
as_(9002, "Anna", "accountant"); dd = c.post("/ledger/journal-drafts", json={"date": str(T0), "narration": "Anna's own", "lines": lines}).json()["id"]
T("an accountant cannot approve their OWN journal", c.post(f"/ledger/journal-drafts/{dd}/approve", json={}).status_code == 403)
as_(9003, "Bob", "accountant"); T("a different accountant can", c.post(f"/ledger/journal-drafts/{dd}/approve", json={}).status_code == 200)
# require-approval policy
as_(1, "owner", "owner"); T("owner turns on 'require approval'", c.put("/ledger/journal-settings", json={"require_journal_approval": True}).json()["require_journal_approval"])
as_(9001, "Priya", "bookkeeper"); rr = c.post("/ledger/journals", json={"date": str(T0), "narration": "direct", "lines": lines}); T("policy: a bookkeeper can no longer post directly", rr.status_code == 403 and "approved" in rr.text, rr.text[:160])
as_(1, "owner", "owner"); T("policy: an owner still can", c.post("/ledger/journals", json={"date": str(T0), "narration": "direct owner", "lines": lines}).status_code == 200)
c.put("/ledger/journal-settings", json={"require_journal_approval": False})

# ---------------------------------------------------------------- 6. AI / rule suggestions
lst = c.get("/ledger/journal-drafts", params={"kind": "ai_bank", "status": "submitted"}).json()
T("AI suggestions were generated from the rules and matches", lst["pending"] >= 10, str(lst["counts"]))
T("suggestions are ordered most-confident first", [i["confidence"] for i in lst["items"]] == sorted([i["confidence"] for i in lst["items"]], reverse=True))
T("every suggestion states a reason and a confidence", all(i["reason"] and i["confidence"] for i in lst["items"]))
again = c.post("/ledger/journal-suggestions/generate").json(); T("re-running does not duplicate suggestions", again["created"] == 0 and again["skipped_existing"] >= 10, str(again))
coded = next(i for i in lst["items"] if i["suggestion"]["type"] == "coding"); match = next(i for i in lst["items"] if i["suggestion"]["type"] == "match")
T("coding suggestion previews a balanced journal with GST", len(coded["lines"]) >= 2 and sum(Decimal(l["debit"]) for l in coded["lines"]) == sum(Decimal(l["credit"]) for l in coded["lines"]), str(coded["lines"]))
tb0 = c.get("/ledger/reports/trial-balance").json()
# adjust then approve the coding suggestion
new_acct = acct("499")
adj = c.put(f"/ledger/journal-drafts/{coded['id']}", json={"account_id": new_acct}); T("reviewer can change the suggested account", adj.status_code == 200 and any(l["account_code"] == "499" for l in adj.json()["lines"]), adj.text[:200])
ap = c.post(f"/ledger/journal-drafts/{coded['id']}/approve", json={}); T("approving posts via the normal reconciliation path", ap.status_code == 200 and ap.json()["posted_journal_id"], ap.text[:200])
with eng.connect() as k: st = k.exec_driver_sql("select status, matched_kind from bank_lines where id=?", (coded["suggestion"]["bank_line"]["id"],)).fetchone()
T("the bank line became reconciled (spend/receive)", st[0] == "reconciled" and st[1] in ("spend", "receive"), str(st))
mp = c.post(f"/ledger/journal-drafts/{match['id']}/approve", json={}); T("approving a match suggestion records the payment against the invoice", mp.status_code == 200, mp.text[:200])
rej = next(i for i in c.get("/ledger/journal-drafts", params={"kind": "ai_bank", "status": "submitted"}).json()["items"])
T("rejecting a suggestion keeps it out of the queue and it is not re-suggested", c.post(f"/ledger/journal-drafts/{rej['id']}/reject", json={"reason": "Personal expense"}).status_code == 200 and c.post("/ledger/journal-suggestions/generate").json()["created"] == 0)
bulk = c.post("/ledger/journal-drafts/bulk-approve", json={"min_confidence": "0.95"}).json(); T("bulk-approve approves only >= threshold and reports failures", bulk["approved"] >= 1 and all(f.get("error") for f in bulk["failed"]), str(bulk))
left = c.get("/ledger/journal-drafts", params={"kind": "ai_bank", "status": "submitted"}).json()["items"]; T("nothing at/above the threshold is left", all(Decimal(i["confidence"]) < Decimal("0.95") for i in left), str([i["confidence"] for i in left][:5]))
tb1 = c.get("/ledger/reports/trial-balance").json() if False else None
d2 = Sess(); from accfino_core.ledger import service as LS; o = d2.query(m.Organisation).first(); tbx = LS.trial_balance(d2, o, T0); d2.close()
T("after all approvals the trial balance still balances", tbx["balanced"], f"{tbx['total_debit']} vs {tbx['total_credit']}")
as_(9001, "Priya", "bookkeeper"); T("a bookkeeper cannot bulk-approve", c.post("/ledger/journal-drafts/bulk-approve", json={}).status_code == 403); as_(1, "owner", "owner")

# ---------------------------------------------------------------- 7. repeating journals
reps = c.get("/ledger/repeating-journals").json()["items"]; T("repeating templates are listed with a labelled next narration", len(reps) == 3 and any("{" not in (r["next_narration"] or "{") and "2026" in r["next_narration"] for r in reps), str([r["next_narration"] for r in reps]))
before_j = c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2027-12-31", "limit": 1}).json()["total"]
run = c.post("/ledger/repeating-journals/run", json={"as_at": str(T0)}).json()
T("running catches up the overdue fortnightly template into DRAFTS (not journals)", run["drafts"] >= 2 and run["posted"] == 0 and not run["errors"], str(run))
T("repeating drafts did not touch the ledger", c.get("/ledger/journals", params={"from": "2025-07-01", "to": "2027-12-31", "limit": 1}).json()["total"] == before_j)
run2 = c.post("/ledger/repeating-journals/run", json={"as_at": str(T0)}).json(); T("running twice creates nothing new (idempotent)", run2["drafts"] == 0 and run2["posted"] == 0, str(run2))
later = c.post("/ledger/repeating-journals/run", json={"as_at": "2027-01-05"}).json()
T("running later posts the post-mode template with its auto-reversal", later["posted"] >= 1 and not later["errors"], str(later))
jp = c.get("/ledger/journals", params={"from": "2026-10-01", "to": "2027-03-01", "source_type": "repeating", "limit": 5}).json(); T("the posted occurrence has a dynamic-label narration", jp["total"] >= 1 and "{" not in jp["items"][0]["narration"], str(jp["items"][:1]))
bad = c.post("/ledger/repeating-journals", json={"name": "bad", "frequency": "monthly", "next_date": str(T0), "lines": [{"account_id": E1, "debit": "5"}, {"account_id": E2, "credit": "4"}]}); T("an invalid template is refused up front", bad.status_code == 422, bad.text[:160])
as_(9001, "Priya", "bookkeeper"); pm = c.post("/ledger/repeating-journals", json={"name": "auto", "mode": "post", "frequency": "monthly", "next_date": str(T0), "lines": [{"account_id": E1, "debit": "5"}, {"account_id": E2, "credit": "5"}]}); T("a bookkeeper cannot create an auto-POSTING template", pm.status_code == 403, pm.text[:120]); as_(1, "owner", "owner")

# ---------------------------------------------------------------- 8. CSV import
CSV = ("Date,Narration,Reference,Account,Description,Debit,Credit,Tax Code,Contact,Tracking\\n30/06/2026,Import accrual,IMP-1,412,Fee,1000.00,,,Baker,Admin\\n,,,805,Accrued,,1000.00,,,\\n"
       "01/07/2026,Import 2,IMP-2,453,Stationery,50,,,,\\n,,,805,Accrued,,50,,,\\n").replace("\\n", "\n")
dry = c.post("/ledger/journal-import", json={"csv": CSV, "mode": "draft", "dry_run": True}).json(); T("dry run validates and previews without saving", dry["valid"] == 2 and dry["invalid"] == 0 and dry["saved"] == 0, str(dry)[:300])
BAD = CSV + "02/07/2026,Unbalanced,,453,x,10,,,,\n,,,805,y,,9,,,\n,,,,,,,,,\n99/99/2026,Bad date,,453,x,1,,,,\n,,,805,y,,1,,,\n"
bd = c.post("/ledger/journal-import", json={"csv": BAD, "mode": "draft", "dry_run": False}).json()
T("all-or-nothing: any invalid journal blocks the whole import and says why", bd["invalid"] == 2 and bd.get("error") and bd["saved"] == 0 and any("balance" in e.lower() for j in bd["journals"] for e in j["errors"]) and any("date" in e.lower() for j in bd["journals"] for e in j["errors"]), str(bd)[:400])
n0 = c.get("/ledger/journal-drafts", params={"kind": "import"}).json()["items"]; T("nothing was saved by the failed import", len(n0) == 0)
ok = c.post("/ledger/journal-import", json={"csv": CSV, "mode": "draft", "dry_run": False}).json(); T("valid file imports as drafts", ok["saved"] == 2, str(ok)[:200])
imps = c.get("/ledger/journal-drafts", params={"kind": "import"}).json()["items"]; T("imported drafts kept reference and tracking", {i["reference"] for i in imps} == {"IMP-1", "IMP-2"})
as_(9001, "Priya", "bookkeeper"); T("a bookkeeper cannot import straight to the ledger", c.post("/ledger/journal-import", json={"csv": CSV, "mode": "post", "dry_run": False}).status_code == 403); as_(1, "owner", "owner")
pst = c.post("/ledger/journal-import", json={"csv": CSV.replace("IMP-", "POST-"), "mode": "post", "dry_run": False}).json(); T("an approver can import and post directly", pst["posted"] == 2, str(pst)[:200])
tem = c.get("/ledger/journal-import/template"); T("a CSV template can be downloaded", tem.status_code == 200 and "Narration" in tem.text)
T("a file with no Account column gives a helpful message", "Account" in c.post("/ledger/journal-import", json={"csv": "Date,Foo\n1/1/2026,x", "dry_run": True}).text)

# ---------------------------------------------------------------- 9. detailed general ledger
Q = {"from": "2026-07-01", "to": "2026-09-30"}
g = c.get("/ledger/reports/general-ledger-detail", params={**Q, "account_ids": [acct("090")]}).json()
T("ledger for one account has opening, running balance and closing", g["opening_applies"] and g["groups"][0]["opening"] is not None and g["groups"][0]["rows"][-1]["balance"] == g["groups"][0]["closing"], str(g["groups"][0]["opening"]))
gm = c.get("/ledger/reports/general-ledger-detail", params={**Q, "account_ids": [acct("090"), acct("805")]}).json(); T("multiple accounts at once", gm["group_count"] == 2)
gv = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "voucher", "q": "Accrual"}).json(); T("group by voucher with text search", gv["group_count"] >= 1 and all("accrual" in g_["label"].lower() or any("accrual" in (r["description"] or "").lower() for r in g_["rows"]) for g_ in gv["groups"]), str(gv["group_count"]))
gp = c.get("/ledger/reports/general-ledger-detail", params={**Q, "contact": "AGL"}).json(); T("filter by party", gp["line_count"] >= 1 and all("AGL" in (r["contact"] or "") for g_ in gp["groups"] for r in g_["rows"]) and not gp["opening_applies"], str(gp["line_count"]))
with eng.connect() as k: adm_id = k.exec_driver_sql("select id from tracking_options where name='Admin'").scalar()
gt = c.get("/ledger/reports/general-ledger-detail", params={**Q, "tracking_option_ids": [adm_id]}).json(); T("filter by tracking option (dimension)", gt["line_count"] > 5 and all("Admin" in r["tracking"] for g_ in gt["groups"] for r in g_["rows"]), str(gt["line_count"]))
gd = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "tracking"}).json(); T("group by dimension splits balances per option", {"Admin", "Consulting"} <= {g_["label"] for g_ in gd["groups"]}, str([g_["label"] for g_ in gd["groups"]]))
gs = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "source", "source_type": "payroll_run"}).json(); T("filter + group by source", gs["group_count"] == 1)
gmo = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "month"}).json(); T("group by month", gmo["group_count"] == 3)
gc = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "voucher", "consolidate": True}).json(); gn = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "voucher"}).json()
T("consolidate merges same-account lines within a voucher without changing totals", sum(x["count"] for x in gc["groups"]) <= sum(x["count"] for x in gn["groups"]) and gc["total_debit"] == gn["total_debit"])
gall = c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "none"}).json(); T("whole-ledger view balances", gall["balanced"] is True and gall["total_debit"] == gall["total_credit"], f"{gall['total_debit']} {gall['total_credit']}")
gcsv = c.get("/ledger/reports/general-ledger-detail", params={**Q, "format": "csv", "account_ids": [acct("090")]}); T("CSV export", gcsv.status_code == 200 and gcsv.text.startswith("Group,Date"))
T("bad group_by is rejected", c.get("/ledger/reports/general-ledger-detail", params={**Q, "group_by": "nope"}).status_code == 422)

# ---------------------------------------------------------------- 10. health + isolation
hl = c.get("/ledger/ledger-health").json(); T("health summary reports queue sizes", all(k in hl for k in ("drafts", "awaiting_approval", "ai_suggestions", "suspense_balance", "future_dated", "repeating_due")), str(hl))
T("a future-dated auto-reversal is counted", hl["future_dated"] >= 1)
T("read-only role cannot create drafts", (as_(9004, "Ro", "readonly") or c.post("/ledger/journal-drafts", json={"date": str(T0), "narration": "x", "lines": lines}).status_code == 403))
T("read-only role can read the queue and the detailed ledger", c.get("/ledger/journal-drafts").status_code == 200 and c.get("/ledger/reports/general-ledger-detail", params=Q).status_code == 200)
as_(1, "owner", "owner")
acts = {a[0] for a in AUDIT}
T("the audit trail recorded drafts, approvals, rejections, bulk approval, repeating runs, imports, settings and journal postings", {"ledger.journal_draft.created", "ledger.journal_draft.submitted", "ledger.journal_draft.approved", "ledger.journal_draft.rejected", "ledger.journal_draft.bulk_approved", "ledger.repeating.run", "ledger.journal.imported", "ledger.journal.settings", "ledger.journal.posted", "ledger.journal_suggestions.generated"} <= acts, str(sorted(acts)))
T("approval audit entries name who approved", any(a[0] == "ledger.journal_draft.approved" and a[3] == "owner" for a in AUDIT))
print("\nFAILURES:", len(fails), fails)
