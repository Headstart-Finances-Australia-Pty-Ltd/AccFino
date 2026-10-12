"""
Admin File Manager: browse/read/edit files under ACCFINO_DATA_ROOT and the database tables.
"""
import os
import sys
from pathlib import Path
from fastapi import APIRouter
from accfino.shared import paths as _paths

router = APIRouter()

import logging
logger = logging.getLogger("accfino")


import base64, io, json, logging, os, sys, uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, Body
import csv        as _csv
import math       as _math
import pickle     as _pickle
import sqlite3    as _sqlite3
from urllib.parse import unquote as _unquote
import pandas     as _pd_fm

_DATA_ROOT = _paths.filemanager_root()

def _node_type(p: Path) -> str:
    if p.is_dir():                              return "folder"
    if p.suffix.lower() in (".db", ".sqlite"): return "database"
    return "file"

def _safe_val(v) -> str:
    """Convert any Python value to a clean, JSON-safe string."""
    try:
        if v is None:
            return ""
        if isinstance(v, float) and (_math.isnan(v) or _math.isinf(v)):
            return ""
        s = str(v)
        # Strip null bytes and non-printable control chars (keep newlines as space)
        s = "".join(c if c >= " " or c in "\t" else " " for c in s)
        return s[:500]
    except Exception:
        return ""

def _safe_rows(raw: list, cols: list) -> list:
    """Return list of {col: safe_str} dicts - every value is JSON-safe."""
    str_cols = [str(c) for c in cols]
    result   = []
    for row in raw:
        if isinstance(row, dict):
            result.append({c: _safe_val(row.get(orig)) for c, orig in zip(str_cols, cols)})
        else:
            result.append({c: _safe_val(getattr(row, str(orig), "")) for c, orig in zip(str_cols, cols)})
    return result

def _resolve_path(raw: str) -> Path:
    """
    Decode a URL-encoded relative path, normalise separators,
    resolve to an absolute path inside _DATA_ROOT.
    Raises HTTPException 403 if path escapes DATA_ROOT.
    Raises HTTPException 404 if path does not exist.
    """
    # 1. URL-decode (%20 - space, %2F - /, etc.)
    decoded = _unquote(raw or "")
    # 2. Normalise: forward slashes only, no leading slash
    clean   = decoded.replace("\\", "/").replace("\\\\", "/").strip("/")
    if not clean:
        raise HTTPException(400, "Empty path")
    # 3. Resolve to absolute
    target  = (_DATA_ROOT / clean).resolve()
    # 4. Security: must stay inside DATA_ROOT
    try:
        target.relative_to(_DATA_ROOT)
    except ValueError:
        raise HTTPException(403, f"Access denied: {clean}")
    return target

@router.get("/filemanager/tree")
def fm_tree():
    """Return full recursive tree of DATA_ROOT for the file manager, plus a
    synthetic 'Postgres Database' node exposing every real app table
    (chart_of_accounts, pricing_plans, rdr_rules, groq_key_pool, etc.) --
    same browsing/editing UI as any other file/table in this page, just
    backed by the actual application database instead of a stray .db file."""
    def _walk(base: Path, rel: str) -> list:
        items = []
        try:
            for child in sorted(base.iterdir()):
                rel_path = f"{rel}/{child.name}" if rel else child.name
                node = {
                    "name": child.name,
                    "path": rel_path,          # forward-slash relative path
                    "type": _node_type(child),
                }
                if child.is_dir():
                    node["children"] = _walk(child, rel_path)
                elif child.suffix.lower() in (".db", ".sqlite"):
                    try:
                        cx = _sqlite3.connect(str(child))
                        node["tables"] = [
                            r[0] for r in cx.execute(
                                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                            ).fetchall()
                        ]
                        cx.close()
                    except Exception:
                        node["tables"] = []
                items.append(node)
        except PermissionError:
            pass
        return items

    tree = []
    try:
        from sqlalchemy import inspect as _sa_inspect
        from accfino.shared.db.database import engine as _pg_engine
        from accfino.shared.db.known_tables import get_accfino_table_names
        accfino_tables = get_accfino_table_names()
        pg_tables = sorted(t for t in _sa_inspect(_pg_engine).get_table_names() if t in accfino_tables)
        tree.append({
            "name": "Postgres Database",
            "path": "__postgres_db__",
            "type": "database",
            "tables": pg_tables,
        })
    except Exception as _e:
        logger.warning(f"filemanager: could not list Postgres tables: {_e}")

    if _DATA_ROOT.exists():
        tree.extend(_walk(_DATA_ROOT, ""))
    else:
        return {"tree": tree, "data_root": str(_DATA_ROOT), "error": "DATA_ROOT does not exist"}

    return {"tree": tree, "data_root": str(_DATA_ROOT)}

