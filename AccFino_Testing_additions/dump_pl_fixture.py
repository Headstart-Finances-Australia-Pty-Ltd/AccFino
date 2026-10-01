import os, shutil, sys, json
sys.path.insert(0, "/home/claude/w/AccFino/backend"); os.environ["DATABASE_URL"] = "postgresql://x:y@localhost/none"
shutil.copy("/tmp/adv_test.db", "/tmp/fx2.db")           # the advanced-test database: it contains splits, multi-option lines and unassigned amounts
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from accfino_core import models as m
from accfino_core.api import books_reports
from accfino_core.security.context import OrgContext, current_org
from db_app.database import get_db
eng = create_engine("sqlite:////tmp/fx2.db", connect_args={"check_same_thread": False}); S = sessionmaker(bind=eng)
app = FastAPI(); app.include_router(books_reports.ledger_reports, prefix="/ledger/reports")
def _db():
    d = S()
    try: yield d
    finally: d.close()
app.dependency_overrides[get_db] = _db; app.dependency_overrides[current_org] = lambda: OrgContext(1, "owner", False, S().query(m.Organisation).first(), "owner")
c = TestClient(app); cid = eng.connect().exec_driver_sql("select id from tracking_categories order by id").scalar()
r = c.get("/ledger/reports/profit-loss-by-tracking", params={"from": "2025-07-01", "to": "2026-09-30", "category_id": cid}).json()
fx = json.load(open("/home/claude/w/AccFino/frontend/src/pages/accounting/__tests__/fixtures/extraReports.json")); fx["plTracking"] = r
json.dump(fx, open("/home/claude/w/AccFino/frontend/src/pages/accounting/__tests__/fixtures/extraReports.json", "w"))
print([c_["name"] for c_ in r["columns"]], r["net_profit"]["total"], r["matches_profit_loss"])
