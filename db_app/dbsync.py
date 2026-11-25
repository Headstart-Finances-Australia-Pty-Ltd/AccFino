"""Moving data between the main database (DATABASE_URL = number 0) and the
standby databases (DATABASE_STANDBY_URLS = numbers 1, 2, ...).

  1. WARM COPY (main -> every standby): once every DB_STANDBY_SYNC_HOURS
     (default 24; 0 = off) while the main database is the active one, so a standby
     already holds users, licences, companies, invoices, transactions ... when it
     is needed. It is a MERGE, cheap when little changed.
  2. FAILOVER (database.py): the app moves from A to B. We try once to copy A -> B.
     A database that is out of quota usually cannot be read, in which case B simply
     carries on with the data it already has.
  3. FAIL-BACK (loop below): while a standby is in use, the main database is tried
     every DB_FAILBACK_MINUTES (default 30; 0 = off). When it accepts connections
     again, the standby is merged into it, the app switches back, and a second quick
     pass catches rows written meanwhile.

A copy is a MERGE: rows are inserted or updated by primary key, nothing is ever
deleted. A row that would break another unique/foreign-key rule is skipped and
counted. Large binary columns are only transferred for rows the target lacks.

DB_SYNC_SKIP_TABLES=name1,name2 leaves tables out.

Session files (main_app/data/...) live on disk, not in Postgres, and are not copied.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from db_app import database as D

log = logging.getLogger("accfino.dbsync")

last = {"at": None, "results": []}
_lock = threading.Lock()
_started = False


def q(ident) -> str:
    return '"' + str(ident).replace('"', '""') + '"'


def _skip() -> set:
    return {s.strip() for s in os.environ.get("DB_SYNC_SKIP_TABLES", "").split(",") if s.strip()}


def is_busy() -> bool:
    return _lock.locked()


# ── schema ───────────────────────────────────────────────────────────────────
def ensure_schema(i: int):
    """Create any missing tables/columns in database `i` - tables only, no seed data, so the
    copied rows (roles, admin, licences ...) keep their original ids."""
    import importlib

    import db_app.models  # noqa: F401  registers the core models
    from db_app.models.base import Base

    for extra in ("db_app.models.accounting", "db_app.models.account_balance", "db_app.models.transaction"):
        try:
            importlib.import_module(extra)
        except Exception:
            pass
    eng = D.make_engine(i)
    try:
        Base.metadata.create_all(bind=eng, checkfirst=True)
        for mod in ("add_currency_loan_columns", "create_account_balances", "create_accounting_tables", "create_payroll_tables"):
            try:
                importlib.import_module(f"db_app.migrations.{mod}").run(eng)
            except Exception as e:  # same tolerance as the app's own start-up
                log.warning("schema step %s on database %d skipped: %s", mod, i, str(e)[:120])
    finally:
        eng.dispose()


def _list_tables(cur):
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
    )
    return [r[0] for r in cur.fetchall()]


def _sort_by_dependency(cur, tables):
    """Parents before the tables that reference them."""
    cur.execute(
        "SELECT c.conrelid::regclass::text, c.confrelid::regclass::text FROM pg_constraint c WHERE c.contype='f'"
    )
    ts = set(tables)
    deps = {t: set() for t in tables}
    for child, parent in cur.fetchall():
        c, p = child.replace('"', ""), parent.replace('"', "")
        if c in ts and p in ts and c != p:
            deps[c].add(p)
    out, done = [], set()

    def visit(t, stack=()):
        if t in done or t in stack:
            return
        for d in deps[t]:
            visit(d, stack + (t,))
        done.add(t)
        out.append(t)

    for t in tables:
        visit(t)
    return out


def _describe(cur, table):
    cur.execute(
        """SELECT a.attname, a.attgenerated <> '', a.attidentity, format_type(a.atttypid, a.atttypmod)
             FROM pg_attribute a
            WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
        (q(table),),
    )
    cols = [{"name": r[0], "generated": r[1], "identity": r[2], "type": r[3]} for r in cur.fetchall()]
    cur.execute(
        """SELECT a.attname, format_type(a.atttypid, a.atttypmod)
             FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY (i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary""",
        (q(table),),
    )
    pk = [{"name": r[0], "type": r[1]} for r in cur.fetchall()]
    return cols, pk


def _stream(src, sql, params, batch):
    """Rows of `sql` as JSON dicts in batches, via a server-side cursor (memory stays small)."""
    cur = src.cursor(name="kc")
    cur.itersize = batch
    try:
        cur.execute(sql, params)
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                break
            yield [r[0] for r in rows]
    finally:
        cur.close()
        src.rollback()


