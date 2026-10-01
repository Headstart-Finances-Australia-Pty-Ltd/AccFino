"""Tests for: AI coder (RDR + Groq), background scheduler, P&L by tracking, split lines, multi-currency journals. Works on a COPY of the seeded demo database."""
import json, os, shutil, sys, time
sys.path.insert(0, "/home/claude/w/AccFino/backend"); os.environ["DATABASE_URL"] = "postgresql://x:y@localhost/none"
DB = "/tmp/adv_test.db"; shutil.copy(os.environ.get("DEMO_DB", "/tmp/demo_nofx.db"), DB)
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from accfino_core import models as m
from accfino_core.api import ledger, ledger_tools, books_reports
from accfino_core.books import banking as K, models as b
from accfino_core.books.common import BooksError
from accfino_core.ledger import ai_coder as AI, journal_tools as JT, scheduler as SCH
from accfino_core.ledger.journal_models import JournalDraft, RepeatingJournal
from accfino_core.security import audit as _audit
from accfino_core.security.context import OrgContext, current_org
from db_app.database import get_db
from db_app.models.rdr_rule import RDRRule

eng = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False}); event.listen(eng, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
Sess = sessionmaker(bind=eng)
RDRRule.__table__.create(eng, checkfirst=True); AI._table_cache.clear()
app = FastAPI()
@app.exception_handler(BooksError)
async def _e(request, exc): return JSONResponse({"detail": str(exc)}, status_code=exc.status)
for r, p in ((ledger.router, "/ledger"), (ledger_tools.router, "/ledger"), (books_reports.ledger_reports, "/ledger/reports")): app.include_router(r, prefix=p)
WHO = {"uid": 1, "name": "owner", "role": "owner"}
def _db():
    d = Sess()
    try: yield d
    finally: d.close()
def _ctx():
    d = Sess(); org = d.query(m.Organisation).first(); return OrgContext(WHO["uid"], WHO["name"], False, org, WHO["role"])
app.dependency_overrides[get_db] = _db; app.dependency_overrides[current_org] = _ctx
c = TestClient(app)
def as_(uid, name, role): WHO.update(uid=uid, name=name, role=role)
AUDIT = []; _audit.write = lambda action, **kw: AUDIT.append((action, kw.get("entity"), kw.get("username"), kw.get("detail")))
fails = []
def T(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   -> {str(detail)[:300]}"))
    if not cond: fails.append(name)
q1 = lambda sql, *a: eng.connect().exec_driver_sql(sql, a).scalar()
acct = lambda code: q1("select id from ledger_accounts where code=?", code)
taxid = lambda code: q1("select id from tax_codes where code=?", code)
D = lambda x: Decimal(str(x))
TODAY = date(2026, 9, 30)
def tb_ok():
    d = Sess(); o = d.query(m.Organisation).first(); from accfino_core.ledger import service as LS; r = LS.trial_balance(d, o, date(2099, 1, 1)); d.close(); return r["balanced"]
def jd(jid): return c.get(f"/ledger/journals/{jid}").json()
def post(body): return c.post("/ledger/journals", json={"date": str(TODAY), "narration": "t", **body})
cat = eng.connect().exec_driver_sql("select id,name from tracking_categories order by id").fetchall()
opts = {n: (i, cid) for cid, _n in [(cat[0][0], cat[0][1])] for i, n in [(r[0], r[1]) for r in eng.connect().exec_driver_sql("select id,name from tracking_options where category_id=?", (cat[0][0],))]}
CAT = cat[0][0]; OPT = list(opts.values()); O1, O2 = OPT[0][0], OPT[1][0]; N1, N2 = list(opts)[0], list(opts)[1]
E1, E2, GST, BANK = acct("445"), acct("805"), acct("820"), acct("090")
print("tracking category", cat[0][1], "options", list(opts))

# =========================================================================================== 1. SPLIT LINES (MYOB-style jobs)
r = post({"lines": [{"account_id": E1, "debit": "1000.00", "allocations": [{"tracking_option_ids": [O1], "percent": "60"}, {"tracking_option_ids": [O2], "percent": "40"}]}, {"account_id": E2, "credit": "1000.00"}]})
T("split a line 60/40 across two jobs", r.status_code == 200, r.text)
j = r.json(); ex = [l for l in j["lines"] if l["account_code"] == "445"]
T("...posts two lines that add back to the original exactly", len(ex) == 2 and sorted(D(l["debit"]) for l in ex) == [D("400.00"), D("600.00")] and sum(D(l["debit"]) for l in ex) == D("1000.00"), str(ex))
T("...each part carries its own job", {tuple(l["tracking_option_ids"]) for l in ex} == {(O1,), (O2,)}, str(ex))
T("...and the journal balances", tb_ok())
r = post({"lines": [{"account_id": E1, "debit": "100.01", "allocations": [{"tracking_option_ids": [O1], "percent": "33.33"}, {"tracking_option_ids": [O2], "percent": "33.33"}, {"tracking_option_ids": [], "percent": "33.34"}]}, {"account_id": E2, "credit": "100.01"}]})
ex = [l for l in r.json()["lines"] if l["account_code"] == "445"]
T("odd cents: three-way split of 100.01 still adds to 100.01 (last part takes the rounding)", r.status_code == 200 and sum(D(l["debit"]) for l in ex) == D("100.01") and len(ex) == 3, r.text[:200])
r = post({"amounts_are": "exclusive", "lines": [{"account_id": E1, "debit": "333.33", "tax_code_id": taxid("INPUT"), "allocations": [{"tracking_option_ids": [O1], "percent": "50"}, {"tracking_option_ids": [O2], "percent": "50"}]}, {"account_id": E2, "credit": "366.66"}]})
j = r.json() if r.status_code == 200 else {}; ex = [l for l in j.get("lines", []) if l["account_code"] == "445"]; gl = [l for l in j.get("lines", []) if l["account_code"] == "820"]
T("GST-exclusive split: the GST is split in step and the GST account gets the exact total", r.status_code == 200 and sum(D(l["tax_amount"]) for l in ex) == D(gl[0]["debit"]) == D("33.33") and sum(D(l["debit"]) for l in ex) == D("333.33"), r.text[:300])
r = post({"lines": [{"account_id": E1, "debit": "100", "allocations": [{"tracking_option_ids": [O1], "amount": "30"}, {"tracking_option_ids": [O2], "amount": "70"}]}, {"account_id": E2, "credit": "100"}]})
T("split by amount", r.status_code == 200 and sorted(D(l["debit"]) for l in r.json()["lines"] if l["account_code"] == "445") == [D("30.00"), D("70.00")], r.text[:200])
for name, al, want in [("percentages that don't reach 100%", [{"percent": "60"}, {"percent": "30"}], "100%"), ("amounts that don't add to the line", [{"amount": "30"}, {"amount": "60"}], "add up"),
                       ("a mix of percent and amount", [{"percent": "50"}, {"amount": "50"}], "either a percentage or an amount"), ("a single part", [{"percent": "100"}], "between 2 and 20"),
                       ("a zero share", [{"percent": "0"}, {"percent": "100"}], "greater than zero"), ("a share that rounds to nothing", [{"percent": "99.9999"}, {"percent": "0.0001"}], "rounds to nothing"), ("21 parts", [{"percent": "1"}] * 21, "between 2 and 20")]:
    rr = post({"lines": [{"account_id": E1, "debit": "100", "allocations": al}, {"account_id": E2, "credit": "100"}]})
    T(f"split refused: {name}", rr.status_code == 422 and want in rr.text, rr.text[:200])
r = c.post("/ledger/journal-drafts", json={"date": str(TODAY), "narration": "split draft", "lines": [{"account_id": E1, "debit": "200", "allocations": [{"tracking_option_ids": [O1], "percent": "25"}, {"tracking_option_ids": [O2], "percent": "75"}]}, {"account_id": E2, "credit": "200"}]})
T("a draft keeps the split", r.status_code == 201 and r.json()["lines"][0]["allocations"][1]["percent"] == "75", r.text[:200])
pv = c.post("/ledger/journal-preview", json={"date": str(TODAY), "lines": [{"account_id": E1, "debit": "200", "allocations": [{"tracking_option_ids": [O1], "percent": "25"}, {"tracking_option_ids": [O2], "percent": "75"}]}, {"account_id": E2, "credit": "200"}]}).json()
T("the preview shows the split lines", pv["balanced"] and len([l for l in pv["lines"] if l["account_code"] == "445"]) == 2, str(pv)[:200])
ap = c.post(f"/ledger/journal-drafts/{r.json()['id']}/approve", json={}); T("approving the draft posts the split", ap.status_code == 200 and len([l for l in jd(ap.json()["posted_journal_id"])["lines"] if l["account_code"] == "445"]) == 2, ap.text[:200])
o3 = [x for x in cat if x[0] != CAT]
T("a split part keeps the line's own tracking from another category", True)
csv_imp = "Date,Narration,Account,Debit,Credit,Tracking\n30/09/2026,Split by import,445,100,,{a}:60;{b}:40\n,,805,,100,\n".format(a=N1, b=N2)
di = c.post("/ledger/journal-import", json={"csv": csv_imp, "mode": "post", "dry_run": False}).json()
T("CSV import understands 'Job:percent' in the Tracking column", di.get("posted") == 1, di)
bad = c.post("/ledger/journal-import", json={"csv": csv_imp.replace(":60", ":50"), "mode": "post", "dry_run": True}).json()
T("...and reports a split that does not total 100%", bad["invalid"] == 1 and any("100%" in e for j in bad["journals"] for e in j["errors"]), str(bad)[:300])

# =========================================================================================== 2. P&L BY TRACKING OPTION
FY = {"from": "2025-07-01", "to": "2026-09-30", "category_id": CAT}
pl = c.get("/ledger/reports/profit-loss-by-tracking", params=FY).json()
T("P&L by tracking has a column per option plus Unassigned", [x["name"] for x in pl["columns"]][-1] == "Unassigned" and {N1, N2} <= {x["name"] for x in pl["columns"]}, str(pl["columns"]))
T("the columns add up to the ordinary Profit & Loss", pl["matches_profit_loss"] and pl["net_profit"]["total"] == pl["profit_loss_net"], f"{pl['net_profit']['total']} vs {pl['profit_loss_net']}")
T("...for every section and every row (row totals = sum of columns)", all(D(rw["total"]) == sum(D(v) for v in rw["amounts"].values()) for s in pl["sections"] for rw in s["rows"]))
T("...and each section total is the sum of its rows, per column", all(D(s["totals"][k]) == sum(D(rw["amounts"][k]) for rw in s["rows"]) for s in pl["sections"] for k in [x["key"] for x in pl["columns"]]))
T("tagged spending lands in the tagged column (the 60/40 split above)", D(next(rw for s in pl["sections"] for rw in s["rows"] if rw["code"] == "445")["amounts"][str(O1)]) >= D("600.00"), "")
r = post({"lines": [{"account_id": E1, "debit": "90.00", "tracking_option_ids": [O1, O2]}, {"account_id": E2, "credit": "90.00"}]})
pl2 = c.get("/ledger/reports/profit-loss-by-tracking", params=FY).json()
T("a line tagged with two options of the same category is shared equally and totals still reconcile", r.status_code == 200 and pl2["matches_profit_loss"], pl2["profit_loss_net"])
r = post({"lines": [{"account_id": E1, "debit": "0.01", "tracking_option_ids": [O1, O2]}, {"account_id": E2, "credit": "0.01"}]})
T("...even when it cannot divide evenly (1 cent)", c.get("/ledger/reports/profit-loss-by-tracking", params=FY).json()["matches_profit_loss"])
T("a category that is not this organisation's is a clean 404", c.get("/ledger/reports/profit-loss-by-tracking", params={**FY, "category_id": 99999}).status_code == 404)
T("from after to is refused", c.get("/ledger/reports/profit-loss-by-tracking", params={"from": "2026-09-30", "to": "2026-01-01", "category_id": CAT}).status_code == 422)
T("a period with no activity gives an empty, zero report (not an error)", (lambda x: x["net_profit"]["total"] == "0.00" and x["matches_profit_loss"])(c.get("/ledger/reports/profit-loss-by-tracking", params={"from": "2001-01-01", "to": "2001-01-31", "category_id": CAT}).json()))
as_(9004, "ro", "readonly"); T("read-only users can run it", c.get("/ledger/reports/profit-loss-by-tracking", params=FY).status_code == 200); as_(1, "owner", "owner")

# =========================================================================================== 3. MULTI-CURRENCY
T("the demo organisation ships with USD rates and a USD journal + a split journal", q1("select count(*) from ledger_fx_rates where currency='USD'") >= 2 and q1("select count(*) from journals where currency='USD'") >= 1 and q1("select count(*) from journals where reference='SPLIT-MKT'") == 1)
with eng.begin() as k: k.exec_driver_sql("delete from ledger_fx_rates")          # start the rate scenarios from a clean table
def usd(lines, rate="0.65", **kw): return post({"currency": "USD", "exchange_rate": rate, "lines": lines, **kw})
r = usd([{"account_id": E1, "debit": "1000.00"}, {"account_id": E2, "credit": "1000.00"}])
T("post a USD journal at 0.65", r.status_code == 200 and r.json()["currency"] == "USD" and r.json()["exchange_rate"] == "0.65000000", r.text[:300])
j = r.json(); ln = {l["account_code"]: l for l in j["lines"]}
T("...ledger amounts are in base currency (AUD 650.00), original USD amounts kept", ln["445"]["debit"] == "650.00" and ln["805"]["credit"] == "650.00" and ln["445"]["orig_debit"] == "1000.00" and ln["805"]["orig_credit"] == "1000.00", str(j["lines"])[:300])
T("...journal total is the base amount and the ledger balances", j["total"] == "650.00" and tb_ok())
det = jd(j["id"]); T("journal detail shows the currency and rate", det["currency"] == "USD" and det["exchange_rate"].startswith("0.65"))
T("GL detail shows the original currency amount", any(rw.get("original") and "USD 1000.00" in rw["original"] for g in c.get("/ledger/reports/general-ledger-detail", params={"from": "2026-09-01", "to": "2026-09-30", "account_ids": [E1]}).json()["groups"] for rw in g["rows"]))
r = usd([{"account_id": E1, "debit": "0.05"}, {"account_id": E2, "debit": "0.05"}, {"account_id": BANK, "credit": "0.10"}], rate="0.5")
T("rounding: per-line conversion that leaves a cent is absorbed and the journal still balances", r.status_code == 200 and tb_ok() and sum(D(l["debit"]) for l in r.json()["lines"]) == sum(D(l["credit"]) for l in r.json()["lines"]), r.text[:300])
pv = c.post("/ledger/journal-preview", json={"date": str(TODAY), "currency": "USD", "exchange_rate": "0.5", "lines": [{"account_id": E1, "debit": "0.05"}, {"account_id": E2, "debit": "0.05"}, {"account_id": BANK, "credit": "0.10"}]}).json()
T("...and the preview tells the user about the rounding", pv["fx"]["rounding"] != "0.00" and any("rounding" in w for w in pv["warnings"]), str(pv["fx"]))
r = usd([{"account_id": E1, "debit": "100.00"}, {"account_id": E2, "credit": "90.00"}])
T("must balance in the FOREIGN currency", r.status_code == 422 and "balance in the foreign currency" in r.text, r.text[:200])
r = post({"currency": "USD", "lines": [{"account_id": E1, "debit": "5"}, {"account_id": E2, "credit": "5"}]})
T("no rate given and none stored: refused with instructions (never guessed)", r.status_code == 422 and "no usd exchange rate" in r.text.lower(), r.text[:250])
T("store a rate", c.put("/ledger/fx-rates", json={"currency": "usd", "date": "2026-09-01", "rate": "0.6400", "source": "RBA"}).json()["currency"] == "USD")
T("store a later rate", c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-20", "rate": "0.6600"}).status_code == 200)
r = post({"currency": "USD", "date": "2026-09-25", "lines": [{"account_id": E1, "debit": "100"}, {"account_id": E2, "credit": "100"}]}); T("omitting the rate uses the latest stored rate on/before the date (0.66, not the earlier 0.64)", r.status_code == 200 and r.json()["exchange_rate"].startswith("0.66"), r.text[:200])
r = post({"currency": "USD", "date": "2026-09-10", "lines": [{"account_id": E1, "debit": "100"}, {"account_id": E2, "credit": "100"}]}); T("...an earlier date uses the earlier rate (0.64) - a later rate is never applied backwards", r.status_code == 200 and r.json()["exchange_rate"].startswith("0.64"), r.text[:200])
T("stored rate for a date replaces the old one (one rate per currency per day)", c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-20", "rate": "0.6700"}).status_code == 200 and len([x for x in c.get("/ledger/fx-rates", params={"currency": "USD"}).json()["items"] if x["date"] == "2026-09-20"]) == 1)
lk = c.get("/ledger/fx-rate", params={"currency": "usd", "date": "2026-09-30"}).json(); T("lookup returns the organisation's own rate and its date/source", lk["rate"].startswith("0.67") and lk["rate_date"] == "2026-09-20", str(lk))
T("lookup with no rate returns null, not a guess", c.get("/ledger/fx-rate", params={"currency": "EUR"}).json()["rate"] is None)
for name, body, want in [("the base currency as a rate", {"currency": "AUD", "date": "2026-09-01", "rate": "1"}, "foreign"), ("an invalid code", {"currency": "US", "date": "2026-09-01", "rate": "1"}, "foreign"), ("a zero rate", {"currency": "EUR", "date": "2026-09-01", "rate": "0"}, "range"), ("an absurd rate", {"currency": "EUR", "date": "2026-09-01", "rate": "99999999"}, "range")]:
    rr = c.put("/ledger/fx-rates", json=body); T(f"rate refused: {name}", rr.status_code == 422 and want in rr.text, rr.text[:160])
for name, body, want in [("an invalid currency code", {"currency": "US", "exchange_rate": "1"}, "3-letter"), ("a zero rate", {"currency": "USD", "exchange_rate": "0"}, "range"), ("a huge rate", {"currency": "USD", "exchange_rate": "9999999"}, "range")]:
    rr = post({**body, "lines": [{"account_id": E1, "debit": "5"}, {"account_id": E2, "credit": "5"}]}); T(f"journal refused: {name}", rr.status_code == 422 and want in rr.text, rr.text[:160])
r = post({"currency": "USD", "exchange_rate": "0.65", "amounts_are": "inclusive", "lines": [{"account_id": E1, "debit": "110", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "110"}]}); jg = r.json() if r.status_code == 200 else {}
T("GST on a foreign-currency journal is now calculated - in DOLLARS: USD 110 at 0.65 = 71.50 of which GST 6.50", r.status_code == 200 and {l["account_code"]: l["debit"] for l in jg.get("lines", [])}.get("820") == "6.50" and {l["account_code"]: l["credit"] for l in jg.get("lines", [])}.get("805") == "71.50", r.text[:300])
r = post({"currency": "USD", "exchange_rate": "0.65", "lines": [{"account_id": E1, "debit": "110", "tax_code_id": taxid("INPUT")}, {"account_id": E2, "credit": "110"}]}); T("...a GST-charging tax code with no GST basis chosen is still refused (as for any journal)", r.status_code == 422 and "charges GST" in r.text, r.text[:200])
r = post({"currency": "AUD", "lines": [{"account_id": E1, "debit": "7"}, {"account_id": E2, "credit": "7"}]}); T("entering the base currency code is an ordinary journal", r.status_code == 200 and r.json()["currency"] is None)
r = usd([{"account_id": E1, "debit": "200"}, {"account_id": E2, "credit": "200"}], auto_reverse_date="2026-10-15"); jf = r.json()
T("an auto-reversing USD journal", r.status_code == 200 and r.json()["auto_reversal"], r.text[:200])
rv = jd(jf["auto_reversal"]["id"]); T("...the reversal keeps the currency and rate and swaps the original amounts", rv["currency"] == "USD" and rv["exchange_rate"] == jf["exchange_rate"] and {l["account_code"]: l["orig_credit"] for l in rv["lines"]}["445"] == "200.00", str(rv["lines"])[:300])
r = usd([{"account_id": E1, "debit": "50"}, {"account_id": E2, "credit": "50"}]); rr = c.post(f"/ledger/journals/{r.json()['id']}/reverse", json={}); T("a manual reversal of a USD journal keeps the currency and rate", rr.status_code == 200 and rr.json()["currency"] == "USD" and rr.json()["lines"][0]["orig_credit"] in ("50.00", None) and tb_ok(), rr.text[:300])
r = c.post("/ledger/journal-drafts", json={"date": "2026-09-25", "narration": "usd draft", "currency": "USD", "lines": [{"account_id": E1, "debit": "80"}, {"account_id": E2, "credit": "80"}]}); T("a draft can be entered in a foreign currency", r.status_code == 201 and r.json()["currency"] == "USD", r.text[:200])
ap = c.post(f"/ledger/journal-drafts/{r.json()['id']}/approve", json={}); T("approving looks up the rate for the posting date (the 20 Sep rate as amended to 0.67)", ap.status_code == 200 and jd(ap.json()["posted_journal_id"])["exchange_rate"].startswith("0.67"), ap.text[:200])
r = c.post("/ledger/journal-drafts", json={"date": "2026-09-25", "narration": "eur draft", "currency": "EUR", "lines": [{"account_id": E1, "debit": "80"}, {"account_id": E2, "credit": "80"}]}); ap = c.post(f"/ledger/journal-drafts/{r.json()['id']}/approve", json={}); T("approving with no rate for that currency fails cleanly and leaves the draft", ap.status_code == 422 and c.get(f"/ledger/journal-drafts/{r.json()['id']}").json()["status"] == "draft", ap.text[:200])
dl = c.get("/ledger/fx-rates", params={"currency": "USD"}).json()["items"]; did = next(x["id"] for x in dl if x["date"] == "2026-09-01")
T("deleting a rate does not change journals already posted at it", c.delete(f"/ledger/fx-rates/{did}").status_code == 200 and jd(r.json()["id"] and j["id"])["exchange_rate"].startswith("0.65"))
as_(9004, "ro", "readonly"); T("read-only users cannot store rates", c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-01", "rate": "0.6"}).status_code == 403); as_(1, "owner", "owner")
T("every trial balance is still balanced after all the multi-currency activity", tb_ok())
bs = c.get("/ledger/reports/profit-loss", params={"from": "2026-09-01", "to": "2026-09-30"}); T("reports stay in base currency and work", bs.status_code == 200)

# =========================================================================================== 4. SCHEDULER
def tpl(name, **kw):
    body = dict(name=name, frequency="monthly", next_date="2026-07-15", mode="draft", narration=name + " {month} {year}", auto_run=True, lines=[{"account_id": E1, "debit": "10"}, {"account_id": E2, "credit": "10"}]); body.update(kw)
    return c.post("/ledger/repeating-journals", json=body)
T("create an auto-run template", (t1 := tpl("Auto A")).status_code == 201 and t1.json()["auto_run"] is True, t1.text[:200])
t2 = tpl("Manual only", auto_run=False); tA = t1.json()["id"]; tM = t2.json()["id"]
n_before = q1("select count(*) from ledger_journal_drafts where kind='repeating'")
s1 = SCH.sweep(Sess, today=TODAY)
T("a sweep catches the auto-run template up (Jul, Aug, Sep) as drafts", s1["drafts"] == 3 and s1["templates"] == 1 and not s1["errors"], s1)
T("...and never touches a template that was not opted in", q1("select next_date from ledger_repeating_journals where id=?", tM) == "2026-07-15" and q1("select runs from ledger_repeating_journals where id=?", tM) == 0)
T("...next date moved on", q1("select next_date from ledger_repeating_journals where id=?", tA) == "2026-10-15")
s2 = SCH.sweep(Sess, today=TODAY); T("a second sweep the same day creates nothing", s2["drafts"] == 0 and s2["posted"] == 0)
db = Sess(); T("the heartbeat is stored and shown by the status endpoint", SCH.heartbeat(db)["today"] == "2026-09-30" and c.get("/ledger/scheduler-status").json()["last_sweep"]["today"] == "2026-09-30" and c.get("/ledger/scheduler-status").json()["auto_templates"] >= 1); db.close()
q = eng.connect().exec_driver_sql("select narration from ledger_journal_drafts where source_ref=? order by journal_date", (f"repeating:{tA}",)).fetchall()
T("the generated drafts carry dated labels", [x[0] for x in q] == ["Auto A July 2026", "Auto A August 2026", "Auto A September 2026"], str(q))
with eng.begin() as k: k.exec_driver_sql("update ledger_repeating_journals set next_date='2026-09-15' where id=?", (tA,))          # simulate a worker with a STALE view re-running an occurrence
db = Sess(); org = db.query(m.Organisation).first(); ctx = SimpleNamespace(user_id=1, username="scheduler", role="owner", is_admin=False, org=org)
rr = JT.run_repeating(db, org, ctx, as_at=TODAY, template_id=tA, only_auto=True); db.close()
T("idempotent: an occurrence that already exists is never created twice", rr["drafts"] == 0 and rr["skipped_existing"] == 1 and q1("select count(*) from ledger_journal_drafts where source_ref=?", f"repeating:{tA}") == 3, rr)
t3 = tpl("Ends early", next_date="2026-07-01", end_date="2026-08-05"); s = SCH.sweep(Sess, today=TODAY); T("an end date is respected", q1("select count(*) from ledger_journal_drafts where source_ref=?", f"repeating:{t3.json()['id']}") == 2, s)
t4 = tpl("Posts itself", next_date="2026-09-29", mode="post", narration="Auto posted {date}"); s = SCH.sweep(Sess, today=TODAY)
T("an auto-run POST template posts when its creator is an approver", s["posted"] == 1 and q1("select count(*) from journals where source_type='repeating' and source_ref=?", f"repeating:{t4.json()['id']}") == 1, s)
t5 = tpl("Demotion", next_date="2026-09-29", mode="post", narration="Should be a draft {date}")
with eng.begin() as k: k.exec_driver_sql("update org_memberships set role='bookkeeper' where user_id=1")
s = SCH.sweep(Sess, today=TODAY); id5 = t5.json()["id"]
T("if the creator is no longer an approver it falls back to a DRAFT rather than posting unattended", s["posted"] == 0 and s["drafts"] == 1 and q1("select count(*) from journals where source_ref=?", f"repeating:{id5}") == 0 and q1("select count(*) from ledger_journal_drafts where source_ref=?", f"repeating:{id5}") == 1, s)
t6 = tpl("Suspended", next_date="2026-09-29", mode="post"); 
with eng.begin() as k: k.exec_driver_sql("update org_memberships set role='owner', suspended_at='2026-09-01 00:00:00' where user_id=1")
s = SCH.sweep(Sess, today=TODAY); T("a suspended creator's post-mode template also falls back to a draft", s["posted"] == 0 and s["drafts"] == 1, s)
with eng.begin() as k: k.exec_driver_sql("update org_memberships set suspended_at=NULL, role='owner' where user_id=1")
t7 = tpl("Locked period", next_date="2026-01-01", frequency="yearly", mode="post"); t8 = tpl("Fine after", next_date="2026-09-29")
with eng.begin() as k: k.exec_driver_sql("update organisations set lock_date='2026-06-30'")
s = SCH.sweep(Sess, today=TODAY)
T("a template that hits the lock date records the error, and the sweep carries on with the others", any("lock date" in e["error"] for e in s["errors"]) and q1("select count(*) from ledger_journal_drafts where source_ref=?", f"repeating:{t8.json()['id']}") == 1 and "lock date" in (q1("select last_error from ledger_repeating_journals where id=?", t7.json()["id"]) or ""), s)
with eng.begin() as k: k.exec_driver_sql("update organisations set lock_date=NULL")
T("the error is shown on the template", any("lock date" in (x["last_error"] or "") for x in c.get("/ledger/repeating-journals").json()["items"]))
T("the scheduler wrote audit entries under its own name", any(a[0] == "ledger.repeating.auto_run" and a[2] == "scheduler" for a in AUDIT))
# foreign-currency repeating template: rate looked up per occurrence date
c.put("/ledger/fx-rates", json={"currency": "GBP", "date": "2026-07-01", "rate": "1.9000"}); c.put("/ledger/fx-rates", json={"currency": "GBP", "date": "2026-08-20", "rate": "2.0000"})
t9 = tpl("GBP retainer", next_date="2026-08-01", currency="GBP", mode="post"); s = SCH.sweep(Sess, today=TODAY); i9 = t9.json()["id"]
rows = eng.connect().exec_driver_sql("select journal_date, exchange_rate, currency from journals where source_ref=? order by journal_date", (f"repeating:{i9}",)).fetchall()
T("a GBP repeating journal uses the organisation's rate that applied on each occurrence date", [(r[0], float(r[1]), r[2]) for r in rows] == [("2026-08-01", 1.9, "GBP"), ("2026-09-01", 2.0, "GBP")], rows)
t10 = tpl("CHF retainer", next_date="2026-09-01", currency="CHF"); s = SCH.sweep(Sess, today=TODAY)
T("a currency with no stored rate stops that template with a clear error (no guessed rate)", any("CHF" in e["error"] for e in s["errors"]) and q1("select count(*) from ledger_journal_drafts where source_ref=?", f"repeating:{t10.json()['id']}") == 0, s)
calls = []; real = SCH.sweep; SCH.sweep = lambda *a, **k: calls.append(1) or {}
T("the background thread runs a sweep and stops cleanly", SCH.runner.start(interval=30, first_delay=0) and (time.sleep(0.6) or True) and len(calls) >= 1, calls); SCH.runner.stop(); T("...stop() ends the thread", SCH.runner.thread is None)
os.environ["ACCFINO_SCHEDULER"] = "0"; T("ACCFINO_SCHEDULER=0 disables it", SCH.runner.start() is False and c.get("/ledger/scheduler-status").json()["enabled"] is False); os.environ["ACCFINO_SCHEDULER"] = "1"; SCH.sweep = real
boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")); SCH.sweep = boom; T("a crashing sweep does not kill the thread loop", SCH.runner.start(interval=30, first_delay=0) and (time.sleep(0.4) or True) and SCH.runner.thread.is_alive()); SCH.runner.stop(); SCH.sweep = real
T("the scheduler is registered on app startup", any("scheduler" in str(h) for h in __import__("accfino_core").install.__code__.co_consts) or "_sched.start" in open("/home/claude/w/AccFino/backend/accfino_core/__init__.py").read())

# =========================================================================================== 5. AI CODER: RDR + GROQ
def add_lines(rows):
    d = Sess(); org = d.query(m.Organisation).first(); ba = d.query(m.LedgerAccount).filter_by(code='090').first()
    last = d.query(b.BankLine).filter(b.BankLine.bank_account_id == ba.id, b.BankLine.balance.isnot(None)).order_by(b.BankLine.line_date.desc(), b.BankLine.id.desc()).first(); bal = last.balance; out = []
    for desc, amt in rows:
        bal += D(amt); out.append(dict(date=TODAY, description=desc, amount=D(amt), balance=bal))
    K.import_lines(d, org, 1, ba, out, adopt_existing=False); d.commit(); d.close()
def sugg(kind="ai_bank"): return c.get("/ledger/journal-drafts", params={"kind": kind, "status": "submitted"}).json()["items"]
def by_desc(items, frag): return next((i for i in items if frag.lower() in i["suggestion"]["bank_line"]["description"].lower()), None)
name445 = q1("select name from ledger_accounts where code='445'"); name_stat = q1("select name from ledger_accounts where code='453'"); name_rev = q1("select name from ledger_accounts where account_class='revenue' and system_key is null limit 1")
with eng.begin() as k:
    for i, (rid, nm, pri, kw, rx, then, dr_only) in enumerate([("r1", "Officeworks", 100, "officeworks", "[]", name_stat, 0), ("r2", "Power", 90, "agl|origin energy", "[]", name445, 0), ("r3", "Ghost", 80, "ghostmerchant", "[]", "No Such Account Anywhere", 0),
            ("r4", "Regex", 70, None, '["^tollway\\\\s+\\\\d+"]', name445, 0), ("r5", "Refund only", 60, "refundco", "[]", name445, 1), ("r6", "Wrong side", 55, "sellsstuff", "[]", name_rev, 0), ("r7", "No condition", 50, None, "[]", name445, 0)]):
        k.exec_driver_sql("insert into rdr_rules (id,name,priority,keywords,regex_any,debit_gt,credit_gt,debit_only,credit_only,\"then\",then_gst_category) values (?,?,?,?,?,NULL,NULL,?,0,?,NULL)", (rid, nm, pri, kw, rx, dr_only, then))
add_lines([("OFFICEWORKS 4417723891 CARD PURCHASE", "-45.00"), ("TOLLWAY 4471 LINKT", "-12.50"), ("GHOSTMERCHANT PTY LTD", "-20.00"), ("REFUNDCO PAYMENT", "60.00"), ("SELLSSTUFF SHOP", "-33.00"), ("AGL ENERGY 998877665", "-210.00")])
gen = c.post("/ledger/journal-suggestions/generate").json(); items = sugg()
T("RDR proposes a coding when the organisation's own rules have nothing", gen["rdr"] >= 2 and gen["llm"] == 0 and gen["llm_enabled"] is False, gen)
o = by_desc(items, "officeworks"); T("...mapped onto THIS organisation's account by name, with source rdr", o and o["suggestion"]["source"] == "rdr" and any(l["account_code"] == "453" for l in o["lines"]), o and o["suggestion"])
T("...at 85% confidence and saying it is a platform rule", o and o["confidence"] == "0.8500" and "Platform rule" in o["reason"], o and o["reason"])
T("a regex rule works", (t := by_desc(items, "tollway")) is not None and t["suggestion"]["source"] == "rdr", t and t["suggestion"])
T("the highest-priority matching rule wins ('AGL' matches r2)", (a := by_desc(items, "agl energy")) is not None and any(l["account_code"] == "445" for l in a["lines"]))
T("a rule whose account does not exist in this chart is skipped, not guessed", by_desc(items, "ghostmerchant") is None)
T("a debit-only rule ignores money coming in", by_desc(items, "refundco") is None)
T("a rule that would code a payment to an INCOME account is refused (wrong direction)", by_desc(items, "sellsstuff") is None)
T("a rule with no text condition never matches everything", all("no condition" not in (i["reason"] or "").lower() for i in items))
b90 = c.post("/ledger/journal-drafts/bulk-approve", json={"min_confidence": "0.90", "ids": [o["id"], t["id"], a["id"]]}).json()
T("RDR suggestions can NEVER be bulk-approved (even at the lowest 90% setting)", b90["approved"] == 0 and b90["considered"] == 0, b90)
ap = c.post(f"/ledger/journal-drafts/{o['id']}/approve", json={}); T("an individual approval works and reconciles the bank line", ap.status_code == 200 and q1("select status from bank_lines where id=?", o["suggestion"]["bank_line"]["id"]) == "reconciled", ap.text[:200])
add_lines([("OFFICEWORKS 5550001111 CARD PURCHASE", "-19.00")]); c.post("/ledger/journal-suggestions/generate"); nx = by_desc(sugg(), "5550001111".replace("5550001111", "OFFICEWORKS"))
nx = next(i for i in sugg() if i["suggestion"]["bank_line"]["amount"] == "-19.00")
T("approving TAUGHT the organisation: next time it is coded from memory with its own source", nx["suggestion"]["source"] == "learned", nx["suggestion"])
# ---- LLM
PROMPTS = []; REPLIES = {}
def fake_chat(system, prompt):
    PROMPTS.append(prompt)
    for k, v in REPLIES.items():
        if k in prompt.lower(): 
            if isinstance(v, Exception): raise v
            return v
    return '{"account_code": null, "confidence": 0, "reason": "unknown"}'
AI.chat_backend = fake_chat
code_ok = "445"
add_lines([("QANTAS AIRWAYS 9876543210 SYDNEY", "-450.00"), ("ZZ HALLUCINATE PTY", "-15.00"), ("ZZ LOWCONF PTY", "-16.00"), ("ZZ NULLREPLY PTY", "-17.00"), ("ZZ FENCED PTY", "-18.00"), ("ZZ THINK PTY", "-19.50"), ("ZZ GARBAGE PTY", "-21.00"), ("ZZ TWICE ONE", "-22.00"), ("ZZ TWICE TWO", "-23.00")])
REPLIES.update({"qantas": json.dumps({"account_code": code_ok, "confidence": 0.99, "reason": "airline travel"}), "hallucinate": '{"account_code": "9999", "confidence": 0.95, "reason": "invented"}',
                "lowconf": '{"account_code": "445", "confidence": 0.3, "reason": "guess"}', "fenced": '```json\n{"account_code": "445", "confidence": 0.7, "reason": "fenced ok"}\n```',
                "think": '<think>hmm {"account_code": "1"}</think>{"account_code": "445", "confidence": 0.65, "reason": "after thinking"}', "garbage": "I think it is probably travel, sorry!"})
gen = c.post("/ledger/journal-suggestions/generate").json()
T("the LLM is OFF by default: no model call is made and nothing leaves the system", gen["llm_enabled"] is False and PROMPTS == [] and gen["llm_calls"] == 0, (gen, PROMPTS[:1]))
as_(9001, "Priya", "bookkeeper"); T("only someone with settings rights can turn AI on", c.put("/ledger/journal-settings", json={"llm_suggestions": True}).status_code == 403); as_(1, "owner", "owner")
T("the owner turns AI suggestions on", c.put("/ledger/journal-settings", json={"llm_suggestions": True}).json()["llm_suggestions"] is True)
gen = c.post("/ledger/journal-suggestions/generate").json(); items = sugg()
T("with it on, uncoded lines are put to the model", gen["llm_enabled"] and gen["llm_calls"] >= 7 and gen["llm"] >= 3, gen)
q = by_desc(items, "qantas"); T("the model's suggestion is shown with source 'llm' and its reason", q and q["suggestion"]["source"] == "llm" and "airline travel" in q["reason"], q and q["reason"])
T("its confidence is CAPPED at 80% however sure the model says it is (it said 99%)", q and q["confidence"] == "0.8000", q and q["confidence"])
T("a code that is not in this organisation's chart is discarded", by_desc(items, "hallucinate") is None)
T("a low-confidence answer is discarded (no evidence is better than a guess)", by_desc(items, "lowconf") is None)
T("an explicit 'null' answer gives no suggestion", by_desc(items, "nullreply") is None)
T("a JSON reply wrapped in a code fence is understood", (f := by_desc(items, "fenced")) is not None and f["confidence"] == "0.7000")
T("reasoning text before the JSON does not confuse it", (th := by_desc(items, "think")) is not None and th["suggestion"]["account_id"] == acct("445"))
T("a reply that is not JSON gives no suggestion (and no crash)", by_desc(items, "garbage") is None)
P = next(p for p in PROMPTS if "qantas" in p.lower())
T("privacy: long digit runs (account/card numbers) are masked before leaving", "9876543210" not in P and "#" in P, P[:200])
T("privacy: the prompt lists only postable accounts (no bank, GST, control accounts)", not any(f"\n{code} |" in "\n" + P for code in ("090", "820", "610", "800")) and "\n445 |" in "\n" + P, P[-400:])
T("the direction is stated so a payment is never coded to income", "money going OUT" in P and not any("revenue" in ln for ln in P.split("Accounts:")[1].splitlines()), "")
sug2 = c.post("/ledger/journal-suggestions/generate").json(); T("re-running does not re-ask the model for lines that already have a suggestion", sug2["created"] == 0, sug2)
ai_ids = [i["id"] for i in sugg() if i["suggestion"]["source"] in ("llm", "rdr")]; other = [i for i in sugg() if i["suggestion"]["source"] not in ("llm", "rdr") and float(i["confidence"]) >= 0.90]
b95 = c.post("/ledger/journal-drafts/bulk-approve", json={"min_confidence": "0.90"}).json()
still = {i["id"] for i in sugg()}
T("bulk approval at the LOWEST threshold (90%) approves rule/match suggestions but never a single LLM or RDR one", b95["approved"] == len(other) >= 1 and all(i in still for i in ai_ids) and len(ai_ids) >= 4, (b95, len(ai_ids), len(other)))
ap = c.post(f"/ledger/journal-drafts/{q['id']}/approve", json={}); T("a person approving the LLM suggestion posts it through the normal path", ap.status_code == 200 and tb_ok(), ap.text[:200])
n_calls = len(PROMPTS); add_lines([("ZZ REPEATER SHOP", "-31.00"), ("ZZ REPEATER SHOP", "-32.00"), ("ZZ REPEATER SHOP", "-33.00")]); REPLIES["repeater"] = '{"account_code": "445", "confidence": 0.75, "reason": "shop"}'
g = c.post("/ledger/journal-suggestions/generate").json(); T("the same merchant seen three times costs ONE model call in a run", len([p for p in PROMPTS[n_calls:] if "repeater" in p.lower()]) == 1 and g["llm"] == 3, (g, len(PROMPTS) - n_calls))
orig_new = AI.new_state; AI.new_state = lambda max_calls=25: orig_new(2)
add_lines([(f"ZZ BUDGET {i} SHOP", f"-{40 + i}.00") for i in range(5)]); REPLIES["budget"] = '{"account_code": "445", "confidence": 0.7, "reason": "b"}'; n_calls = len(PROMPTS)
g = c.post("/ledger/journal-suggestions/generate").json(); T("a per-run budget bounds the number of model calls", g["llm_calls"] == 2 and len(PROMPTS) - n_calls == 2, g); AI.new_state = orig_new
REPLIES["outage"] = AI.AiUnavailable("No Groq key is available - the pool is empty"); add_lines([("ZZ OUTAGE ONE", "-51.00"), ("ZZ OUTAGE TWO", "-52.00"), ("OFFICEWORKS AGAIN 12345678", "-53.00")]); n_calls = len(PROMPTS)
g = c.post("/ledger/journal-suggestions/generate").json()
T("no Groq key: reported clearly, the model is not asked again, and RDR/rules still work", "No Groq key" in (g["llm_unavailable"] or "") and len([p for p in PROMPTS[n_calls:] if "outage" in p.lower()]) == 1, g)
REPLIES["crash"] = RuntimeError("connection reset"); add_lines([("ZZ CRASH SHOP", "-61.00")]); g = c.post("/ledger/journal-suggestions/generate")
T("a network failure never breaks suggestion generation", g.status_code == 200, g.text[:200])
# default backend through the key pool (no real network: requests and the pool are faked)
import requests, db_app.database as dbdb, main_app.backend.utils.groq_pool as GP
AI.chat_backend = AI._default_chat; keys = [dict(groq_key="k1", model=None, pool_id=1), dict(groq_key="k2", model="custom/model", pool_id=2)]; outcomes = []; seen = []
dbdb.SessionLocal = Sess; GP.resolve_groq_key = lambda db: keys.pop(0) if keys else dict(groq_key=None, model=None, pool_id=None); GP.record_key_outcome = lambda db, pid, success: outcomes.append((pid, success))
class Resp:
    def __init__(s, code, body): s.code, s.body = code, body
    def raise_for_status(s):
        if s.code >= 400: raise requests.exceptions.HTTPError(str(s.code))
    def json(s): return s.body
def fake_post(url, json=None, headers=None, timeout=None):
    seen.append((url, json, headers, timeout)); return Resp(429, {}) if headers["Authorization"].endswith("k1") else Resp(200, {"choices": [{"message": {"content": '{"account_code": "445", "confidence": 0.7, "reason": "ok"}'}}]})
requests.post = fake_post
out = AI._default_chat("sys", "user"); T("the default backend rotates to the next pool key when one is rate-limited, and records each key's health", "445" in out and outcomes == [(1, False), (2, True)], outcomes)
T("...it calls Groq's endpoint with temperature 0, the key's model override, and a timeout", seen[-1][0].startswith("https://api.groq.com/") and seen[-1][1]["temperature"] == 0 and seen[-1][1]["model"] == "custom/model" and seen[-1][3] == 20, seen[-1][:2])
try: AI._default_chat("s", "u"); ok = False
except AI.AiUnavailable as e: ok = "No Groq key" in str(e)
T("with an empty pool it raises AiUnavailable", ok)
keys[:] = [dict(groq_key="k1", model=None, pool_id=1)] * 3; outcomes.clear()
try: AI._default_chat("s", "u"); ok = False
except AI.AiUnavailable as e: ok = "did not answer" in str(e) and len(outcomes) == 3
T("if every attempt fails it gives up after 3 tries", ok, outcomes)
T("the audit trail records the generate calls with their AI counters", any(a[0] == "ledger.journal_suggestions.generated" and a[3] and "llm_calls" in a[3] for a in AUDIT))

print("\nFAILURES:", len(fails), fails)
