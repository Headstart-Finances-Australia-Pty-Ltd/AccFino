"""
Migration: restructure pricing_plans from a single `data` JSON blob column
into real per-field columns (name, description, price_monthly, etc).

Runs from react_api.py's startup hook -- idempotent, safe on every boot:
  - If the table doesn't exist yet, creates it with the new column shape
    directly (fresh installs never see the old shape at all).
  - If the table exists with the OLD shape (a `data` column), adds the
    new columns, backfills them from `data` for every existing row, then
    drops `data`.
  - If the table already has the new shape, does nothing.

Also re-syncs from pricing.json every run (same self-healing reconcile
pattern as create_coa_kb_pricing_lending.py) so a plan added to the JSON
file later still lands in Postgres even after this migration's first run.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
_PRICING_CANDIDATES = [_ROOT / "main_app" / "data" / "pricing.json"]


def _first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    return None


_NEW_COLUMNS = {
    "name": "VARCHAR(200)",
    "description": "VARCHAR(1000)",
    "price_monthly": "INTEGER DEFAULT 0",
    "price_yearly": "INTEGER DEFAULT 0",
    "badge": "VARCHAR(50)",
    "highlight": "BOOLEAN DEFAULT FALSE",
    "category": "VARCHAR(50)",
    "features": "JSON",
    "modules": "JSON",
    "price_effective_from": "VARCHAR(20)",
}


def run(engine):
    from sqlalchemy import text, inspect

    insp = inspect(engine)

    if not insp.has_table("pricing_plans"):
        with engine.begin() as conn:
            cols_sql = ",\n".join(f"{name} {sqltype}" for name, sqltype in _NEW_COLUMNS.items())
            conn.execute(text(f"""
                CREATE TABLE pricing_plans (
                    slug VARCHAR(50) PRIMARY KEY,
                    {cols_sql},
                    sort_order INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
        logger.info("Migration: created pricing_plans table (new column shape)")
    else:
        existing_cols = {c["name"] for c in insp.get_columns("pricing_plans")}
        had_old_blob = "data" in existing_cols
        with engine.begin() as conn:
            for name, sqltype in _NEW_COLUMNS.items():
                if name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE pricing_plans ADD COLUMN {name} {sqltype}"))
            if had_old_blob:
                logger.info("Migration: pricing_plans has old `data` blob column -- backfilling new columns from it")
                rows = conn.execute(text("SELECT slug, data FROM pricing_plans")).fetchall()
                for slug, data in rows:
                    if not data:
                        continue
                    conn.execute(text("""
                        UPDATE pricing_plans SET
                            name = :name, description = :description,
                            price_monthly = :price_monthly, price_yearly = :price_yearly,
                            badge = :badge, highlight = :highlight, category = :category,
                            features = :features, modules = :modules,
                            price_effective_from = :price_effective_from
                        WHERE slug = :slug
                    """), {
                        "slug": slug,
                        "name": data.get("name"),
                        "description": data.get("description"),
                        "price_monthly": data.get("price_monthly", 0),
                        "price_yearly": data.get("price_yearly", 0),
                        "badge": data.get("badge"),
                        "highlight": bool(data.get("highlight", False)),
                        "category": data.get("category"),
                        "features": json.dumps(data.get("features", [])),
                        "modules": json.dumps(data.get("modules", [])),
                        "price_effective_from": data.get("price_effective_from"),
                    })
                conn.execute(text("ALTER TABLE pricing_plans DROP COLUMN data"))
                logger.info(f"Migration: backfilled {len(rows)} pricing_plans row(s) into new columns, dropped old `data` column")

    # Reconcile from pricing.json every run (same pattern as
    # create_coa_kb_pricing_lending.py) -- a plan added to the JSON file
    # after this migration already ran still needs to reach Postgres.
    pricing_path = _first_existing(_PRICING_CANDIDATES)
    if not pricing_path:
        return
    try:
        plans = json.loads(pricing_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Migration: could not parse {pricing_path}: {e}")
        return

    synced = 0
    with engine.begin() as conn:
        for i, (slug, p) in enumerate(plans.items()):
            existing = conn.execute(text("SELECT 1 FROM pricing_plans WHERE slug = :slug"), {"slug": slug}).first()
            if existing:
                continue  # don't overwrite admin edits made directly in Postgres
            conn.execute(text("""
                INSERT INTO pricing_plans
                    (slug, name, description, price_monthly, price_yearly, badge,
                     highlight, category, features, modules, price_effective_from, sort_order)
                VALUES
                    (:slug, :name, :description, :price_monthly, :price_yearly, :badge,
                     :highlight, :category, :features, :modules, :price_effective_from, :sort_order)
            """), {
                "slug": slug,
                "name": p.get("name"),
                "description": p.get("description"),
                "price_monthly": p.get("price_monthly", 0),
                "price_yearly": p.get("price_yearly", 0),
                "badge": p.get("badge"),
                "highlight": bool(p.get("highlight", False)),
                "category": p.get("category"),
                "features": json.dumps(p.get("features", [])),
                "modules": json.dumps(p.get("modules", [])),
                "price_effective_from": p.get("price_effective_from"),
                "sort_order": i,
            })
            synced += 1
    if synced:
        logger.info(f"Migration: synced {synced} missing pricing plan(s) from {pricing_path} into Postgres")
