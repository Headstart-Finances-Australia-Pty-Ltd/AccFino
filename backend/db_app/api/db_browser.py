"""
db_app/api/db_browser.py
-----------------------------------------------------------------------------
Generic Postgres table browser for the File Manager's "Database" view --
same idea as TalentIQ's admin table editor (list tables, inspect schema,
browse/edit/delete/insert rows), adapted for AccFino:

  - Not restricted to a table-name prefix (TalentIQ used "tiq_*"); AccFino's
    tables don't share one, so this lists every table in the public schema.
  - PK-aware rather than assuming every table has an integer "id" column --
    AccFino has both (rdr_rules.id and pricing_plans.slug are VARCHAR
    primary keys, groq_key_pool.id is an integer) so the primary key
    column is looked up per-table via SQLAlchemy's inspector instead of
    being hardcoded.

Routes (all prefixed /db-browser in react_api.py):
  GET    /db-browser/tables                    List all tables + row counts
  GET    /db-browser/tables/{table}/schema      Column names/types/nullability
  GET    /db-browser/tables/{table}/rows        Paginated rows (+ optional search)
  PUT    /db-browser/tables/{table}/rows/{id}   Update one row (by its real PK)
  DELETE /db-browser/tables/{table}/rows/{id}   Delete one row
  DELETE /db-browser/tables/{table}/rows        Bulk delete by id list
  POST   /db-browser/tables/{table}/rows        Insert a new row
  POST   /db-browser/tables/{table}/upload-csv  Bulk upsert rows from a CSV file
  POST   /db-browser/query                      Read-only SELECT passthrough

No table-name allowlist is enforced beyond "must actually exist in the
public schema" -- same trust model as the rest of this app's admin
endpoints (gated client-side via <Guard adminOnly>, not a server-side
role check yet). Treat this like any other admin-only tool: don't expose
these routes to non-admin users in the frontend.
"""
import csv
import io
import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import text, inspect, bindparam

from db_app.database import SessionLocal, engine
from db_app.known_tables import get_accfino_table_names

router = APIRouter()

# Tables that exist but deserve a caution note in the UI (schema/auth data,
# not ordinary business data). Still fully visible/editable -- same trust
# model as the rest of this app's admin tools -- just flagged.
_SENSITIVE_NOTE = {"users": "Contains password hashes -- edit with care."}


def _pk_column(table: str) -> str:
    """Returns the actual primary key column name for a table, instead of
    assuming "id" -- e.g. rdr_rules.id and pricing_plans.slug are VARCHAR
    PKs, not integers, and the column name itself varies (slug vs id)."""
    if table not in get_accfino_table_names():
        raise HTTPException(404, f"Table '{table}' does not exist.")
    insp = inspect(engine)
    if not insp.has_table(table):
        raise HTTPException(404, f"Table '{table}' does not exist.")
    pk = insp.get_pk_constraint(table).get("constrained_columns") or []
    if not pk:
        raise HTTPException(400, f"Table '{table}' has no primary key -- cannot browse/edit rows generically.")
    return pk[0]  # composite PKs aren't supported by this generic editor


def _serialize_row(row: dict) -> dict:
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            row[k] = v.isoformat()
        elif v is not None and not isinstance(v, (int, float, bool, str, dict, list)):
            row[k] = str(v)
    return row


