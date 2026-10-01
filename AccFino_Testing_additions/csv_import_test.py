"""Tests for accfino_core.books.csv_import and /imports. Run from backend/:  PYTHONPATH=. python -m pytest ../AccFino_Testing_additions/csv_import_test.py -q
Offline (SQLite). Loads the shipped mockdata/csv set end to end and checks the safety behaviour of the importer."""
import io, os, sys
from datetime import date
from decimal import Decimal
import pytest
sys.path.insert(0, os.path.dirname(__file__))
from csv_import_harness import make_db, make_org, load_all, ORDER, SD
from accfino_core import models as m
from accfino_core.books import csv_import as CI, models as b, reports as R
from accfino_core.inventory import models as inv
from accfino_core.assets import models as fa

CSV_DIR = os.path.join(os.path.dirname(__file__), "..", "mockdata", "csv")
TODAY = date(2026, 9, 30)


@pytest.fixture()
def env():
    db = make_db(); org, ctx = make_org(db)
    yield db, org, ctx
    db.close()


@pytest.fixture(scope="module")
def loaded():
    db = make_db(); org, ctx = make_org(db)
    res = load_all(db, org, ctx, CSV_DIR, log=lambda *a: None)
    yield db, org, ctx, res
    db.close()


def imp(env, entity, text, dry=False, **opts):
    db, org, ctx = env
    return CI.run_import(db, org, ctx, entity, text.encode(), dry_run=dry, options=opts)


# ------------------------------------------------------------------------------------------ the shipped data set
def test_every_shipped_file_imports_cleanly(loaded):
    _, _, _, res = loaded
    assert len(res) == len(ORDER) and all(not r.get("error") for r in res.values())


def test_core_controls_pass_after_full_load(loaded):
    db, org, _, _ = loaded
    ok, bad = SD.verify(db, org, TODAY)
    failing = {n for n, _ in bad}
    # Only checks that depend on demo-seeder content (budgets, drafts, AI suggestions) or the manual-BAS-journal caveat may fail
    allowed = {"GST/BAS: GST account movement = 1A - 1B", "Budget variance has a budget (and actuals once the year is under way)", "Ledger health: drafts, approvals and AI suggestions exist"}
    assert failing <= allowed, failing
    assert len(ok) >= 17


def test_record_counts(loaded):
    db, org, _, _ = loaded
    q = lambda M, **k: db.query(M).filter_by(org_id=org.id, **k).count()
    assert q(b.Contact) == 26 and q(inv.StockItem) == 6 and q(fa.FixedAsset) == 7 and q(b.ExpenseClaim) == 10
    assert {d.status for d in db.query(b.Doc).filter_by(org_id=org.id, doc_type="quote")} == {"draft", "sent", "accepted", "declined"}
    assert {c.status for c in db.query(b.ExpenseClaim).filter_by(org_id=org.id)} == {"draft", "submitted", "approved", "rejected", "paid"}


def test_aged_reports_have_every_bucket(loaded):
    db, org, _, _ = loaded
    for side in ("sales", "purchases"):
        a = R.aged(db, org, side, TODAY)
        assert sum(1 for v in a["buckets"].values() if Decimal(v) > 0) >= 4, (side, a["buckets"])       # the ageing report is populated across the buckets


# ------------------------------------------------------------------------------------------ safety behaviour
GOOD_CUST = "name,abn,terms_days\nAcme Pty Ltd,51 824 753 556,14\n"


def test_dry_run_saves_nothing(env):
    db, org, _ = env
    r = imp(env, "customers", GOOD_CUST, dry=True)
    assert not r["error"] and r["valid"] == 1 and r["saved"] == 0
    assert db.query(b.Contact).filter_by(org_id=org.id).count() == 0


def test_bad_abn_blocks_the_whole_file(env):
    db, org, _ = env
    r = imp(env, "customers", "name,abn\nGood Co,51 824 753 556\nBad Co,12 345 678 901\n")
    assert r["error"] and r["invalid"] == 1 and r["saved"] == 0
    assert "ABN" in r["items"][0]["errors"][0]                      # problems are listed first
    assert db.query(b.Contact).filter_by(org_id=org.id).count() == 0


def test_missing_required_column_is_a_clear_error(env):
    with pytest.raises(Exception) as e:
        imp(env, "invoices", "number,customer\nINV-1,Acme\n")
    assert "missing required column" in str(e.value)


