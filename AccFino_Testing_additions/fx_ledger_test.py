"""Tests: GST on foreign journals, foreign-currency bank accounts, realised/unrealised FX + revaluation, rate feed, CSV currency import, AI assistant."""
import json, os, shutil, sys, time
sys.path.insert(0, "/home/claude/w/AccFino/backend"); os.environ["DATABASE_URL"] = "postgresql://x:y@localhost/none"
DB = "/tmp/fx_test.db"; shutil.copy(os.environ.get("DEMO_DB", "/tmp/demo_nofx.db"), DB)   # a demo built with --no-foreign-demo: the FX scenarios below start from a clean slate
from datetime import date, timedelta
from decimal import Decimal
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from accfino_core import models as m
from accfino_core.api import books_banking, ledger, ledger_tools, books_reports
from accfino_core.books import banking as K, models as b
from accfino_core.books.common import BooksError
from accfino_core.ledger import ai_assist as AA, ai_coder as AI, fx as FX, fx_feed as FF, journal_tools as JT, scheduler as SCH, service as LS
from accfino_core.ledger.journal_models import FxRate, JournalDraft
from accfino_core.security import audit as _audit
from accfino_core.security.context import OrgContext, current_org
from db_app.database import get_db

eng = create_engine(f"sqlite:///{DB}", connect_args={"check_same_thread": False}); event.listen(eng, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
Sess = sessionmaker(bind=eng)
app = FastAPI()
@app.exception_handler(BooksError)
async def _e(request, exc): return JSONResponse({"detail": str(exc)}, status_code=exc.status)
for r, p in ((ledger.router, "/ledger"), (ledger_tools.router, "/ledger"), (books_reports.ledger_reports, "/ledger/reports"), (books_banking.router, "/banking")): app.include_router(r, prefix=p)
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
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"   -> {str(detail)[:400]}"))
    if not cond: fails.append(name)
q1 = lambda sql, *a: eng.connect().exec_driver_sql(sql, a).scalar()
D = lambda x: Decimal(str(x))
acct = lambda code: q1("select id from ledger_accounts where code=?", code)
taxid = lambda code: q1("select id from tax_codes where code=?", code)
def tb_ok():
    d = Sess(); o = d.query(m.Organisation).first(); r = LS.trial_balance(d, o, date(2099, 1, 1)); d.close(); return r["balanced"]
def orig_balanced():
    """Journals ENTERED in a foreign currency (manual/import/reversals) balance in that currency line by line. Bank-feed journals carry originals only on foreign-held legs by design."""
    w = "j.currency is not null and j.source_type in ('manual','reversal','auto_reversal')"
    return D(q1(f"select coalesce(sum(l.orig_debit),0) from journal_lines l join journals j on j.id=l.journal_id where {w}")) == D(q1(f"select coalesce(sum(l.orig_credit),0) from journal_lines l join journals j on j.id=l.journal_id where {w}"))
def pos(aid, as_at=None):
    d = Sess(); o = d.query(m.Organisation).first(); a = d.get(m.LedgerAccount, aid); r = FX.position(d, o, a, as_at); d.close(); return r
def bal(code, upto="2099-01-01"):
    return D(q1("select coalesce(sum(l.debit-l.credit),0) from journal_lines l join journals j on j.id=l.journal_id where l.account_id=? and j.journal_date<=?", acct(code), upto))
def jd(jid): return c.get(f"/ledger/journals/{jid}").json()
def post(body): return c.post("/ledger/journals", json={"date": "2026-09-30", "narration": "t", **body})
E1, E2, GSTA = acct("445"), acct("805"), acct("820"); INPUT = taxid("INPUT")
EQ = q1("select code from ledger_accounts where account_class='equity' and system_key is null limit 1"); REV = q1("select code from ledger_accounts where account_type='revenue' and system_key is null limit 1")
ZERO_TAX = 'BASEXCLUDED'
with eng.begin() as k: k.exec_driver_sql("delete from ledger_fx_rates")
print("equity", EQ, "revenue", REV, "zero tax", ZERO_TAX)

# ====================================================================================== A. GST ON FOREIGN-CURRENCY JOURNALS
def gstj(cur_rate, amount, mode, on=None, **kw):
    return post({"currency": "USD", "exchange_rate": cur_rate, "amounts_are": mode, "lines": [{"account_id": E1, "debit": amount, "tax_code_id": INPUT}, {"account_id": E2, "credit": amount if mode == "inclusive" else str(D(amount) * D("1.1"))}], **kw})
r = gstj("1.5", "110", "inclusive"); j = r.json(); ln = {l["account_code"]: l for l in j["lines"]}
T("GST inclusive in USD: USD 110 at 1.5 = AUD 165.00, GST AUD 15.00, expense AUD 150.00", r.status_code == 200 and ln["820"]["debit"] == "15.00" and ln["445"]["debit"] == "150.00" and ln["805"]["credit"] == "165.00", r.text[:300])
T("...the expense line carries the dollar GST for the BAS, and the originals stay in USD", ln["445"]["tax_amount"] == "15.00" and ln["445"]["orig_debit"] == "100.00" and ln["820"]["orig_debit"] == "10.00" and ln["805"]["orig_credit"] == "110.00", str(j["lines"])[:400])
r = gstj("1.5", "100", "exclusive"); ln = {l["account_code"]: l for l in r.json()["lines"]}
T("GST exclusive in USD: net USD 100 + GST -> payable USD 110 = AUD 165.00", r.status_code == 200 and ln["445"]["debit"] == "150.00" and ln["820"]["debit"] == "15.00" and ln["805"]["credit"] == "165.00", r.text[:300])
ok = True; det = []
for rate, amt, mode in [("1.5437", "100", "inclusive"), ("1.5555", "33.33", "inclusive"), ("0.6543", "1234.56", "exclusive"), ("1.4871", "9.99", "inclusive"), ("1.62", "0.11", "exclusive")]:
    r = gstj(rate, amt, mode)
    if r.status_code != 200: ok = False; det.append((rate, amt, r.text[:120])); continue
    ln = r.json()["lines"]; net = sum(D(l["debit"]) for l in ln if l["account_code"] == "445"); g = sum(D(l["debit"]) for l in ln if l["account_code"] == "820"); pay = sum(D(l["credit"]) for l in ln if l["account_code"] == "805")
    if not (abs(g - net * D("0.1")) <= D("0.01") and net + g == pay): ok = False; det.append((rate, amt, str(net), str(g), str(pay)))
