"""Shared CSV bulk-load engine (pure: no accfino.core / accfino.modules imports - modules pass their rules in).

One mechanism for every table that can be loaded from a CSV:
  * a Spec names the table, its columns, the permission and a `handler(db, ctx, access, row)` that creates ONE record by calling the module's own service
    (so every business rule, permission, duplicate check and audit entry of the normal screen applies; nothing is inserted behind the services' back);
  * "Check file" (dry run) executes the real handler for every row inside a database SAVEPOINT and then rolls everything back, so the preview shows the true row
    errors, including rules that depend on earlier rows of the same file;
  * "Import" is all-or-nothing by default (strict): if any row is rejected nothing is saved. strict=False saves the valid rows and reports the rest;
  * the file is data only: size and row limits, UTF-8 (BOM tolerated), unknown columns ignored and reported, no formulas are evaluated.
Anything a handler needs to know about "this is only a preview" is in db.info["bulk_dry_run"] (e.g. to suppress outgoing e-mail).
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

log = logging.getLogger("accfino.bulkload")
MAX_BYTES = 2_000_000
MAX_ROWS = 5000


@dataclass(frozen=True)
class Column:
    name: str
    required: bool = False
    help: str = ""
    example: str = ""


@dataclass
class Spec:
    key: str
    label: str
    columns: List[Column]
    handler: Callable                        # (db, ctx, access, row: dict[str, str]) -> any; raise an HTTPException/ValueError to reject the row
    capability: str = ""                     # permission the caller needs (module-specific meaning; passed to access.require)
    notes: str = ""
    order: int = 100                         # load order within the module (lower first)
    area: str = ""                           # screen / tab the table belongs to

    def catalogue(self) -> dict:
        return dict(key=self.key, label=self.label, notes=self.notes, order=self.order, area=self.area, capability=self.capability,
                    columns=[dict(name=c.name, required=c.required, help=c.help, example=c.example) for c in self.columns])


class RowError(ValueError):
    """Raise from a handler to reject the row with a plain message."""


# ----------------------------------------------------------------------------------------------------------------- parsing helpers for handlers
TRUE = {"1", "true", "yes", "y", "t"}
FALSE = {"0", "false", "no", "n", "f", ""}


def as_bool(v, name="value", default=False) -> bool:
    s = str(v or "").strip().lower()
    if s == "" and default is not None:
        return default
    if s in TRUE:
        return True
    if s in FALSE:
        return False
    raise RowError(f"{name} must be yes or no")


def as_int(v, name="value", required=False) -> Optional[int]:
    s = str(v or "").strip()
    if not s:
        if required:
            raise RowError(f"{name} is required")
        return None
    try:
        return int(s)
    except ValueError:
        raise RowError(f"{name} must be a whole number")


def as_date(v, name="date", required=False) -> Optional[date]:
    s = str(v or "").strip()
    if not s:
        if required:
            raise RowError(f"{name} is required")
        return None
    for f in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise RowError(f"{name} must be a date like 2026-09-30 or 30/09/2026")


def as_json(v, name="value", default=None):
    s = str(v or "").strip()
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        raise RowError(f"{name} must be valid JSON")


def as_list(v, sep=";") -> List[str]:
    return [x.strip() for x in str(v or "").split(sep) if x.strip()]


def need(row: dict, *names):
    for n in names:
        if not str(row.get(n, "") or "").strip():
            raise RowError(f"{n} is required")


# ----------------------------------------------------------------------------------------------------------------------------------- the engine
def template_csv(spec: Spec) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([c.name for c in spec.columns])
    w.writerow([c.example for c in spec.columns])
    return out.getvalue()


def _message(e: Exception) -> str:
    d = getattr(e, "detail", None) or getattr(e, "message", None)
    if isinstance(d, (list, dict)):
        d = json.dumps(d)[:300]
    return str(d or e)[:400] or e.__class__.__name__


def parse(spec: Spec, raw) -> dict:
    """-> {rows: [(row_number, {col: value})], ignored_columns: [...]} or raises RowError for file-level problems. Row numbers match a spreadsheet (header = row 1)."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_BYTES:
            raise RowError("The file is too large (limit 2 MB)")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
    else:
        text = raw or ""
    if "\x00" in text:
        raise RowError("This does not look like a CSV text file")
    rd = csv.reader(io.StringIO(text))
    try:
        head = next(rd)
    except StopIteration:
        raise RowError("The file is empty")
    cols = [re.sub(r"\s+", "_", (h or "").strip().lower()) for h in head]
    known = {c.name for c in spec.columns}
    missing = [c.name for c in spec.columns if c.required and c.name not in cols]
    if missing:
        raise RowError(f"Missing column(s): {', '.join(missing)}. Download the template to see the expected columns.")
    rows = []
    for n, rec in enumerate(rd, start=2):
        if not any((x or "").strip() for x in rec):
            continue
        rows.append((n, {cols[i]: (rec[i] or "").strip() for i in range(min(len(cols), len(rec))) if cols[i]}))
        if len(rows) > MAX_ROWS:
            raise RowError(f"Too many rows (limit {MAX_ROWS} per file)")
    return dict(rows=rows, ignored_columns=[c for c in cols if c and c not in known])


