import os, shutil, sys, json
sys.path.insert(0, "/home/claude/w/AccFino/backend"); os.environ["DATABASE_URL"] = "postgresql://x:y@localhost/none"
shutil.copy("/tmp/demo.db", "/tmp/fx.db")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from accfino_core import models as m
from accfino_core.api import books_reports
from accfino_core.security.context import OrgContext, current_org
from db_app.database import get_db
eng = create_engine("sqlite:////tmp/fx.db", connect_args={"check_same_thread": False}); S = sessionmaker(bind=eng)
app = FastAPI(); app.include_router(books_reports.ledger_reports, prefix="/ledger/reports")
def _db():
    d = S()
    try: yield d
    finally: d.close()
app.dependency_overrides[get_db] = _db
app.dependency_overrides[current_org] = lambda: OrgContext(1, "owner", False, S().query(m.Organisation).first(), "owner")
c = TestClient(app)
with eng.connect() as k:
    bank = k.exec_driver_sql("select id from ledger_accounts where code='090'").scalar(); gst = k.exec_driver_sql("select id from ledger_accounts where code='820'").scalar()
r = c.get("/ledger/reports/general-ledger-detail", params={"from": "2026-09-01", "to": "2026-09-30", "account_ids": [bank, gst]}).json()
for g in r["groups"]: g["rows"] = g["rows"][:6]           # keep the fixture small; totals stay real
fx = json.load(open("/home/claude/w/AccFino/frontend/src/pages/accounting/__tests__/fixtures/extraReports.json")); fx["glDetail"] = r
json.dump(fx, open("/home/claude/w/AccFino/frontend/src/pages/accounting/__tests__/fixtures/extraReports.json", "w"))
print(r["group_count"], r["line_count"], [(g["label"], g["opening"], g["closing"]) for g in r["groups"]])
