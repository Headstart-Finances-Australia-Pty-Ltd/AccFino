"""
A1 - convert legacy floating-point money columns to exact NUMERIC, with a before/after reconciliation.

For each column in PLAN that is still 'double precision' the migration, inside one transaction per table:
  1. measures  SUM(col) and COUNT(col)                         (the "before" totals, as floats)
  2. computes  EXPECTED = SUM(ROUND(col::numeric, scale))       (what the exact column must hold)
  3. ALTER COLUMN ... TYPE NUMERIC(p,s) USING ROUND(col::numeric, s)
  4. re-measures SUM(col) and requires it to equal EXPECTED exactly, and to be within rows * half-a-unit of "before"
If any check fails the whole table's change is rolled back. The outcome is stored (system_settings 'migration.money_columns')
so an administrator can read the before/after totals. Safe to run on every start: converted columns are skipped.
"""
import json
import logging
from decimal import Decimal

from sqlalchemy import text

from accfino_core.books.money_plan import PG, PLAN

log = logging.getLogger("accfino.money_migration")
SETTING_KEY = "migration.money_columns"


def pending(conn):
    """{table: {column: type_name}} still stored as double precision (or real)."""
    rows = conn.execute(text("""select table_name, column_name from information_schema.columns
                                where table_schema = current_schema() and data_type in ('double precision', 'real')""")).fetchall()
    found = {}
    for t, c in rows:
        if t in PLAN and c in PLAN[t]:
            found.setdefault(t, {})[c] = PLAN[t][c]
    return found


def _measure(conn, table, col, scale=None):
    if scale is None:
        r = conn.execute(text(f'select coalesce(sum("{col}"), 0), count("{col}") from "{table}"')).one()
    else:
        r = conn.execute(text(f'select coalesce(sum(round("{col}"::numeric, {scale})), 0), count("{col}") from "{table}"')).one()
    return Decimal(str(r[0])), int(r[1])


def run(engine) -> list:
    """Convert everything still pending. Returns a list of per-column result dicts (empty if nothing to do)."""
    if engine.dialect.name != "postgresql":
        return []
    results = []
    with engine.connect() as probe:
        todo = pending(probe)
    for table, cols in todo.items():
        try:
            with engine.begin() as conn:
                table_results = []
                for col, typ in cols.items():
                    pg_type, scale = PG[typ]
                    before, n = _measure(conn, table, col)
                    expected, _ = _measure(conn, table, col, scale)
                    conn.execute(text(f'ALTER TABLE "{table}" ALTER COLUMN "{col}" TYPE {pg_type} USING round("{col}"::numeric, {scale})'))
                    after, _ = _measure(conn, table, col)
                    tolerance = Decimal(n) * Decimal("0.5") / (Decimal(10) ** scale) + Decimal("0.000001")
                    ok = after == expected and abs(after - before) <= tolerance
                    if not ok:
                        raise RuntimeError(f"{table}.{col}: before={before} expected={expected} after={after} (tolerance {tolerance})")
                    table_results.append(dict(table=table, column=col, type=pg_type, rows=n, before=str(before), after=str(after),
                                              difference=str(after - before)))
                results.extend(table_results)
                log.info("money migration: %s converted (%s columns)", table, len(table_results))
        except Exception as e:                       # one table failing must not stop the others or the app
            log.error("money migration FAILED for %s (rolled back): %s", table, e)
            results.append(dict(table=table, column="*", type="-", rows=0, before="-", after="-", error=str(e)))
    if results:
        _store(engine, results)
    return results


def _store(engine, results):
    try:
        with engine.begin() as conn:
            payload = json.dumps(dict(ran_at=__import__("datetime").datetime.utcnow().isoformat(timespec="seconds") + "Z", columns=results))
            conn.execute(text("""insert into system_settings(key, value) values (:k, :v)
                                 on conflict (key) do update set value = excluded.value"""), dict(k=SETTING_KEY, v=payload))
    except Exception as e:
        log.warning("could not store money-migration report: %s", e)


def report(db):
    """Last stored migration report + what is still pending (for the admin endpoint)."""
    row = db.execute(text("select value from system_settings where key = :k"), dict(k=SETTING_KEY)).first()
    last = json.loads(row[0]) if row and row[0] else None
    still = pending(db.connection())
    return dict(last_run=last, still_floating=[f"{t}.{c}" for t, cs in still.items() for c in cs],
                converted=not still)