def run(db, ctx, access, spec: Spec, raw, *, apply: bool = False, strict: bool = True, audit: Optional[Callable] = None) -> dict:
    """Execute the import. The caller commits when result['applied'] > 0 (and only then); on a dry run everything has been rolled back already."""
    if spec.capability:
        access.require(spec.capability)
    try:
        p = parse(spec, raw)
    except RowError as e:
        return dict(key=spec.key, dry_run=not apply, applied=0, valid_rows=0, rejected=[], file_error=str(e), ignored_columns=[])
    rows = p["rows"]
    rejected, ok = [], 0
    previous = db.info.get("bulk_dry_run")
    db.info["bulk_dry_run"] = not apply
    outer = db.begin_nested()
    try:
        for n, row in rows:
            sp = db.begin_nested()
            try:
                spec.handler(db, ctx, access, row)
                db.flush()
                sp.commit()
                ok += 1
            except Exception as e:                                       # noqa: BLE001 - every failure is a row error, never a crash of the import
                sp.rollback()
                status = getattr(e, "status_code", None)
                if status == 403:
                    outer.rollback()
                    raise                                                 # a permission problem is not a data problem: refuse the whole file
                if isinstance(e, ValueError) or status:
                    msg = _message(e)
                else:
                    log.warning("bulk load %s row %s failed: %s", spec.key, n, e.__class__.__name__)
                    msg = "This row could not be processed (it conflicts with existing data or breaks a rule)"
                rejected.append(dict(row=n, error=msg))
    finally:
        db.info["bulk_dry_run"] = previous
    keep = apply and not (strict and rejected) and ok > 0
    if keep:
        outer.commit()
        if audit:
            audit(db, ctx, access, spec.key, ok, len(rejected))
    else:
        outer.rollback()
    res = dict(key=spec.key, dry_run=not apply, strict=strict, valid_rows=ok, rejected=rejected, applied=ok if keep else 0, ignored_columns=p["ignored_columns"], total_rows=len(rows))
    if apply and strict and rejected:
        res["note"] = "Nothing was imported because strict mode refuses a file with rejected rows. Fix the rows, or untick strict to import the valid ones."
    return res


# ------------------------------------------------------------------------------------------------------------------------------------ HTTP layer
def build_router(specs: Dict[str, Spec], *, ctx_dep, db_dep, access_dep, gate: Callable, enabled: Callable, audit: Optional[Callable] = None):
    """Routes (mount the result under the module prefix, e.g. /practice):
         GET  /bulk/status            {enabled}: is bulk import on for this organisation (platform switch + plan)?
         GET  /bulk                   the tables and their columns the caller may load
         GET  /bulk/{key}/template    CSV template (header + one example row)
         POST /bulk/{key}             multipart: file, apply (default false = check only), strict (default true)
    `gate(db, ctx)` raises when bulk import is switched off / not in the plan; `enabled(db, ctx)` answers the status question."""
    from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
    from fastapi.responses import Response

    r = APIRouter(prefix="/bulk")

    def spec_for(key):
        s = specs.get(key)
        if s is None:
            raise HTTPException(404, "Unknown table")
        return s

    @r.get("/status")
    def status(ctx=Depends(ctx_dep), db=Depends(db_dep), a=Depends(access_dep)):
        return {"enabled": bool(enabled(db, ctx))}

    @r.get("")
    def catalogue(ctx=Depends(ctx_dep), db=Depends(db_dep), a=Depends(access_dep)):
        gate(db, ctx)
        out = []
        for s in sorted(specs.values(), key=lambda x: (x.order, x.key)):
            c = s.catalogue()
            try:
                a.require(s.capability) if s.capability else None
                c["allowed"] = True
            except HTTPException:
                c["allowed"] = False
            out.append(c)
        return {"items": out}

    @r.get("/{key}/template")
    def template(key: str, ctx=Depends(ctx_dep), db=Depends(db_dep), a=Depends(access_dep)):
        gate(db, ctx)
        return Response(template_csv(spec_for(key)), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{key}-template.csv"'})

    @r.post("/{key}")
    async def load(key: str, file=File(...), apply: bool = Form(False), strict: bool = Form(True), ctx=Depends(ctx_dep), db=Depends(db_dep), a=Depends(access_dep)):
        gate(db, ctx)
        s = spec_for(key)
        raw = await file.read(MAX_BYTES + 1)
        try:
            res = run(db, ctx, a, s, raw, apply=apply, strict=strict, audit=audit)
        except Exception:
            db.rollback()
            raise
        if res["applied"] > 0:
            db.commit()
        else:
            db.rollback()
        return res

    load.__annotations__["file"] = UploadFile          # real class (not a postponed string): FastAPI needs it to build the multipart field
    return r
