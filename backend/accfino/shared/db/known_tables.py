"""
accfino/shared/db/known_tables.py
-----------------------------------------------------------------------------
The definitive list of tables that belong to AccFino.

Why this exists: AccFino's Postgres database is shared with at least one
other application (TalentIQ) in the same 'public' schema. Naively listing
"every table in the public schema" (what db_browser.py and the file
manager's Postgres node used to do) leaks the other app's tables straight
into AccFino's admin UI -- e.g. jobintel_records, job_matches, resumes,
skill_taxonomy are TalentIQ tables, not AccFino's, and have no business
being editable from here.

This combines:
  1. Every table SQLAlchemy's ORM models know about (every registered model,
     Base.metadata.tables) -- covers users, transactions, invoices, etc.
  2. Tables created by raw-SQL migrations that have no ORM model (see
     db_app/migrations/*.py) -- accounting_*, payroll_*, account_balances,
     stp_submissions.

If you add a new table via a raw-SQL migration (not an ORM model), declare it in
that module's manifest (raw_sql_tables) or it won't show up in the table browser.
"""

def get_accfino_table_names() -> set:
    """Returns every table name that actually belongs to AccFino."""
    from accfino.shared.contracts import registry
    try:
        from accfino.shared.db.base import Base
        registry.import_all_models()       # import triggers model registration onto Base.metadata
        orm_tables = set(Base.metadata.tables.keys())
    except Exception:
        orm_tables = set()
    return orm_tables | registry.raw_sql_tables()