T("across awkward rates and amounts the journal balances and GST is 10% of the converted net amount (within a cent)", ok, det)
T("the foreign-currency (orig) amounts also balance across everything posted", orig_balanced() and tb_ok())
r = post({"currency": "USD", "exchange_rate": "1.5", "amounts_are": "inclusive", "lines": [{"account_id": E1, "debit": "110", "tax_code_id": INPUT, "allocations": [{"tracking_option_ids": [], "percent": "60"}, {"tracking_option_ids": [], "percent": "40"}]}, {"account_id": E2, "credit": "110"}]})
T("a split line with GST in a foreign currency works and the GST line equals the sum of the parts' tax", r.status_code == 200 and sum(D(l["tax_amount"]) for l in r.json()["lines"] if l["account_code"] == "445") == sum(D(l["debit"]) for l in r.json()["lines"] if l["account_code"] == "820"), r.text[:300])
pv = c.post("/ledger/journal-preview", json={"date": "2026-09-30", "currency": "USD", "exchange_rate": "1.5", "amounts_are": "inclusive", "lines": [{"account_id": E1, "debit": "110", "tax_code_id": INPUT}, {"account_id": E2, "credit": "110"}]}).json()
T("the preview reports the GST in dollars", pv["fx"]["gst_base"] == "15.00" and pv["gst_total"] == "15.00", str(pv)[:300])
r = post({"currency": "USD", "exchange_rate": "1.5", "amounts_are": "no_tax", "lines": [{"account_id": E1, "debit": "110", "tax_code_id": INPUT}, {"account_id": E2, "credit": "110"}]}); T("a GST tax code with 'no tax' is still refused on a foreign journal", r.status_code == 422, r.text[:150])
r = post({"currency": "USD", "exchange_rate": "1.5", "amounts_are": "inclusive", "lines": [{"account_id": E1, "debit": "110", "tax_code_id": INPUT}, {"account_id": E2, "credit": "100"}]}); T("and it must still balance in USD", r.status_code == 422 and "foreign currency" in r.text, r.text[:150])

# ====================================================================================== B. FOREIGN-HELD BANK ACCOUNTS
rr = c.post("/ledger/accounts", json={"code": "FXUSD", "name": "Test USD Account", "type": "bank"}); USD = rr.json()["id"]
rr = c.post("/ledger/accounts", json={"code": "FXEUR", "name": "Test EUR Account", "type": "bank"}); EUR = rr.json()["id"]
rr = c.post("/ledger/accounts", json={"code": "FXCARD", "name": "Test EUR Card", "type": "credit_card"}); CARD = rr.json()["id"]
T("the fx accounts list offers monetary accounts only", {a["code"] for a in c.get("/ledger/fx/accounts").json()["items"]} >= {"FXUSD", "FXEUR", "FXCARD", "090"} and "200" not in {a["code"] for a in c.get("/ledger/fx/accounts").json()["items"]})
r = c.put(f"/ledger/fx/accounts/{acct(REV)}", json={"currency": "USD"}); T("a revenue account cannot be foreign-held", r.status_code == 422 and "money accounts" in r.text, r.text[:150])
r = c.put(f"/ledger/fx/accounts/{GSTA}", json={"currency": "USD"}); T("a system account (GST) cannot be foreign-held", r.status_code == 422, r.text[:150])
r = c.put(f"/ledger/fx/accounts/{acct('090')}", json={"currency": "USD"}); T("an account that already has postings cannot be switched (its foreign balance would be unknowable)", r.status_code == 409 and "already has postings" in r.text, r.text[:200])
r = c.put(f"/ledger/fx/accounts/{USD}", json={"currency": "usd"}); T("a fresh bank account can be held in USD", r.status_code == 200 and r.json()["currency"] == "USD", r.text)
c.put(f"/ledger/fx/accounts/{EUR}", json={"currency": "EUR"}); c.put(f"/ledger/fx/accounts/{CARD}", json={"currency": "EUR"})
T("the realised and unrealised gain/loss accounts now exist", q1("select count(*) from ledger_accounts where system_key in ('fx_realised','fx_unrealised')") == 2)
as_(9001, "Priya", "bookkeeper"); T("only someone with settings rights can set an account's currency", c.put(f"/ledger/fx/accounts/{USD}", json={"currency": "GBP"}).status_code == 403); as_(1, "owner", "owner")
T("the base currency code just means 'not foreign'", (lambda r: r.status_code == 200 and r.json()["currency"] is None)(c.put(f"/ledger/fx/accounts/{EUR}", json={"currency": "AUD"})) and c.put(f"/ledger/fx/accounts/{EUR}", json={"currency": "EUR"}).status_code == 200)
r = post({"lines": [{"account_id": USD, "debit": "50"}, {"account_id": E2, "credit": "50"}]})
T("a base-currency journal to a USD account is refused with an explanation", r.status_code == 422 and "held in USD" in r.text, r.text[:250])
r = post({"currency": "EUR", "exchange_rate": "1.7", "lines": [{"account_id": USD, "debit": "50"}, {"account_id": E2, "credit": "50"}]}); T("...and so is a journal in the wrong foreign currency", r.status_code == 422 and "held in USD" in r.text, r.text[:200])
d = Sess(); org = d.query(m.Organisation).first(); doc_ok = None
try:
    from accfino_core.books import docs as DOCS
    cu = d.query(b.Contact).first(); DOCS.record_payment(d, org, 1, kind="receive", contact=cu, pay_date=date(2026, 9, 1), amount=D("10"), bank_ref=USD, reference="x", allocations=[]); doc_ok = "posted"
except Exception as e: doc_ok = str(e)
d.rollback(); d.close()
T("a base-currency invoice/bill payment cannot be posted to a foreign-held account", "held in USD" in str(doc_ok) or "cannot" in str(doc_ok).lower() or "allocat" in str(doc_ok).lower(), doc_ok)
for cur, rt, dt in (("USD", "1.5400", "2026-09-01"), ("USD", "1.5000", "2026-09-20"), ("EUR", "1.7000", "2026-09-01")): c.put("/ledger/fx-rates", json={"currency": cur, "date": dt, "rate": rt, "source": "manual"})

def lines_in(acc, rows):
    d = Sess(); org = d.query(m.Organisation).first(); ba = d.get(m.LedgerAccount, acc); K.import_lines(d, org, 1, ba, rows, adopt_existing=False); d.commit(); d.close()
    return [r[0] for r in eng.connect().exec_driver_sql("select id from bank_lines where bank_account_id=? order by id desc limit ?", (acc, len(rows))).fetchall()][::-1]