def _upsert_batch(dst, table, cols, pk_cols, update_cols, has_identity, rows, out, update_only=False):
    col_list = ", ".join(q(c) for c in cols)
    if update_only:
        # rows that already exist: refresh their ordinary columns (an INSERT without the NOT NULL binary column would be rejected)
        if not update_cols:
            return
        sql = (
            f"UPDATE {q(table)} AS t SET " + ", ".join(f"{q(c)} = x.{q(c)}" for c in update_cols) +
            f" FROM json_populate_recordset(NULL::{q(table)}, %s::json) AS x WHERE " +
            " AND ".join(f"t.{q(c)} = x.{q(c)}" for c in pk_cols)
        )
    else:
        pk_sql = ", ".join(q(c) for c in pk_cols)
        conflict = (
            f"ON CONFLICT ({pk_sql}) DO UPDATE SET " + ", ".join(f"{q(c)} = EXCLUDED.{q(c)}" for c in update_cols)
            if update_cols else f"ON CONFLICT ({pk_sql}) DO NOTHING"
        )
        sql = (
            f"INSERT INTO {q(table)} ({col_list}) {'OVERRIDING SYSTEM VALUE ' if has_identity else ''}"
            f"SELECT {col_list} FROM json_populate_recordset(NULL::{q(table)}, %s::json) {conflict}"
        )
    cur = dst.cursor()

    def run(batch_rows) -> bool:
        cur.execute("SAVEPOINT b")
        try:
            cur.execute(sql, (json.dumps(batch_rows),))
            cur.execute("RELEASE SAVEPOINT b")
            return True
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT b")
            cur.execute("RELEASE SAVEPOINT b")
            if getattr(e, "pgcode", None) not in ("23505", "23503", "23502", "23514"):
                raise
            return False

    if run(rows):
        out["rows"] += len(rows)
        return
    for r in rows:  # something in the batch breaks another rule: skip only the clashing rows
        if run([r]):
            out["rows"] += 1
        else:
            out["skipped_rows"] += 1


def _copy_table(src, dst, table, out):
    dcur, scur = dst.cursor(), src.cursor()
    dst_cols, pk = _describe(dcur, table)
    src_cols, _ = _describe(scur, table)
    src.rollback()
    if not pk:
        out["tables_without_pk"].append(table)
        return
    src_names = {c["name"] for c in src_cols}
    usable = [c for c in dst_cols if not c["generated"] and c["name"] in src_names]
    pk_cols = [c["name"] for c in pk]
    has_identity = any(c["identity"] == "a" for c in usable)
    blob_cols = [c["name"] for c in usable if c["type"] == "bytea"]
    light_cols = [c["name"] for c in usable if c["type"] != "bytea"]

    try:
        # Pass A - tables with big binary columns: copy whole rows the target is missing.
        if blob_cols and len(pk) == 1:
            dcur.execute(f"SELECT {q(pk_cols[0])} FROM {q(table)}")
            keys = [r[0] for r in dcur.fetchall()]
            sel = f"SELECT row_to_json(t) FROM {q(table)} t WHERE NOT ({q(pk_cols[0])} = ANY (%s::{pk[0]['type']}[]))"
            for rows in _stream(src, sel, (keys,), 2):
                _upsert_batch(dst, table, [c["name"] for c in usable], pk_cols, [], has_identity, rows, out)
                out["blob_rows"] += len(rows)
        # Pass B - every row (without the binary columns for such tables).
        pass_cols = light_cols if blob_cols else [c["name"] for c in usable]
        update_cols = [c for c in pass_cols if c not in pk_cols]
        sel = f"SELECT row_to_json(x) FROM (SELECT {', '.join(q(c) for c in pass_cols)} FROM {q(table)}) x"
        for rows in _stream(src, sel, None, 500):
            _upsert_batch(dst, table, pass_cols, pk_cols, update_cols, has_identity, rows, out, bool(blob_cols))
        dst.commit()
    except Exception:
        dst.rollback()
        raise

    # Keep SERIAL counters ahead of the copied ids so the next INSERT does not collide.
    for c in usable:
        dcur.execute("SELECT pg_get_serial_sequence(%s, %s)", (q(table), c["name"]))
        seq = dcur.fetchone()[0]
        if not seq:
            continue
        dcur.execute(f"SELECT MAX({q(c['name'])}) FROM {q(table)}")
        mx = dcur.fetchone()[0]
        if mx is None:
            continue
        dcur.execute(f"SELECT setval(%s, GREATEST(%s::bigint, (SELECT last_value FROM {seq})))", (seq, mx))
    dst.commit()