@router.get("/tables")
def list_tables():
    """List every table in the public schema with its row count and PK column.

    Uses 2 batched queries total, regardless of how many tables exist --
    previously this ran a COUNT(*) plus a separate PK lookup for EVERY
    table in a loop (2N round-trips), which on a remote/serverless
    Postgres like Neon added real, noticeable latency as tables grew.

    Row counts come from pg_class.reltuples (Postgres's own planner
    statistics, refreshed by autovacuum/ANALYZE) rather than a live
    COUNT(*) scan -- this is what pgAdmin/DBeaver/etc. show by default
    for exactly this performance reason. It's an estimate, not exact to
    the row -- open a specific table (table_rows below) for a precise count.
    """
    db = SessionLocal()
    try:
        accfino_tables = get_accfino_table_names()

        # -- Batch 1: every table + its approximate row count, one query --
        count_rows = db.execute(text("""
            SELECT c.relname AS table_name, c.reltuples::bigint AS approx_rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r' AND n.nspname = 'public'
            ORDER BY c.relname
        """)).fetchall()
        count_rows = [r for r in count_rows if r.table_name in accfino_tables]

        # -- Batch 2: every table's primary key column, one query --
        pk_rows = db.execute(text("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
        """)).fetchall()
        pk_by_table: Dict[str, str] = {}
        for tname, col in pk_rows:
            pk_by_table.setdefault(tname, col)  # first column wins for composite PKs

        tables = []
        for tname, approx_rows in count_rows:
            tables.append({
                "table": tname,
                "rows": max(int(approx_rows), 0),
                "pk_column": pk_by_table.get(tname),
                "note": _SENSITIVE_NOTE.get(tname),
            })
        return tables
    finally:
        db.close()


@router.get("/tables/{table}/schema")
def table_schema(table: str):
    if table not in get_accfino_table_names():
        raise HTTPException(404, f"Table '{table}' does not exist.")
    insp = inspect(engine)
    if not insp.has_table(table):
        raise HTTPException(404, f"Table '{table}' does not exist.")
    cols = []
    pk_cols = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
    for c in insp.get_columns(table):
        cols.append({
            "column_name": c["name"],
            "data_type": str(c["type"]),
            "is_nullable": c.get("nullable", True),
            "is_primary_key": c["name"] in pk_cols,
        })
    return cols


@router.get("/tables/{table}/rows")
def table_rows(table: str, page: int = 1, page_size: int = 50, search: Optional[str] = None):
    if table not in get_accfino_table_names():
        raise HTTPException(404, f"Table '{table}' does not exist.")
    insp = inspect(engine)
    if not insp.has_table(table):
        raise HTTPException(404, f"Table '{table}' does not exist.")
    pk_col = _pk_column(table)
    offset = (page - 1) * page_size

    db = SessionLocal()
    try:
        total = db.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()

        where_clause = ""
        params: Dict[str, Any] = {"lim": page_size, "off": offset}
        if search:
            # Search across every text-like column with a simple ILIKE OR chain.
            col_types = {c["name"]: str(c["type"]).upper() for c in insp.get_columns(table)}
            text_cols = [c for c, t in col_types.items() if any(k in t for k in ("CHAR", "TEXT"))]
            if text_cols:
                where_clause = "WHERE " + " OR ".join(f'"{c}"::text ILIKE :search' for c in text_cols)
                params["search"] = f"%{search}%"

        rows = db.execute(
            text(f'SELECT * FROM "{table}" {where_clause} ORDER BY "{pk_col}" DESC LIMIT :lim OFFSET :off'),
            params,
        )
        cols = list(rows.keys())
        data = [_serialize_row(dict(zip(cols, r))) for r in rows.fetchall()]
        return {"total": total, "page": page, "page_size": page_size, "pk_column": pk_col, "columns": cols, "rows": data}
    finally:
        db.close()


class RowPayload(BaseModel):
    data: Dict[str, Any]


@router.put("/tables/{table}/rows/{row_id}")
def update_row(table: str, row_id: str, payload: RowPayload):
    pk_col = _pk_column(table)
    safe = {k: v for k, v in payload.data.items() if k != pk_col}
    if not safe:
        raise HTTPException(400, "No fields to update")
    db = SessionLocal()
    try:
        sets = ", ".join(f'"{k}" = :{k}' for k in safe)
        safe["_pk"] = row_id
        result = db.execute(text(f'UPDATE "{table}" SET {sets} WHERE "{pk_col}" = :_pk'), safe)
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Row not found")
        return {"message": "Row updated"}
    finally:
        db.close()


@router.delete("/tables/{table}/rows/{row_id}")
def delete_row(table: str, row_id: str):
    pk_col = _pk_column(table)
    db = SessionLocal()
    try:
        result = db.execute(text(f'DELETE FROM "{table}" WHERE "{pk_col}" = :id'), {"id": row_id})
        db.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Row not found")
        return {"message": "Row deleted"}
    finally:
        db.close()


@router.delete("/tables/{table}/rows")
def bulk_delete_rows(table: str, payload: dict = Body(...)):
    pk_col = _pk_column(table)
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(400, "No row ids provided")
    db = SessionLocal()
    try:
        stmt = text(f'DELETE FROM "{table}" WHERE "{pk_col}" IN :ids').bindparams(
            bindparam("ids", expanding=True)
        )
        result = db.execute(stmt, {"ids": ids})
        db.commit()
        return {"message": f"Deleted {result.rowcount} row(s)"}
    finally:
        db.close()


def _cast_value(raw: str, col_type: str):
    """Casts a raw CSV string to a reasonable Python value based on the
    target column's SQL type -- JSON columns get parsed, booleans get
    interpreted from common truthy/falsy text, everything else stays a
    string (Postgres/psycopg2 handles numeric-string-to-int/float
    coercion fine for plain parameterized values)."""
    t = col_type.upper()
    if "JSON" in t:
        try:
            return json.loads(raw)
        except Exception:
            return raw  # not valid JSON -- store the raw text rather than fail the whole row
    if "BOOL" in t:
        return raw.strip().lower() in ("true", "1", "yes", "t", "y")
    return raw


@router.post("/tables/{table}/upload-csv")
async def upload_csv(table: str, file: UploadFile = File(...)):
    """Bulk upsert rows from a CSV file: a row is UPDATEd if its primary
    key already exists in the table, otherwise INSERTed. The CSV must
    include a column matching the table's real primary key so rows can
    be matched -- unknown columns in the CSV (not present on the table)
    are silently ignored rather than failing the whole upload, and each
    row commits independently so one bad row doesn't block the rest."""
    if table not in get_accfino_table_names():
        raise HTTPException(404, f"Table '{table}' does not exist.")
    insp = inspect(engine)
    if not insp.has_table(table):
        raise HTTPException(404, f"Table '{table}' does not exist.")

    pk_col = _pk_column(table)
    col_types = {c["name"]: str(c["type"]) for c in insp.get_columns(table)}

    raw = await file.read()
    try:
        text_content = raw.decode("utf-8-sig")  # utf-8-sig strips Excel's BOM if present
    except UnicodeDecodeError:
        raise HTTPException(400, "Could not read file as UTF-8 text -- is this actually a CSV?")

    reader = csv.DictReader(io.StringIO(text_content))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV appears to be empty or has no header row.")

    valid_cols = [c for c in reader.fieldnames if c in col_types]
    unknown_cols = [c for c in reader.fieldnames if c not in col_types]
    if pk_col not in valid_cols:
        raise HTTPException(
            400,
            f"CSV must include a '{pk_col}' column (this table's primary key) "
            f"so rows can be matched to existing ones. Columns found: {', '.join(reader.fieldnames)}",
        )

    inserted, updated, skipped = 0, 0, 0
    errors = []

    db = SessionLocal()
    try:
        for i, row in enumerate(reader, start=2):  # row 1 is the header
            pk_val = (row.get(pk_col) or "").strip()
            if not pk_val:
                skipped += 1
                continue

            data = {}
            for col in valid_cols:
                if col == pk_col:
                    continue
                val = row.get(col)
                if val is None or val == "":
                    continue
                data[col] = _cast_value(val, col_types[col])

            try:
                existing = db.execute(text(f'SELECT 1 FROM "{table}" WHERE "{pk_col}" = :pk'), {"pk": pk_val}).first()
                if existing:
                    if data:
                        sets = ", ".join(f'"{k}" = :{k}' for k in data)
                        db.execute(text(f'UPDATE "{table}" SET {sets} WHERE "{pk_col}" = :_pk'), {**data, "_pk": pk_val})
                    updated += 1
                else:
                    all_data = {pk_col: pk_val, **data}
                    cols_sql = ", ".join(f'"{k}"' for k in all_data)
                    vals_sql = ", ".join(f":{k}" for k in all_data)
                    db.execute(text(f'INSERT INTO "{table}" ({cols_sql}) VALUES ({vals_sql})'), all_data)
                    inserted += 1
                db.commit()
            except Exception as e:
                db.rollback()
                errors.append(f"Row {i} ({pk_col}={pk_val!r}): {e}")
    finally:
        db.close()

    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "unknown_columns": unknown_cols,
        "errors": errors[:20],  # cap so a bad file doesn't return a huge payload
        "error_count": len(errors),
    }


@router.post("/tables/{table}/rows", status_code=201)
def insert_row(table: str, payload: RowPayload):
    if table not in get_accfino_table_names():
        raise HTTPException(404, f"Table '{table}' does not exist.")
    insp = inspect(engine)
    if not insp.has_table(table):
        raise HTTPException(404, f"Table '{table}' does not exist.")
    safe = {k: v for k, v in payload.data.items() if v is not None and v != ""}
    if not safe:
        raise HTTPException(400, "No data provided")
    db = SessionLocal()
    try:
        cols = ", ".join(f'"{k}"' for k in safe)
        vals = ", ".join(f":{k}" for k in safe)
        pk_col = _pk_column(table)
        result = db.execute(text(f'INSERT INTO "{table}" ({cols}) VALUES ({vals}) RETURNING "{pk_col}"'), safe)
        db.commit()
        return {"message": "Row inserted", "id": result.scalar()}
    finally:
        db.close()


class QueryPayload(BaseModel):
    sql: str


@router.post("/query")
def run_query(payload: QueryPayload):
    """Read-only SQL passthrough -- only SELECT statements are allowed."""
    sql = payload.sql.strip()
    if not sql.lower().startswith("select"):
        raise HTTPException(400, "Only SELECT queries are allowed here.")
    db = SessionLocal()
    try:
        result = db.execute(text(sql))
        cols = list(result.keys())
        rows = [_serialize_row(dict(zip(cols, r))) for r in result.fetchall()]
        return {"columns": cols, "rows": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()