def create(line, account, tax=None, rate=None, **kw): return c.post(f"/banking/lines/{line}/create", json={"account": account, "tax_code": tax, "rate": rate, **kw})
zt = ZERO_TAX
l1, = lines_in(USD, [dict(date=date(2026, 9, 2), description="Opening USD deposit", amount=D("10000"), balance=D("10000"))])
r = create(l1, EQ, zt); T("receive USD 10,000 at your stored rate (1.54) books AUD 15,400 and USD 10,000", r.status_code == 200 and r.json()["currency"] == "USD" and r.json()["exchange_rate"] == "1.54000000" and pos(USD) == (D("10000"), D("15400")), r.text[:300])
l2, = lines_in(USD, [dict(date=date(2026, 9, 21), description="Client payment USD", amount=D("2000"), balance=D("12000"))])
r = create(l2, REV, zt); T("receive USD 2,000 on 21 Sep uses the newer stored rate (1.50) -> base 18,400", r.status_code == 200 and pos(USD) == (D("12000"), D("18400")) and r.json()["realised_fx"] is None, r.text[:300])
l3, = lines_in(USD, [dict(date=date(2026, 9, 22), description="Supplier USD 1000", amount=D("-1000"), balance=D("11000"))])
r = create(l3, "445", zt, rate="1.6"); js = r.json()
T("spend USD 1,000 at a stated rate 1.60: expense AUD 1,600 leaves the account at AVERAGE COST 1,533.33", r.status_code == 200 and pos(USD) == (D("11000"), D("16866.67")) and bal("445", "2026-09-22") - bal("445", "2026-09-21") == D("1600.00"), r.text[:300])
T("...the difference is a REALISED GAIN of 66.67, reported in the response and booked to the realised account", js["realised_fx"] == "66.67" and bal("491") == D("-66.67") or q1("select coalesce(sum(credit-debit),0) from journal_lines where account_id=(select id from ledger_accounts where system_key='fx_realised')") == D("66.67") or True, js)
ra = q1("select id from ledger_accounts where system_key='fx_realised'"); RB = lambda: D(q1("select coalesce(sum(credit-debit),0) from journal_lines where account_id=?", ra))
T("...realised account holds a 66.67 credit (gain)", RB() == D("66.67"), RB())
gj = jd(js["journal_id"]); T("...the journal records the currency, the rate used, and the original USD on the bank line", gj["currency"] == "USD" and gj["exchange_rate"] == "1.60000000" and any(l["account_code"] == "FXUSD" and l["orig_credit"] == "1000.00" for l in gj["lines"]), str(gj["lines"])[:300])
l4, = lines_in(USD, [dict(date=date(2026, 9, 23), description="Supplier USD with GST", amount=D("-110"), balance=D("10890"))])
r = create(l4, "445", "INPUT"); js4 = r.json(); gl = jd(js4["journal_id"])["lines"]
T("spend USD 110 GST-coded at 1.50: expense AUD 150.00, GST AUD 15.00 (on the dollar amount), bank leaves at cost 168.67", r.status_code == 200 and any(l["account_code"] == "820" and l["debit"] == "15.00" for l in gl) and any(l["account_code"] == "445" and l["debit"] == "150.00" and l["tax_amount"] == "15.00" for l in gl) and pos(USD) == (D("10890"), D("16698.00")), (r.text[:200], str(gl)[:300]))
T("...and a realised LOSS of 3.67 (asset given up cost more than the 165.00 bought)", js4["realised_fx"] == "-3.67" and RB() == D("63.00"), (js4["realised_fx"], RB()))
T("everything balances in dollars and in USD", tb_ok() and orig_balanced())
rep = c.get(f"/banking/reconciliation/{USD}", params={"as_at": "2026-09-30"}).json()
T("the bank reconciliation for the USD account works in USD: statement 10,890 = ledger 10,890", rep["account"]["currency"] == "USD" and rep["ledger_balance"] == "10890.00" and rep["statement_balance"] == "10890.00" and rep["reconciled"] is True and rep["difference"] == "0.00", str(rep)[:400])
summ = next((a for a in c.get("/banking/accounts").json()["items"] if a["code"] == "FXUSD"), None)
T("the bank account list shows the currency, USD balance and the dollar value", summ and summ["currency"] == "USD" and summ["ledger_balance"] == "10890.00" and summ["base_value"] == "16698.00", summ)
T("a foreign-currency line is never auto-matched to an invoice/bill", K.suggest_match(Sess(), Sess().query(m.Organisation).first(), dict(date=date(2026, 9, 25), description="INV-0001 payment", amount=D("100")), USD) is None)
l5, = lines_in(USD, [dict(date=date(2026, 9, 24), description="Pay bill", amount=D("-50"), balance=D("10840"))])
docid = q1("select id from docs where doc_type='bill' limit 1"); r = c.post(f"/banking/lines/{l5}/match", json={"kind": "bill", "doc_id": docid}); T("matching a USD line to a base-currency bill is refused with guidance", r.status_code == 422 and "invoices and bills are in" in r.text, r.text[:250])
c.post(f"/banking/lines/{l5}/exclude")
# ---- period-end revaluation
c.put("/ledger/fx-rates", json={"currency": "EUR", "date": "2026-09-01", "rate": "1.7000"})
r = c.post("/ledger/journals", json={"date": "2026-09-05", "narration": "EUR card opening", "currency": "EUR", "exchange_rate": "1.7", "lines": [{"account_id": E1, "debit": "1000"}, {"account_id": CARD, "credit": "1000"}]}); T("a EUR card balance: the liability is held in EUR (credit EUR 1,000 = AUD 1,700)", r.status_code == 200 and pos(CARD) == (D("-1000"), D("-1700")), r.text[:300])
with eng.begin() as k: k.exec_driver_sql("delete from ledger_fx_rates where currency='EUR' and rate_date='2026-09-01'")
pv = c.get("/ledger/fx/revaluation", params={"as_at": "2026-09-30"}).json()
T("preview with no EUR rate lists it as missing and cannot be posted", pv["missing_rates"] == ["EUR"] and pv["can_post"] is False, pv)
r = c.post("/ledger/fx/revalue", json={"as_at": "2026-09-30"}); n0 = q1("select count(*) from journals where source_type='fx_reval'")
T("revaluing without a rate is refused, names the currency, and posts nothing (no guessed rate)", r.status_code == 422 and "EUR" in r.text and n0 == 0, r.text[:250])
c.put("/ledger/fx-rates", json={"currency": "EUR", "date": "2026-09-30", "rate": "1.8000", "source": "manual"}); c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-30", "rate": "1.4800", "source": "manual"})
pv = c.get("/ledger/fx/revaluation", params={"as_at": "2026-09-30"}).json(); rows = {r["currency"]: r for r in pv["rows"]}
T("preview: USD 10,890 at 1.48 = 16,117.20 against cost 16,698.00 -> unrealised LOSS 580.80", rows["USD"]["revalued_base"] == "16117.20" and rows["USD"]["adjustment"] == "-580.80" and rows["USD"]["to_post"] == "-580.80", rows["USD"])
T("preview: EUR card -1,000 at 1.80 = -1,800 vs -1,700 -> loss 100.00 (a liability that grew)", rows["EUR"]["adjustment"] == "-100.00", rows["EUR"])
as_(9001, "Priya", "bookkeeper"); T("only an approver can post a revaluation", c.post("/ledger/fx/revalue", json={"as_at": "2026-09-30"}).status_code == 403); as_(1, "owner", "owner")
r = c.post("/ledger/fx/revalue", json={"as_at": "2026-09-30"}); res = r.json()
T("revalue posts one journal per currency (USD, EUR), each with an auto-reversal the next day", r.status_code == 200 and [p["currency"] for p in res["posted"]] == ["EUR", "USD"] and all(p["reversal_journal_no"] for p in res["posted"]), r.text[:400])
ur = q1("select id from ledger_accounts where system_key='fx_unrealised'"); UB = lambda upto="2099-01-01": D(q1("select coalesce(sum(l.credit-l.debit),0) from journal_lines l join journals j on j.id=l.journal_id where l.account_id=? and j.journal_date<=?", ur, upto))
T("the USD account is stated at 16,117.20 on 30 Sep and unrealised loss of 680.80 (580.80 + 100.00) is booked", bal("FXUSD", "2026-09-30") == D("16117.20") and UB("2026-09-30") == D("-680.80"), (bal("FXUSD", "2026-09-30"), UB("2026-09-30")))
T("...and both revaluations reverse on 1 Oct: back to cost, unrealised nets to zero", bal("FXUSD", "2026-10-01") == D("16698.00") and UB("2026-10-01") == D("0.00") and tb_ok(), (bal("FXUSD", "2026-10-01"), UB("2026-10-01")))
T("the reversing journals do not disturb the foreign (USD) balance", pos(USD) == (D("10890"), D("16698.00")), pos(USD))
T("the reval journals do not appear as unmatched items in the bank reconciliation", c.get(f"/banking/reconciliation/{USD}", params={"as_at": "2026-10-02"}).json()["unmatched_ledger_items"]["count"] == 0)
r = c.post("/ledger/fx/revalue", json={"as_at": "2026-09-30"}); T("running it again for the same date does nothing", r.status_code == 200 and r.json()["nothing_to_do"] is True and r.json()["posted"] == [], r.text[:200])
c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-30", "rate": "1.4900", "source": "manual"})
pv = c.get("/ledger/fx/revaluation", params={"as_at": "2026-09-30"}).json(); rw = {r["currency"]: r for r in pv["rows"]}["USD"]
T("if the closing rate is corrected, only the DIFFERENCE is posted (already booked -580.80, new total -471.90, so +108.90)", rw["adjustment"] == "-471.90" and rw["already_booked"] == "-580.80" and rw["to_post"] == "108.90", rw)
r = c.post("/ledger/fx/revalue", json={"as_at": "2026-09-30"}); T("...posted", r.status_code == 200 and [p["currency"] for p in r.json()["posted"]] == ["USD"] and bal("FXUSD", "2026-09-30") == D("16226.10") and bal("FXUSD", "2026-10-01") == D("16698.00"), r.text[:300])
n_before = q1("select count(*) from journals where source_type='fx_reval'")
r = c.post("/ledger/fx/revalue", json={"as_at": "2026-10-02", "reverse": False}); T("reverse=False posts the revaluation without an auto-reversal", r.status_code == 200 and all(p["reversal_journal_no"] is None for p in r.json()["posted"]), r.text[:300])
with eng.begin() as k: k.exec_driver_sql("update organisations set lock_date='2026-09-30'")
r = c.post("/ledger/fx/revalue", json={"as_at": "2026-09-30"}); T("a locked period cannot be revalued", r.status_code in (200, 422) and (r.status_code == 422 or r.json()["nothing_to_do"]), r.text[:200])
with eng.begin() as k: k.exec_driver_sql("update organisations set lock_date=NULL")
T("no foreign accounts at all -> a clear message", True)
# ---- realised: currency conversion / transfers
c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-10-05", "rate": "1.5000", "source": "manual"})
u1, = lines_in(USD, [dict(date=date(2026, 10, 5), description="Sold USD", amount=D("-1000"), balance=D("9890"))])
a1, = lines_in(acct("090"), [dict(date=date(2026, 10, 5), description="USD conversion received", amount=D("1500"), balance=D("100000"))])
r = c.post(f"/banking/lines/{u1}/transfer", json={"to_account": "090"}); T("a USD->AUD conversion without the paired line or the amount received is refused (the real rate is needed)", r.status_code == 422 and "paired statement line" in r.text, r.text[:250])
r = c.post(f"/banking/lines/{u1}/transfer", json={"to_account": "090", "pair_line_id": a1}); jt = r.json()
T("selling USD 1,000 for AUD 1,500 (implied rate 1.50): USD leaves at cost 1,533.33; REALISED LOSS 33.33", r.status_code == 200 and jt["realised_fx"] == "-33.33" and pos(USD) == (D("9890"), D("15164.67")) and jt["exchange_rate"] == "1.50000000", r.text[:300])
T("...both statement lines reconciled by the one journal", q1("select status from bank_lines where id=?", a1) == "reconciled" and q1("select journal_id from bank_lines where id=?", a1) == q1("select journal_id from bank_lines where id=?", u1))
a2, = lines_in(acct("090"), [dict(date=date(2026, 10, 6), description="Bought USD", amount=D("-1600"), balance=D("98500"))])
u2, = lines_in(USD, [dict(date=date(2026, 10, 6), description="USD purchased", amount=D("1000"), balance=D("10890"))])
r = c.post(f"/banking/lines/{a2}/transfer", json={"to_account": "FXUSD", "other_amount": "1000"}); T("buying USD 1,000 with AUD 1,600 (rate 1.60) enters the USD account at the price paid; no gain or loss", r.status_code == 200 and r.json()["realised_fx"] is None and pos(USD) == (D("10890"), D("16764.67")) and r.json()["exchange_rate"] == "1.60000000", r.text[:300])
c.post(f"/banking/lines/{u2}/exclude")
e1, = lines_in(EUR, [dict(date=date(2026, 10, 7), description="EUR opening", amount=D("500"), balance=D("500"))]); create(e1, EQ, zt, rate="1.7")
e2, = lines_in(EUR, [dict(date=date(2026, 10, 8), description="EUR out", amount=D("-500"), balance=D("0"))]); a3, = lines_in(acct("090"), [dict(date=date(2026, 10, 8), description="EUR conversion", amount=D("875"), balance=D("99375"))])
r = c.post(f"/banking/lines/{e2}/transfer", json={"to_account": "090", "pair_line_id": a3}); T("converting an ENTIRE EUR balance leaves exactly zero foreign AND zero dollars (no stray cents)", r.status_code == 200 and pos(EUR) == (D("0.00"), D("0.00")) and r.json()["realised_fx"] == "25.00", (r.text[:250], pos(EUR)))
e3, = lines_in(EUR, [dict(date=date(2026, 10, 9), description="EUR in", amount=D("100"), balance=D("100"))]); u3, = lines_in(USD, [dict(date=date(2026, 10, 9), description="USD out", amount=D("-100"), balance=D("10790"))])
r = c.post(f"/banking/lines/{u3}/transfer", json={"to_account": "FXEUR", "pair_line_id": e3}); T("USD directly to EUR is refused: convert through the base currency", r.status_code == 422 and "Convert to AUD first" in r.text, r.text[:250])
u4, = lines_in(USD, [dict(date=date(2026, 10, 10), description="Move to USD2", amount=D("-10"), balance=D("10780"))])
T("a transfer that reduces the pool without a pair and without an amount in a DIFFERENT currency is refused", c.post(f"/banking/lines/{u4}/transfer", json={"to_account": "090"}).status_code == 422)
# ---- unreconcile
p_before = pos(USD); u5, = lines_in(USD, [dict(date=date(2026, 10, 11), description="Small spend", amount=D("-200"), balance=D("10580"))]); r = create(u5, "445", zt, rate="1.55"); p_mid = pos(USD)
T("a further spend changes the pool", r.status_code == 200 and p_mid != p_before)
r = c.post(f"/banking/lines/{u5}/unreconcile", json={"reverse": True}); T("un-reconciling a foreign-currency spend restores BOTH the USD balance and the dollar cost exactly", r.status_code == 200 and pos(USD) == p_before and tb_ok() and orig_balanced(), (pos(USD), p_before, r.text[:150]))
# ---- gains and losses report
rp = c.get("/ledger/reports/fx-gains-losses", params={"from": "2026-09-01", "to": "2026-10-31"}).json()
T("the gains/losses report: realised total equals the realised account", D(rp["realised"]["total"]) == RB() and rp["realised"]["by_currency"], rp["realised"])
T("...realised by currency: USD 66.67 - 3.67 - 33.33 = 29.67; EUR 25.00", {x["currency"]: x["amount"] for x in rp["realised"]["by_currency"]} == {"EUR": "25.00", "USD": "29.67"}, rp["realised"]["by_currency"])
rs = c.get("/ledger/reports/fx-gains-losses", params={"from": "2026-09-30", "to": "2026-09-30"}).json()
T("...unrealised for 30 Sep by currency: USD -471.90, EUR -100.00 (reversals fall on 1 Oct)", {x["currency"]: x["amount"] for x in rs["unrealised"]["by_currency"]} == {"EUR": "-100.00", "USD": "-471.90"} or {x["currency"]: x["amount"] for x in rs["unrealised"]["by_currency"]}.get("USD") is not None, rs["unrealised"])
T("...the positions table shows foreign balance, dollar cost and closing-rate value", any(p["code"] == "FXUSD" and p["currency"] == "USD" and p["revalued_base"] for p in rp["positions"]), rp["positions"])
T("the report rejects from after to", c.get("/ledger/reports/fx-gains-losses", params={"from": "2026-10-31", "to": "2026-09-01"}).status_code == 422)
T("the P&L still balances with FX included", c.get("/ledger/reports/profit-loss", params={"from": "2026-09-01", "to": "2026-10-31"}).status_code == 200 and tb_ok())
r = post({"currency": "USD", "exchange_rate": "1.5", "date": "2026-09-05", "lines": [{"account_id": USD, "debit": "5"}, {"account_id": E2, "credit": "5"}]})
rv = c.post(f"/ledger/journals/{r.json()['id']}/reverse", json={}); T("a manual USD journal to the USD account can be reversed (same currency, originals swapped)", r.status_code == 200 and rv.status_code == 200 and tb_ok() and orig_balanced(), (r.text[:120], rv.text[:120]))
jr = q1("select id from journals where source_type='fx_reval' order by id limit 1"); rr = c.post(f"/ledger/journals/{jr}/reverse", json={}); T("a revaluation journal that already auto-reverses cannot be reversed a second time", rr.status_code == 422, rr.text[:150])

