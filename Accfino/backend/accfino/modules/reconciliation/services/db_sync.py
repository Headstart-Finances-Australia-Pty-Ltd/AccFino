"""
accfino.modules.reconciliation.services.db_sync
-----------------------------------------------
Postgres is authoritative for the Chart of Accounts and the Knowledge Base. The TF-IDF classifier engine still reads flat files,
so after every write the matching file is regenerated (a derived cache; deleted files are recreated from Postgres on the next sync).
The files live in the data root (reference/), outside the application package.
"""
import csv
import json

from accfino.modules.reconciliation.models.reference import ChartOfAccount, KnowledgeBase
from accfino.shared import paths
from accfino.shared.db.database import SessionLocal


def sync_coa_csv_from_db():
    """Regenerates ChartOfAccounts.csv from the chart_of_accounts table."""
    db = SessionLocal()
    try:
        rows = db.query(ChartOfAccount).order_by(ChartOfAccount.name).all()
        path = paths.reference_dir() / "ChartOfAccounts.csv"
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["*Name", "*Type"])
            for r in rows:
                writer.writerow([r.name, r.type or ""])
    finally:
        db.close()


def sync_kb_json_from_db():
    """Regenerates knowledge_base.json from the knowledge_base table (row id=1)."""
    db = SessionLocal()
    try:
        row = db.get(KnowledgeBase, 1)
        data = row.data if row else {}
        (paths.reference_dir() / "knowledge_base.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        db.close()