INV_OK = "number,customer,issue_date,line_description,qty,unit_price,account,tax_code\nINV-9001,Acme Pty Ltd,2026-08-01,Consulting,2,500,200,OUTPUT\n,,,Second line,1,100,200,OUTPUT\n"


def test_invoice_posts_to_ledger_with_gst_and_reload_is_refused(env):
    db, org, ctx = env
    imp(env, "customers", GOOD_CUST); db.commit()
    r = imp(env, "invoices", INV_OK); db.commit()
    assert r["saved"] == 1 and r["total"] == "1210.00"              # (2x500 + 100) + 10% GST
    doc = db.query(b.Doc).filter_by(org_id=org.id, number="INV-9001").one()
    assert doc.status == "approved" and doc.journal_id and doc.tax_total == Decimal("110.00")
    again = imp(env, "invoices", INV_OK)
    assert again["error"] and "already exists" in again["items"][0]["errors"][0]


def test_unknown_customer_is_created_with_a_warning(env):
    r = imp(env, "invoices", INV_OK, dry=True)
    assert not r["error"] and "will be created" in r["items"][0]["warnings"][0]


def test_draft_mode_does_not_post(env):
    db, org, _ = env
    imp(env, "invoices", INV_OK, mode="draft"); db.commit()
    d = db.query(b.Doc).filter_by(org_id=org.id, number="INV-9001").one()
    assert d.status == "draft" and d.journal_id is None


def test_receipt_cannot_exceed_amount_owing(env):
    db, org, _ = env
    imp(env, "customers", GOOD_CUST); imp(env, "invoices", INV_OK); db.commit()
    r = imp(env, "receipts", "date,customer,bank_account,invoice,amount\n2026-08-10,Acme Pty Ltd,090,INV-9001,5000\n")
    assert r["error"] and "Over-allocation" in r["items"][0]["errors"][0]
    ok = imp(env, "receipts", "date,customer,bank_account,invoice,amount\n2026-08-10,Acme Pty Ltd,090,INV-9001,1210\n"); db.commit()
    assert not ok["error"] and db.query(b.Doc).filter_by(org_id=org.id, number="INV-9001").one().status == "paid"


def test_supplier_reference_duplicate_is_refused(env):
    bills = ("number,supplier,issue_date,reference,line_description,unit_price,account,tax_code\n"
             "B-1,Office Co,2026-08-01,OC-77,Paper,100,453,INPUT\nB-2,Office Co,2026-08-02,OC-77,Paper again,100,453,INPUT\n")
    r = imp(env, "bills", bills)
    assert r["error"] and "possible duplicate bill" in r["items"][0]["errors"][0]


def test_aliases_delimiters_and_date_formats(env):
    r = imp(env, "customers", "Customer Name;Email Address;Payment Terms\nAlpha Ltd;a@x.com;30\n", dry=True)      # semicolon CSV, aliased headers
    assert not r["error"] and r["valid"] == 1
    r2 = imp(env, "invoices", "number,customer,date,description,price,account\nI1,Zed,31/07/2026,Work,$1,200.00,200\n".replace("$1,200.00", '"$1,200.00"'), dry=True)
    assert not r2["error"], r2


def test_stock_movements_are_applied_in_date_order_and_cannot_oversell(env):
    db, org, _ = env
    imp(env, "inventory_items", "sku,name\nA1,Item\n"); db.commit()
    r = imp(env, "stock_movements", "date,sku,kind,quantity,unit_cost,account\n2026-08-05,A1,sell,5,,\n2026-08-01,A1,buy,10,4.00,090\n", dry=True)   # sell listed first but dated later
    assert not r["error"], r
    r = imp(env, "stock_movements", "date,sku,kind,quantity,unit_cost,account\n2026-08-05,A1,sell,50,,\n2026-08-01,A1,buy,10,4.00,090\n", dry=True)
    assert r["error"] and "on hand" in r["items"][0]["errors"][0]


def test_claims_large_gst_receipt_needs_attachment_before_submit(env):
    db, org, _ = env
    csv_ = "claim,title,status,date,description,account,tax_code,amount\nC1,Flights,submitted,2026-08-01,Flight,493,INPUT,412.00\n"
    r = imp(env, "expense_claims", csv_)
    assert r["error"] and "82.5" in r["items"][0]["errors"][0]
    assert not imp(env, "expense_claims", csv_.replace("submitted", "draft"), dry=True)["error"]


