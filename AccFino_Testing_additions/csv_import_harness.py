"""Loads mockdata/csv/*.csv into a fresh organisation (SQLite, offline) through accfino_core.books.csv_import and runs the app's own
cross-report checks (seed_demo.verify). Usage (from backend/):  python ../AccFino_Testing_additions/csv_import_harness.py [csv_dir] [--today 2026-09-30]"""
import os, sys, glob
from datetime import date
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://offline:offline@localhost/none")
os.environ.setdefault("JWT_SECRET", "x" * 64)
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
import db_app.models  # noqa
import accfino_core.subscription.models  # noqa  (registers the subscription tables for create_all)
import accfino_core.tenancy.models  # noqa  (registers the tenancy tables for create_all)
from accfino_core import models as m
from accfino_core.books import csv_import as CI
from accfino_core.books import reports as R
from accfino_core.ledger import journal_tools as JT
from accfino_core.books import banking as K
from accfino_core import seed_demo as SD


def make_db(path=":memory:"):
    from sqlalchemy.pool import StaticPool
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(eng, "connect")
    def _c(dbapi, _):
        dbapi.isolation_level = None
        dbapi.execute("PRAGMA foreign_keys=ON")
    @event.listens_for(eng, "begin")
    def _b(conn):
        conn.exec_driver_sql("BEGIN")
    m.Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, autoflush=False)()


def make_org(db, bank_code="090"):
    user, _ = SD._get_or_create_user(db, "tester@example.com")
    org = SD._make_org(db, user, "CSV Test Pty Ltd")
    from accfino_core.migrate import seed_org_ledger
    seed_org_ledger(db, org)
    db.add(m.LedgerAccount(org_id=org.id, code=bank_code, name="Business Cheque Account", account_type="bank", account_class=m.ACCOUNT_TYPES["bank"]))
    db.commit()
    return org, SD.Ctx(user.id, "owner", org)


ORDER = [("01_customers", "customers"), ("02_suppliers", "suppliers"), ("03_journals", "journals"), ("04_inventory_items", "inventory_items"), ("05_quotes", "quotes"),
         ("06_invoices", "invoices"), ("07_credit_notes", "credit_notes"), ("08_receipts", "receipts"), ("09_purchase_orders", "purchase_orders"), ("10_bills", "bills"),
         ("11_supplier_credits", "supplier_credits"), ("12_supplier_payments", "supplier_payments"), ("13_fixed_assets", "fixed_assets"), ("14_expense_claims", "expense_claims"),
         ("15_stock_movements", "stock_movements")]


def load_all(db, org, ctx, folder, log=print, stop_on_error=True):
    results = {}
    for stem, ent in ORDER:
        raw = open(os.path.join(folder, stem + ".csv"), "rb").read()
        if ent == "journals":
            res = JT.import_journals(db, org, ctx, raw.decode("utf-8"), mode="post", dry_run=False)
            ok = not res.get("error"); n = res["count"]; bad = [(j["row"], j["errors"]) for j in res["journals"] if j["errors"]]
            if ok: db.commit()
        else:
            dry = CI.run_import(db, org, ctx, ent, raw, dry_run=True)
            res = CI.run_import(db, org, ctx, ent, raw, dry_run=False) if not dry["error"] else dry
            ok = not res["error"]; n = res["count"]; bad = [(i["row"], i["errors"]) for i in res["items"] if i["errors"]]
            if ok: db.commit()
            else: db.rollback()
            for w in res["warnings"]: log("      warn:", w[:200])
        results[ent] = res
        log(f"{'OK  ' if ok else 'FAIL'} {ent:18s} {n:4d} record(s)" + ("" if ok else f"  {len(bad)} problem(s), first: {bad[:3]}"))
        if not ok and stop_on_error: break
    return results


if __name__ == "__main__":
    folder = next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join(os.path.dirname(__file__), "..", "mockdata", "csv"))
    today = date.fromisoformat(sys.argv[sys.argv.index("--today") + 1]) if "--today" in sys.argv else date(2026, 9, 30)
    db = make_db(); org, ctx = make_org(db)
    res = load_all(db, org, ctx, folder)
    if all(not r.get("error") for r in res.values()) and len(res) == len(ORDER):
        ok, bad = SD.verify(db, org, today)
        for n, d in ok: print("  PASS ", n)
        for n, d in bad: print("  FAIL ", n, "->", d)