@router.get("/filemanager/read/{file_path:path}")
def fm_read(file_path: str, table: str = ""):
    """
    Read a file, SQLite table, or Postgres table and return {columns, rows, source}.
    file_path is a URL-encoded, forward-slash relative path from DATA_ROOT,
    EXCEPT for the sentinel "__postgres_db__" which reads from the real
    application database instead of a file on disk.
    All returned values are plain JSON-safe strings.
    """
    if file_path == "__postgres_db__":
        if not table:
            raise HTTPException(400, "table is required to read from the Postgres database")
        from accfino.shared.db.known_tables import get_accfino_table_names
        if table not in get_accfino_table_names():
            raise HTTPException(404, f"Table {table!r} does not exist")
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        from accfino.shared.db.database import SessionLocal as _PgSession, engine as _pg_engine
        insp = _sa_inspect(_pg_engine)
        if not insp.has_table(table):
            raise HTTPException(404, f"Table {table!r} does not exist in Postgres")
        db = _PgSession()
        try:
            result = db.execute(_sa_text(f'SELECT * FROM "{table}" LIMIT 1000'))
            cols = list(result.keys())
            raw  = [dict(zip(cols, row)) for row in result.fetchall()]
            return {"columns": cols, "rows": _safe_rows(raw, cols),
                    "source": f"postgres - {len(raw)} rows"}
        except Exception as e:
            raise HTTPException(500, f"Postgres read error: {e}")
        finally:
            db.close()

    target = _resolve_path(file_path)

    if not target.exists():
        raise HTTPException(404, f"File not found: {file_path!r} - {target}")

    ext = target.suffix.lower()

    # -- SQLite table ----------------------------------------------------------
    if table and ext in (".db", ".sqlite"):
        try:
            cx   = _sqlite3.connect(str(target))
            cols = [r[1] for r in cx.execute(f"PRAGMA table_info('{table}')").fetchall()]
            if not cols:
                cx.close()
                raise HTTPException(404, f"Table {table!r} not found in {target.name}")
            raw  = [dict(zip(cols, row)) for row in
                    cx.execute(f'SELECT * FROM "{table}" LIMIT 1000').fetchall()]
            cx.close()
            return {"columns": cols, "rows": _safe_rows(raw, cols),
                    "source": f"sqlite - {len(raw)} rows"}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"SQLite error: {e}")

    # -- CSV - parse into columns/rows for tabular editing -------------------
    if ext == ".csv":
        try:
            import csv as _csv_r, io as _io
            raw_bytes = target.read_bytes()
            if raw_bytes.startswith(b"\xef\xbb\xbf"):
                raw_bytes = raw_bytes[3:]
            text = raw_bytes.decode("utf-8", errors="replace")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            reader = _csv_r.DictReader(_io.StringIO(text))
            items  = [dict(row) for row in reader]
            cols   = list(reader.fieldnames or (items[0].keys() if items else []))
            rows   = [{c: _safe_val(r.get(c, "")) for c in cols} for r in items[:2000]]
            return {
                "columns": cols,
                "rows":    rows,
                "source":  f"csv - {len(rows)} rows",
            }
        except Exception as e:
            raise HTTPException(500, f"CSV read error: {e}")

    # -- JSON - always tabular -------------------------------------------------
    if ext in (".json", ".jsonl"):
        try:
            import json as _j
            raw_bytes = target.read_bytes()
            if raw_bytes.startswith(b"\xef\xbb\xbf"):
                raw_bytes = raw_bytes[3:]
            text = raw_bytes.decode("utf-8", errors="replace")
            if ext == ".jsonl":
                items = [_j.loads(ln) for ln in text.splitlines() if ln.strip()]
            else:
                items = _j.loads(text)
            if isinstance(items, list) and items and isinstance(items[0], dict):
                # Collect all keys across all rows (some rows may have extra keys)
                all_keys = list(dict.fromkeys(k for row in items[:500] for k in row))
                cols = [str(c) for c in all_keys]
                return {"columns": cols, "rows": _safe_rows(items[:500], all_keys),
                        "source": f"json - {len(items)} rows"}
            elif isinstance(items, dict):
                # If values are dicts (e.g. pricing.json), expand into tabular rows
                first_val = next(iter(items.values()), None)
                if isinstance(first_val, dict):
                    all_keys = list(dict.fromkeys(
                        k for v in items.values() if isinstance(v, dict) for k in v
                    ))
                    cols = ["_key"] + all_keys
                    rows = []
                    for k, v in list(items.items())[:500]:
                        if isinstance(v, dict):
                            row = {"_key": _safe_val(k)}
                            row.update({c: _safe_val(v.get(c, "")) for c in all_keys})
                        else:
                            row = {"_key": _safe_val(k), **{c: "" for c in all_keys}}
                        rows.append(row)
                    return {"columns": cols, "rows": rows,
                            "source": f"json - {len(rows)} entries"}
                else:
                    rows = [{"key": _safe_val(k), "value": _safe_val(v)}
                            for k, v in list(items.items())[:500]]
                    return {"columns": ["key", "value"], "rows": rows,
                            "source": f"json - {len(rows)} entries"}
            elif isinstance(items, list):
                rows = [{"#": str(i+1), "value": _safe_val(v)}
                        for i, v in enumerate(items[:500])]
                return {"columns": ["#", "value"], "rows": rows,
                        "source": f"json - {len(items)} items"}
            else:
                return {"columns": ["value"], "rows": [{"value": _safe_val(items)}],
                        "source": "json"}
        except Exception as e:
            raise HTTPException(500, f"JSON read error: {e}")

    # -- Pickle ----------------------------------------------------------------
    if ext in (".pkl", ".pickle"):
        try:
            obj = _pd_fm.read_pickle(str(target))
            if isinstance(obj, _pd_fm.DataFrame):
                df   = obj.head(500)
                cols = [str(c) for c in df.columns]
                rows = []
                for _, row in df.iterrows():
                    rows.append({c: _safe_val(v) for c, v in zip(cols, row)})
                return {"columns": cols, "rows": rows,
                        "source": f"pickle - DataFrame {len(df)}r - {len(cols)}c"}
            elif isinstance(obj, dict):
                rows = [{"key": _safe_val(k), "value": _safe_val(v)}
                        for k, v in list(obj.items())[:500]]
                return {"columns": ["key", "value"], "rows": rows, "source": "pickle - dict"}
            elif isinstance(obj, list):
                if obj and isinstance(obj[0], dict):
                    cols = [str(k) for k in obj[0].keys()]
                    return {"columns": cols, "rows": _safe_rows(obj[:500], cols), "source": "pickle - list"}
                rows = [{"#": str(i), "value": _safe_val(v)} for i, v in enumerate(obj[:500])]
                return {"columns": ["#", "value"], "rows": rows, "source": "pickle - list"}
            else:
                return {"columns": ["type", "repr"],
                        "rows": [{"type": type(obj).__name__, "repr": _safe_val(obj)[:2000]}],
                        "source": "pickle"}
        except Exception as e:
            return {"columns": ["error"], "rows": [{"error": f"Cannot read pickle: {e}"}],
                    "source": "pickle - error"}

    # -- PDF -------------------------------------------------------------------
    # Run PDF extraction in a separate subprocess so any crash cannot
    # kill the uvicorn worker process.
    if ext == ".pdf":
        import subprocess, sys, json as _json_pdf
        script = f"""
import sys, json, traceback
try:
    import pdfplumber
    rows = []
    n_pages = 0
    with pdfplumber.open({str(target)!r}) as pdf:
        n_pages = len(pdf.pages)
        for pnum, page in enumerate(pdf.pages[:50], start=1):
            try:
                txt = page.extract_text() or ""
            except Exception:
                txt = ""
            for line in txt.splitlines():
                line = line.strip()
                if line:
                    rows.append({{"page": str(pnum), "text": line[:400]}})
    if not rows:
        rows = [{{"page": "-", "text": "(No extractable text - may be scanned PDF)"}}]
    print(json.dumps({{"ok": True, "rows": rows[:500], "n_pages": n_pages}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)[:300]}}))
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=30
            )
            out = result.stdout.strip()
            if out:
                data = _json_pdf.loads(out)
                if data.get("ok"):
                    return {
                        "columns": ["page", "text"],
                        "rows":    data["rows"],
                        "source":  f"pdf - {data['n_pages']} page(s) - {target.stat().st_size // 1024} KB",
                        "display": "raw",
                    }
                else:
                    return {
                        "columns": ["error"],
                        "rows":    [{"error": data.get("error", "Unknown PDF error")}],
                        "source":  "pdf - error",
                    }
        except subprocess.TimeoutExpired:
            return {"columns": ["error"], "rows": [{"error": "PDF processing timed out (30s)"}], "source": "pdf"}
        except Exception as e:
            pass

        # Fallback: just show file info
        size_kb = target.stat().st_size // 1024
        return {
            "columns": ["property", "value"],
            "rows": [
                {"property": "filename", "value": target.name},
                {"property": "size",     "value": f"{size_kb} KB"},
                {"property": "note",     "value": "PDF text extraction unavailable"},
            ],
            "source": "pdf - info only",
        }

    # -- Plain text fallback ---------------------------------------------------
    try:
        raw_bytes = target.read_bytes()
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            raw_bytes = raw_bytes[3:]
        text  = raw_bytes.decode("utf-8", errors="replace")
        text  = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.splitlines()[:1000]
        rows  = [{"#": str(i + 1), "line": _safe_val(ln)} for i, ln in enumerate(lines)]
        return {"columns": ["#", "line"], "rows": rows,
                "source": f"text - {len(rows)} lines"}
    except Exception as e:
        raise HTTPException(500, f"Cannot read file: {e}")

@router.post("/filemanager/save")
def fm_save(body: dict = Body(...)):
    """Save edited rows back to a CSV file, SQLite table, or Postgres table."""
    path   = body.get("path",   "")
    table  = body.get("table",  "")
    rows   = body.get("rows",   [])
    source = body.get("source", "")

    if path == "__postgres_db__":
        if not table:
            raise HTTPException(400, "table is required to save to the Postgres database")
        from accfino.shared.db.known_tables import get_accfino_table_names
        if table not in get_accfino_table_names():
            raise HTTPException(404, f"Table {table!r} does not exist")
        # Deliberately NOT a delete-all-then-reinsert like the SQLite path
        # below -- a Postgres table can hold far more rows than the 1000-row
        # page currently loaded in the browser, so wholesale replace here
        # would silently destroy every row outside the current view.
        # Instead: upsert each row by its real primary key; use the
        # per-row Delete button (fm_delete_row) to remove rows.
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        from accfino.shared.db.database import SessionLocal as _PgSession, engine as _pg_engine
        insp = _sa_inspect(_pg_engine)
        if not insp.has_table(table):
            raise HTTPException(404, f"Table {table!r} does not exist in Postgres")
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        if not pk:
            raise HTTPException(400, f"Table {table!r} has no primary key -- cannot save generically")
        pk_col = pk[0]

        db = _PgSession()
        try:
            saved = 0
            for row in rows:
                if pk_col not in row or row[pk_col] in (None, ""):
                    continue  # skip incomplete rows rather than guessing a PK
                cols = [c for c in row.keys() if c != pk_col]
                if not cols:
                    continue
                set_clause = ", ".join(f'"{c}" = :{c}' for c in cols)
                params = {c: row[c] for c in cols}
                params["_pk"] = row[pk_col]
                result = db.execute(_sa_text(f'UPDATE "{table}" SET {set_clause} WHERE "{pk_col}" = :_pk'), params)
                if result.rowcount == 0:
                    # Row doesn't exist yet -- insert it (covers rows added via "Add Row")
                    all_cols = [pk_col] + cols
                    col_list = ", ".join(f'"{c}"' for c in all_cols)
                    val_list = ", ".join(f':{c}' for c in all_cols)
                    insert_params = {c: row.get(c) for c in all_cols}
                    db.execute(_sa_text(f'INSERT INTO "{table}" ({col_list}) VALUES ({val_list})'), insert_params)
                saved += 1
            db.commit()
            return {"ok": True, "saved": saved}
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Postgres save error: {e}")
        finally:
            db.close()

    target = _resolve_path(path)

    if "sqlite" in source and table:
        try:
            cx   = _sqlite3.connect(str(target))
            cols = [r[1] for r in cx.execute(f"PRAGMA table_info('{table}')").fetchall()]
            cx.execute(f'DELETE FROM "{table}"')
            for row in rows:
                vals = [row.get(c) for c in cols]
                cx.execute(
                    f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({",".join(["?"]*len(cols))})',
                    vals
                )
            cx.commit(); cx.close()
            return {"ok": True, "saved": len(rows)}
        except Exception as e:
            raise HTTPException(500, f"SQLite save error: {e}")

    if "csv" in source or target.suffix.lower() == ".csv":
        if not rows:
            return {"ok": True, "saved": 0}
        cols = list(rows[0].keys())
        with open(target, "w", newline="", encoding="utf-8") as f:
            w = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
        return {"ok": True, "saved": len(rows)}

    if target.suffix.lower() in (".json", ".jsonl"):
        import json as _js
        if not rows:
            return {"ok": True, "saved": 0}
        if target.suffix.lower() == ".jsonl":
            with open(target, "w", encoding="utf-8") as f:
                for row in rows:
                    f.write(_js.dumps(row) + "\n")
        else:
            with open(target, "w", encoding="utf-8") as f:
                _js.dump(rows, f, indent=2, ensure_ascii=False)
        return {"ok": True, "saved": len(rows)}

    raise HTTPException(400, f"Save not supported for: {source or target.suffix}")

@router.delete("/filemanager/delete-row")
def fm_delete_row(body: dict = Body(...)):
    """Delete a single row from a SQLite table, or a Postgres table, by primary key."""
    path   = body.get("path",   "")
    table  = body.get("table",  "")
    row_id = body.get("row_id")
    pk_col = body.get("pk_col", "id")

    if not table:
        raise HTTPException(400, "table is required for row delete")

    if path == "__postgres_db__":
        from accfino.shared.db.known_tables import get_accfino_table_names
        if table not in get_accfino_table_names():
            raise HTTPException(404, f"Table {table!r} does not exist")
        from sqlalchemy import text as _sa_text, inspect as _sa_inspect
        from accfino.shared.db.database import SessionLocal as _PgSession, engine as _pg_engine
        insp = _sa_inspect(_pg_engine)
        if not insp.has_table(table):
            raise HTTPException(404, f"Table {table!r} does not exist in Postgres")
        # Trust the real PK column from the DB over whatever the frontend
        # guessed (it defaults to "id" or the first column when it can't tell).
        pk = insp.get_pk_constraint(table).get("constrained_columns") or []
        real_pk_col = pk[0] if pk else pk_col
        db = _PgSession()
        try:
            result = db.execute(_sa_text(f'DELETE FROM "{table}" WHERE "{real_pk_col}" = :id'), {"id": row_id})
            db.commit()
            if result.rowcount == 0:
                raise HTTPException(404, "Row not found")
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            db.rollback()
            raise HTTPException(500, f"Postgres delete error: {e}")
        finally:
            db.close()

    target = _resolve_path(path)
    try:
        cx = _sqlite3.connect(str(target))
        cx.execute(f'DELETE FROM "{table}" WHERE "{pk_col}" = ?', (row_id,))
        cx.commit(); cx.close()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Delete error: {e}")