def merge(src_i: int, dst_i: int) -> dict:
    """Copy every row of database `src_i` into database `dst_i` (insert/update by primary key; nothing is deleted)."""
    if src_i == dst_i:
        raise ValueError("source and target are the same database")
    t0 = time.time()
    out = {
        "from": src_i, "to": dst_i, "ok": False, "rows": 0, "blob_rows": 0, "skipped_rows": 0,
        "tables": 0, "tables_without_pk": [], "at": datetime.now(timezone.utc).isoformat(),
    }
    src = dst = None
    try:
        ensure_schema(dst_i)  # the target always gets its tables, even if the source can't be read
        src = D.connect_index(src_i)
        src.set_session(isolation_level="REPEATABLE READ", readonly=True)
        dst = D.connect_index(dst_i)
        skip = _skip()
        scur, dcur = src.cursor(), dst.cursor()
        s_tables, d_tables = _list_tables(scur), set(_list_tables(dcur))
        src.rollback()
        wanted = [t for t in s_tables if t in d_tables and t not in skip]
        for table in _sort_by_dependency(dcur, wanted):
            _copy_table(src, dst, table, out)
            out["tables"] += 1
        out["ok"] = True
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e).strip()[:300]}"
        log.warning("Database copy %d -> %d failed: %s", src_i, dst_i, out["error"])
    finally:
        for c in (src, dst):
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
    out["seconds"] = round(time.time() - t0, 1)
    last["at"] = datetime.now(timezone.utc).isoformat()
    last["results"] = (last["results"] + [out])[-10:]
    log.warning("Database copy finished: %s", json.dumps(out))
    return out


def merge_now(src_i: int, dst_i: int):
    """Manual / admin-triggered copy. Returns None if one is already running."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        return merge(src_i, dst_i)
    finally:
        _lock.release()


def is_reachable(i: int) -> bool:
    try:
        c = D.connect_index(i)
        try:
            c.cursor().execute("SELECT 1")
        finally:
            c.close()
        return True
    except Exception:
        return False


def _on_failover(old: int, new: int):
    """Failover happened (old -> new): copy old into new if the old one can still be read."""
    if not _lock.acquire(blocking=False):
        return
    try:
        r = merge(old, new)
        if not r["ok"]:
            log.warning(
                "Could not copy database %d into %d (the old one is probably out of quota). "
                "Database %d carries on with the data it already has.", old, new, new,
            )
    finally:
        _lock.release()


def failback_once():
    """If a standby is in use and the main database works again: merge standby into it, switch back, merge once more."""
    cur = D.failover.active
    if cur == 0 or _lock.locked() or not is_reachable(0):
        return None
    if not _lock.acquire(blocking=False):
        return None
    try:
        log.warning("Main database is reachable again: copying database %d into it", cur)
        a = merge(cur, 0)
        if not a["ok"]:
            return a
        D.failover.set_active(0, "fail-back")
        b = merge(cur, 0)  # rows written while the first copy ran
        log.error("DATABASE FAIL-BACK: back on the main database (0).")
        return {"first": a, "second": b}
    finally:
        _lock.release()


def warm_standbys():
    """Main -> every standby, only while the main database is the active one."""
    if not D.failover.enabled or D.failover.active != 0 or not _lock.acquire(blocking=False):
        return None
    try:
        return [merge(0, i) for i in range(1, D.failover.count)]
    finally:
        _lock.release()


def _loop(period_s: float, fn, name: str, first_delay_s: float = None):
    def run():
        time.sleep(first_delay_s if first_delay_s is not None else period_s)
        while True:
            try:
                fn()
            except Exception:
                log.exception("%s failed", name)
            time.sleep(period_s)

    threading.Thread(target=run, daemon=True, name=name).start()


def start():
    """Start the failover hook and the (slow) background loops. Call once, from the main API process only."""
    global _started
    if _started:
        return
    _started = True
    D.failover.hooks.append(_on_failover)

    # Fail-back checks cost nothing while the main database is active (they only act on a standby).
    failback_min = float(os.environ.get("DB_FAILBACK_MINUTES", "30"))
    if failback_min > 0:
        _loop(failback_min * 60, lambda: failback_once() if D.failover.active != 0 else None, "db-failback")

    # Keeping a standby warm wakes both databases for a few minutes, so it is deliberately infrequent.
    warm_h = float(os.environ.get("DB_STANDBY_SYNC_HOURS", "24"))
    if warm_h > 0:
        _loop(warm_h * 3600, warm_standbys, "db-warm-sync", first_delay_s=15 * 60)

    if D.failover.enabled:
        log.warning(
            "Database failover on: %d databases, active #%d; standby sync every %s h, fail-back check every %s min",
            D.failover.count, D.failover.active, warm_h or "never", failback_min or "never",
        )