def test_templates_round_trip_through_their_own_importer():
    for key in CI.SPECS:
        text = CI.template_csv(key)
        head = text.splitlines()[0].split(",")
        assert len(head) == len(CI.SPECS[key].columns)
        try:                                                     # the header must be understood by the importer itself
            CI._records(CI.SPECS[key], CI._grid(text), dict(warnings=[]))
        except Exception as e:
            pytest.fail(f"{key} template: {e}")


# ------------------------------------------------------------------------------------------ the HTTP layer
def test_http_endpoints(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from accfino_core.api import books_import
    from accfino_core.books.common import BooksError
    from accfino_core.security.context import OrgContext, current_org
    from db_app.database import get_db
    from fastapi.responses import JSONResponse
    db, org, ctx = env
    app = FastAPI()
    app.include_router(books_import.router, prefix="/imports")
    app.exception_handler(BooksError)(lambda req, exc: JSONResponse({"detail": str(exc)}, status_code=exc.status))
    role = {"v": "owner"}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_org] = lambda: OrgContext(ctx.user_id, "tester", False, org, role["v"])
    c = TestClient(app)
    assert any(i["entity"] == "invoices" for i in c.get("/imports").json()["items"])
    assert c.get("/imports/bills/template").text.startswith("number,supplier,issue_date")
    assert c.get("/imports/nope/template").status_code == 404
    files = {"file": ("c.csv", GOOD_CUST, "text/csv")}
    r = c.post("/imports/customers", files=files, data={"dry_run": "true"}).json()
    assert r["valid"] == 1 and r["saved"] == 0 and db.query(b.Contact).count() == 0
    r = c.post("/imports/customers", files={"file": ("c.csv", GOOD_CUST, "text/csv")}, data={"dry_run": "false"}).json()
    assert r["saved"] == 1 and db.query(b.Contact).count() == 1
    bad = c.post("/imports/customers", files={"file": ("c.csv", "x\n1\n", "text/csv")}, data={"dry_run": "true"})
    assert bad.status_code == 422 and "missing required column" in bad.json()["detail"]
    role["v"] = "readonly"
    assert c.post("/imports/customers", files={"file": ("c.csv", GOOD_CUST, "text/csv")}).status_code == 403


# ------------------------------------------------------------------------------------------ platform switch (Admin > Modules Management)
def test_bulk_import_switch_blocks_every_bulk_endpoint(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from fastapi.responses import JSONResponse
    from accfino_core.api import books_import, books_docs, ledger_tools
    from accfino_core.books.common import BooksError
    from accfino_core.security.context import OrgContext, current_org, current_auth
    from db_app.database import get_db
    db, org, ctx = env
    app = FastAPI()
    app.include_router(books_import.router, prefix="/imports")
    app.include_router(books_import.admin_router, prefix="/admin/bulk-import")
    app.include_router(books_docs.contacts_router, prefix="/contacts")
    app.include_router(ledger_tools.router, prefix="/ledger")
    app.exception_handler(BooksError)(lambda req, exc: JSONResponse({"detail": str(exc)}, status_code=exc.status))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_org] = lambda: OrgContext(ctx.user_id, "tester", False, org, "owner")
    app.dependency_overrides[current_auth] = lambda: {"user_id": ctx.user_id, "username": "admin", "is_admin": True}
    c = TestClient(app)
    f = lambda: {"file": ("c.csv", GOOD_CUST, "text/csv")}
    assert c.get("/imports/status").json() == {"enabled": True}                         # on by default
    assert c.post("/imports/customers", files=f(), data={"dry_run": "true"}).status_code == 200
    assert c.put("/admin/bulk-import", json={"enabled": False}).json() == {"enabled": False}
    assert c.get("/admin/bulk-import").json() == {"enabled": False}
    assert c.get("/imports/status").json() == {"enabled": False}                        # status stays readable so the app can hide buttons
    for r in (c.post("/imports/customers", files=f(), data={"dry_run": "true"}), c.get("/imports"), c.get("/imports/bills/template"),
              c.post("/contacts/import", files=f()), c.post("/ledger/journal-import", json={"csv": "Date,Account\n", "mode": "draft", "dry_run": True})):
        assert r.status_code == 403 and "switched off" in r.json()["detail"], r.text
    assert db.query(b.Contact).count() == 0
    assert c.put("/admin/bulk-import", json={"enabled": True}).json() == {"enabled": True}
    assert c.post("/imports/customers", files=f(), data={"dry_run": "true"}).status_code == 200