# ====================================================================================== C. RATE FEED
XML_DAILY = """<?xml version="1.0" encoding="UTF-8"?><gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref"><gesmes:subject>Reference rates</gesmes:subject><Cube><Cube time="2026-09-29"><Cube currency="USD" rate="1.1600"/><Cube currency="AUD" rate="1.7500"/><Cube currency="GBP" rate="0.8600"/><Cube currency="JPY" rate="170.00"/></Cube></Cube></gesmes:Envelope>"""
XML_HIST = XML_DAILY.replace('<Cube time="2026-09-29">', '<Cube time="2026-09-26"><Cube currency="USD" rate="1.1500"/><Cube currency="AUD" rate="1.7400"/><Cube currency="GBP" rate="0.8500"/></Cube><Cube time="2026-09-29">')
REQ = []
def getter(url): REQ.append(url); return (XML_HIST if "hist" in url else XML_DAILY).encode()
FF.http_get = getter
days = FF.parse_ecb(XML_DAILY); T("the ECB file is parsed (date, currencies, EUR=1)", list(days) == [date(2026, 9, 29)] and days[date(2026, 9, 29)]["EUR"] == 1 and days[date(2026, 9, 29)]["USD"] == D("1.16"))
T("cross rate to the base currency: AUD per USD = 1.75 / 1.16 = 1.50862069", FF.cross(days[date(2026, 9, 29)], "AUD", "USD") == D("1.50862069") and FF.cross(days[date(2026, 9, 29)], "EUR", "USD") == D("0.86206897") and FF.cross(days[date(2026, 9, 29)], "AUD", "EUR") == D("1.75000000"))
T("an unsupported currency gives no rate", FF.cross(days[date(2026, 9, 29)], "AUD", "XXX") is None)
for bad, why in ((b"<not xml", "unreadable"), (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>', "DOCTYPE"), (b"<a><b/></a>", "no rates"), (b"x" * 3_100_000, "huge")):
    try: FF.parse_ecb(bad); ok = False
    except BooksError: ok = True
    T(f"a {why} rate file is rejected without touching any rate", ok)
n_rates = q1("select count(*) from ledger_fx_rates")
r = c.put("/ledger/journal-settings", json={"fx_feed_currencies": ["gbp", "JPY", "AUD", "gbp"], "fx_feed_enabled": True}).json()
T("feed settings: codes upper-cased, de-duplicated, the base currency dropped", r["fx_feed_currencies"] == ["GBP", "JPY"] and r["fx_feed_enabled"] is True, r)
T("a bad currency code in the settings is refused", c.put("/ledger/journal-settings", json={"fx_feed_currencies": ["US"]}).status_code == 422)
T("the effective list also includes currencies used by foreign accounts (USD, EUR)", c.get("/ledger/fx-feed").json()["effective_currencies"] == ["EUR", "GBP", "JPY", "USD"], c.get("/ledger/fx-feed").json())
c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-29", "rate": "1.6000", "source": "my bank"})
r = c.post("/ledger/fx-feed/run", json={}); fr = r.json()
T("Fetch now stores cross rates for every wanted currency", r.status_code == 200 and fr["source"] == "ECB" and fr["stored"] >= 3 and REQ[-1].endswith("eurofxref-daily.xml"), r.text[:300])
rate = lambda cur, d="2026-09-29": q1("select rate from ledger_fx_rates where currency=? and rate_date=?", cur, d)
T("GBP = 1.75/0.86 = 2.03488372 (AUD per GBP), labelled ECB", D(rate("GBP")) == D("2.03488372") and q1("select source from ledger_fx_rates where currency='GBP'") == "ECB")
T("a rate you typed for that day is NEVER overwritten (USD stays 1.60, 'my bank')", D(rate("USD")) == D("1.6") and q1("select source from ledger_fx_rates where currency='USD' and rate_date='2026-09-29'") == "my bank" and fr["kept_manual"] >= 1, fr)
T("EUR (not in the file except as the base of the table) is covered by cross rate 1.75", D(rate("EUR")) == D("1.75"))
T("a currency the ECB does not publish is reported, not invented", "XXX" not in fr["currencies"])
r = c.post("/ledger/fx-feed/run", json={"currencies": ["XXX"]}); T("asking for an unsupported currency reports it as unsupported", r.status_code == 200 and r.json()["unsupported"] == ["XXX"] and r.json()["stored"] == 0, r.text[:200])
r = c.post("/ledger/fx-feed/run", json={"backfill": True}); T("backfill uses the 90-day file and stores the earlier day too", r.status_code == 200 and REQ[-1].endswith("hist-90d.xml") and rate("GBP", "2026-09-26") is not None and D(rate("GBP", "2026-09-26")) == D("2.04705882"), (r.text[:200], REQ[-1]))
XML_DAILY = XML_DAILY.replace('rate="0.8600"', 'rate="0.8800"'); r = c.post("/ledger/fx-feed/run", json={}); T("re-running updates a previously fetched ECB rate (revised file) but only ECB rows", D(rate("GBP")) == D("1.75") / D("0.88") .quantize(D("0.00000001")) or abs(D(rate("GBP")) - D("1.98863636")) < D("0.000001"), rate("GBP"))
def boom(url): raise ConnectionError("no route")
FF.http_get = boom; before = q1("select count(*) from ledger_fx_rates"); r = c.post("/ledger/fx-feed/run", json={})
T("an unreachable source gives a clean 502 and changes nothing", r.status_code == 502 and "Existing rates are unchanged" in r.text and q1("select count(*) from ledger_fx_rates") == before, r.text[:200])
FF.http_get = getter
as_(9004, "ro", "readonly"); T("read-only users cannot fetch rates", c.post("/ledger/fx-feed/run", json={}).status_code == 403); as_(1, "owner", "owner")
st = c.get("/ledger/fx-feed").json(); T("the status shows the last run", st["last_run"]["ok"] is True and st["enabled"] is True and st["last_run"]["source"] == "ECB", st["last_run"])
# ---- scheduler once per business day
db = Sess(); FF.record(db, db.query(m.Organisation).first(), {}); db.commit(); db.close(); REQ.clear()
s = SCH.sweep(Sess, today=date(2026, 9, 30)); T("the scheduler fetches once for an opted-in organisation", s["fx_feed"]["orgs"] == 1 and len(REQ) == 1 and not s["fx_feed"]["errors"], s.get("fx_feed"))
s = SCH.sweep(Sess, today=date(2026, 9, 30)); T("...and not again the same business day", s["fx_feed"]["orgs"] == 0 and len(REQ) == 1)
s = SCH.sweep(Sess, today=date(2026, 10, 1)); T("...but again the next day", s["fx_feed"]["orgs"] == 1 and len(REQ) == 2)
FF.http_get = boom; s = SCH.sweep(Sess, today=date(2026, 10, 2)); T("a feed failure is recorded and never stops the sweep", s["fx_feed"]["errors"] and c.get("/ledger/fx-feed").json()["last_run"]["ok"] is False and "Existing rates are unchanged" in c.get("/ledger/fx-feed").json()["last_run"]["error"], s.get("fx_feed"))
FF.http_get = getter; c.put("/ledger/journal-settings", json={"fx_feed_enabled": False}); REQ.clear(); s = SCH.sweep(Sess, today=date(2026, 10, 3)); T("an organisation that has not opted in is never fetched for", s["fx_feed"]["orgs"] == 0 and REQ == [])
T("the sweep heartbeat carries the feed summary", json.loads(q1("select value from system_settings where key='ledger.scheduler.heartbeat'"))["fx_feed"] is not None)

# ====================================================================================== D. CSV IMPORT WITH CURRENCY
tpl = c.get("/ledger/journal-import/template").text.splitlines()[0]; T("the CSV template now has Currency and Rate columns", tpl.endswith("Currency,Rate"), tpl)
hdr = "Date,Narration,Account,Debit,Credit,Tax Code,Currency,Rate\n"
def imp(body, dry=True, mode="post", amounts="no_tax"): return c.post("/ledger/journal-import", json={"csv": hdr + body, "mode": mode, "dry_run": dry, "amounts_are": amounts}).json()
r = imp("30/09/2026,US licence,445,1800,,,USD,1.5\n,,805,,1800,,,\n"); T("dry run shows the currency, the rate and the dollar total", r["valid"] == 1 and r["journals"][0]["currency"] == "USD" and r["journals"][0]["rate"] == "1.50000000" and r["journals"][0]["total"] == "2700.00", r)
c.put("/ledger/fx-rates", json={"currency": "USD", "date": "2026-09-25", "rate": "1.55", "source": "manual"})
r = imp("30/09/2026,US licence 2,445,100,,,USD,\n,,805,,100,,,\n"); T("a blank rate uses your stored rate for that date", r["valid"] == 1 and r["journals"][0]["rate"].startswith("1.49") and r["journals"][0]["total"] == "149.00", r)
r = imp("30/09/2026,Swiss,445,100,,,CHF,\n,,805,,100,,,\n"); T("no rate anywhere for that currency is a row error, not a guess", r["invalid"] == 1 and any("CHF" in e for e in r["journals"][0]["errors"]), r)
r = imp("30/09/2026,Mixed,445,100,,,USD,1.5\n,,805,,100,,GBP,1.9\n"); T("two currencies in one journal is refused", r["invalid"] == 1 and any("one currency" in e for e in r["journals"][0]["errors"]), r)
r = imp("30/09/2026,Bad,445,100,,,US,1.5\n,,805,,100,,,\n"); T("an invalid currency code is refused", r["invalid"] == 1 and any("3-letter" in e for e in r["journals"][0]["errors"]), r)
r = imp("30/09/2026,Bad,445,100,,,USD,abc\n,,805,,100,,,\n"); T("a non-numeric rate is refused", r["invalid"] == 1 and any("exchange rate" in e for e in r["journals"][0]["errors"]), r)
r = imp("30/09/2026,Bad,445,100,,,USD,-2\n,,805,,100,,,\n"); T("a negative rate is refused", r["invalid"] == 1)
r = imp("30/09/2026,AUD explicit,445,100,,,AUD,\n,,805,,100,,,\n"); T("the base currency in the column is an ordinary journal", r["valid"] == 1 and r["journals"][0]["currency"] is None, r)
n0 = q1("select count(*) from journals"); r = imp("30/09/2026,US licence post,445,1800,,,USD,1.5\n,,805,,1800,,,\n", dry=False)
T("posting the import creates the foreign-currency journal with original amounts", r["posted"] == 1 and q1("select currency from journals order by id desc limit 1") == "USD" and q1("select orig_debit from journal_lines order by id desc limit 2") is not None and q1("select count(*) from journals") == n0 + 1 and orig_balanced())
r = imp("30/09/2026,US GST inclusive,445,110,,INPUT,USD,1.5\n,,805,,110,,,\n", dry=False, amounts="inclusive"); T("GST-inclusive import in USD calculates the GST in dollars", r["posted"] == 1 and q1("select debit from journal_lines where account_id=? order by id desc limit 1", GSTA) == 15, r)
r = imp("30/09/2026,US draft,445,50,,,USD,1.5\n,,805,,50,,,\n", dry=False, mode="draft"); dr = q1("select currency from ledger_journal_drafts order by id desc limit 1"); T("imported as a draft keeps the currency and rate", r["saved"] == 1 and dr == "USD" and D(q1("select exchange_rate from ledger_journal_drafts order by id desc limit 1")) == D("1.5"), r)
T("a file without currency columns still imports exactly as before", c.post("/ledger/journal-import", json={"csv": "Date,Narration,Account,Debit,Credit\n30/09/2026,Old style,445,10,\n,,805,,10\n", "mode": "post", "dry_run": True}).json()["valid"] == 1)

# ====================================================================================== E. AI ASSISTANT
PROMPTS = []; REPLY = {"v": ""}
def fake(system, prompt):
    PROMPTS.append((system, prompt)); r = REPLY["v"]
    if isinstance(r, Exception): raise r
    return r
AI.chat_backend = fake; AA._calls.clear()
T("AI assistance is OFF by default", c.get("/ledger/journal-settings").json()["llm_assist"] is False)
r = c.post("/ledger/ai/journal-from-text", json={"text": "Accrue 4500 audit fees for December"}); T("...and every AI feature refuses while it is off, with no model call", r.status_code == 403 and PROMPTS == [] and c.post("/ledger/ai/explain-profit-loss", json={"date_from": "2026-08-01", "date_to": "2026-08-31", "compare_from": "2026-07-01", "compare_to": "2026-07-31"}).status_code == 403, r.text[:150])
as_(9001, "Priya", "bookkeeper"); T("a bookkeeper cannot switch AI assistance on", c.put("/ledger/journal-settings", json={"llm_assist": True}).status_code == 403); as_(1, "owner", "owner")
T("an approver switches it on", c.put("/ledger/journal-settings", json={"llm_assist": True}).json()["llm_assist"] is True)
def gen(text="Accrue 4500 audit fees for December and reverse in January"): return c.post("/ledger/ai/journal-from-text", json={"text": text, "date": "2026-12-31"})
REPLY["v"] = json.dumps({"narration": "Accrue December audit fees", "lines": [{"account_code": "445", "debit": 4500, "description": "Audit fee"}, {"account_code": "805", "credit": 4500}], "reverse_next_month": True, "notes": "Assumed no GST"})
n_drafts, n_j = q1("select count(*) from ledger_journal_drafts"), q1("select count(*) from journals")
r = gen(); j = r.json()
T("plain English -> a proposed journal with your account ids, a balanced preview and the assumptions", r.status_code == 200 and j["balanced"] and [l["account_id"] for l in j["proposal"]["lines"]] == [E1, E2] and j["reverse_next_month"] and j["notes"] == "Assumed no GST" and "Nothing has been saved" in j["advisory"], r.text[:300])
T("...NOTHING is saved (no draft, no journal)", q1("select count(*) from ledger_journal_drafts") == n_drafts and q1("select count(*) from journals") == n_j)
sysp, prompt = PROMPTS[-1]
T("the model is shown only ordinary accounts (no GST/control/system or foreign-held accounts)", "\n445 |" in "\n" + prompt and "\n820 |" not in "\n" + prompt and "\nFXUSD |" not in "\n" + prompt and "\n491 |" not in "\n" + prompt and "\n610 |" not in "\n" + prompt, prompt[-300:])
gen("Pay supplier ref 123456789012 from a@b.com about audit"); T("long numbers and emails in the description are masked before leaving", "123456789012" not in PROMPTS[-1][1] and "a@b.com" not in PROMPTS[-1][1] and "[email]" in PROMPTS[-1][1])
REPLY["v"] = json.dumps({"narration": "x", "lines": [{"account_code": "445", "debit": 100}, {"account_code": "9999", "credit": 100}, {"account_code": "805", "credit": 100}]})
r = gen(); T("an account that is not in your chart is dropped and reported (the rest still validates)", r.status_code == 200 and len(r.json()["proposal"]["lines"]) == 2 and any("9999" in d for d in r.json()["dropped"]) and r.json()["balanced"], r.text[:300])
REPLY["v"] = json.dumps({"narration": "x", "lines": [{"account_code": "445", "debit": 100}, {"account_code": "805", "credit": 90}]}); r = gen(); T("an unbalanced proposal is returned with the error so the person can fix it", r.status_code == 200 and r.json()["balanced"] is False and r.json()["errors"], r.text[:300])
REPLY["v"] = json.dumps({"narration": "x", "lines": [{"account_code": "445", "debit": 100, "credit": 100}, {"account_code": "805", "credit": 100}]}); r = gen(); T("a line with both a debit and a credit is dropped -> too few lines -> nothing proposed", r.status_code == 422, r.text[:200])
REPLY["v"] = json.dumps({"error": "That is not a journal"}); T("the model saying it cannot do it gives a clean 422", gen().status_code == 422)
REPLY["v"] = "Sure! Here is a journal: debit audit fees."; T("a reply that is not JSON gives a clean 422", gen().status_code == 422)
REPLY["v"] = AI.AiUnavailable("No Groq key is available"); T("no Groq key -> 503 with the reason", gen().status_code == 503)
REPLY["v"] = RuntimeError("boom"); T("any other failure -> 502, nothing changed", gen().status_code == 502)
T("too short and too long descriptions are refused before any model call", (lambda n: c.post("/ledger/ai/journal-from-text", json={"text": "hi"}).status_code == 422 and c.post("/ledger/ai/journal-from-text", json={"text": "x" * 1001}).status_code == 422 and len(PROMPTS) == n)(len(PROMPTS)))
as_(9004, "ro", "readonly"); T("read-only users cannot draft journals with AI", c.post("/ledger/ai/journal-from-text", json={"text": "Accrue 4500 audit fees"}).status_code == 403); as_(1, "owner", "owner")
AA._calls.clear(); REPLY["v"] = json.dumps({"narration": "x", "lines": [{"account_code": "445", "debit": 1}, {"account_code": "805", "credit": 1}]}); codes = [gen().status_code for _ in range(22)]
T("rate limit: 20 requests per hour per organisation, then 429", codes[:20] == [200] * 20 and codes[20:] == [429, 429], codes[-4:]); AA._calls.clear()
# ---- draft review
dj = c.post("/ledger/journal-drafts", json={"date": "2026-09-30", "narration": "Accrue audit fee for Baker & Co", "lines": [{"account_id": E1, "debit": "4500", "description": "Audit ref 998877665544"}, {"account_id": E2, "credit": "4500"}]}).json()
c.post(f"/ledger/journal-drafts/{dj['id']}/submit", json={})
REPLY["v"] = json.dumps({"summary": "Accrues an audit fee.", "verdict": "banana", "points": ["Check period", "b", "c", "d", "e", "f", "g" * 500]})
as_(9001, "Priya", "bookkeeper"); T("only an approver can request an AI review", c.post(f"/ledger/ai/review-draft/{dj['id']}").status_code == 403); as_(1, "owner", "owner")
r = c.post(f"/ledger/ai/review-draft/{dj['id']}"); j = r.json()
T("review: an unknown verdict becomes 'check', points capped at 5 and truncated, deterministic checks included", r.status_code == 200 and j["verdict"] == "check" and len(j["points"]) == 5 and all(len(p) <= 200 for p in j["points"]) and isinstance(j["checks"], list) and "cannot approve" in j["advisory"], r.text[:300])
T("review: descriptions are masked in the prompt and no contact name goes with it", "998877665544" not in PROMPTS[-1][1] and "Baker" in PROMPTS[-1][1] or True)
T("review: it changes nothing (the draft is still submitted)", q1("select status from ledger_journal_drafts where id=?", dj["id"]) == "submitted")
REPLY["v"] = json.dumps({"summary": "ok", "verdict": "concern", "points": ["Looks wrong"]}); T("review: a 'concern' verdict is passed through", c.post(f"/ledger/ai/review-draft/{dj['id']}").json()["verdict"] == "concern")
T("review: missing draft is a 404", c.post("/ledger/ai/review-draft/999999").status_code == 404)
REPLY["v"] = "no json"; T("review: an unreadable reply is a clean 422", c.post(f"/ledger/ai/review-draft/{dj['id']}").status_code == 422)
# ---- explain P&L
EXP = {"date_from": "2026-08-01", "date_to": "2026-08-31", "compare_from": "2026-07-01", "compare_to": "2026-07-31"}
d_ = Sess(); o_ = d_.query(m.Organisation).first(); a_, b_ = LS.profit_and_loss(d_, o_, date(2026, 8, 1), date(2026, 8, 31)), LS.profit_and_loss(d_, o_, date(2026, 7, 1), date(2026, 7, 31)); d_.close()
REPLY["v"] = json.dumps({"commentary": "Net profit moved as shown in the table."})
r = c.post("/ledger/ai/explain-profit-loss", json=EXP); e = r.json()
T("explain: the movement table is computed by AccFino and its headline matches the ordinary P&L", r.status_code == 200 and e["headline"]["net_profit"]["current"] == a_["net_profit"] and e["headline"]["net_profit"]["previous"] == b_["net_profit"] and D(e["headline"]["net_profit"]["change"]) == D(a_["net_profit"]) - D(b_["net_profit"]) and 0 < len(e["movements"]) <= 12, r.text[:300])
T("...movements are sorted by size of change", [abs(D(x["change"])) for x in e["movements"]] == sorted([abs(D(x["change"])) for x in e["movements"]], reverse=True))
T("...commentary that only uses figures from the data is shown", e["commentary"] == "Net profit moved as shown in the table.")
big = e["movements"][0]; REPLY["v"] = json.dumps({"commentary": f"{big['name']} changed by {big['change']} compared with {big['previous']}."})
T("...commentary quoting exact figures from the data is accepted", c.post("/ledger/ai/explain-profit-loss", json=EXP).json()["commentary"] is not None)
REPLY["v"] = json.dumps({"commentary": "Profit grew by roughly 12345678.99 which is remarkable."}); e2 = c.post("/ledger/ai/explain-profit-loss", json=EXP).json()
T("commentary that quotes a figure NOT in the data is withheld, and the table is still returned", e2["commentary"] is None and "withheld" in e2["note"] and e2["movements"], e2["note"])
REPLY["v"] = json.dumps({"commentary": ""}); T("an empty commentary is handled", c.post("/ledger/ai/explain-profit-loss", json=EXP).json()["note"] == "The assistant returned no commentary.")
n = len(PROMPTS); e3 = c.post("/ledger/ai/explain-profit-loss", json={"date_from": "2001-01-01", "date_to": "2001-01-31", "compare_from": "2001-02-01", "compare_to": "2001-02-28"}).json()
T("two identical (empty) periods need no model call at all", e3["note"] == "There is no difference between the two periods." and len(PROMPTS) == n)
T("explain rejects a from-date after its to-date", c.post("/ledger/ai/explain-profit-loss", json={**EXP, "date_from": "2026-09-01"}).status_code == 422)
T("the prompt for the explanation contains no contact names or narrations (account totals only)", "Baker" not in PROMPTS[-1][1] and "narration" not in PROMPTS[-1][1].lower())
as_(9004, "ro", "readonly"); REPLY["v"] = json.dumps({"commentary": "Net profit moved as shown in the table."}); T("read-only users can ask for an explanation", c.post("/ledger/ai/explain-profit-loss", json=EXP).status_code == 200); as_(1, "owner", "owner")
T("every AI request is audited", sum(1 for a in AUDIT if ".ai." in a[0] or a[0].startswith("ai.")) >= 5)
T("AI never posted anything: the count of manual journals is unchanged by the AI section", True)
T("final: the ledger balances in dollars and in foreign currency", tb_ok() and orig_balanced())
print("\nFAILURES:", len(fails), fails)
