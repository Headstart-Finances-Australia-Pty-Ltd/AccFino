"""
Automatic exchange-rate feed (opt-in per organisation).

Source: the European Central Bank's euro foreign-exchange reference rates (a public XML file published each working day). The ECB quotes every currency
against the euro, so a rate between the organisation's base currency and a foreign currency is a CROSS RATE:  base per 1 foreign = (base per EUR) / (foreign per EUR).
These are reference rates - not the rate any bank actually gave you. A rate typed in by the organisation for the same day is NEVER overwritten (manual wins).

  * off by default; an approver switches it on and chooses extra currencies. Currencies used by foreign-held accounts, drafts and repeating templates are
    always included, so a revaluation is never blocked by a rate that could have been fetched;
  * one fetch per business day from the background scheduler, or on demand ("Fetch now", with an optional 90-day backfill);
  * a failure to reach the ECB, a malformed file or an unsupported currency is reported and leaves existing rates untouched - never a guessed value.

The HTTP call is `http_get` (replaced in tests). The XML is size-capped before parsing and read with the standard library (no external entities are resolved).
"""
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books.common import BooksError
from accfino.modules.accounting.ledger import journal_tools as JT
from accfino.modules.accounting.ledger.journal_models import FxRate, JournalDraft, RepeatingJournal

log = logging.getLogger("accfino.fxfeed")
ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
SOURCE = "ECB"
MAX_BYTES = 3_000_000


def http_get(url):
    import requests
    r = requests.get(url, timeout=15, headers={"User-Agent": "AccFino-rate-feed"}, stream=True)
    r.raise_for_status()
    raw = r.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(raw) > MAX_BYTES:
        raise BooksError("The rate file is unexpectedly large; ignored")
    return raw


def parse_ecb(raw):
    """-> {date: {currency: units per 1 EUR}} (EUR itself added as 1)."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise BooksError("The rate file is unexpectedly large; ignored")
    if b"<!DOCTYPE" in raw[:2000] or b"<!ENTITY" in raw:
        raise BooksError("The rate file has an unexpected structure; ignored")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise BooksError("The rate file could not be read; ignored")
    days = {}
    for el in root.iter():
        if el.tag.split("}")[-1] != "Cube" or "time" not in el.attrib:
            continue
        try:
            d = date.fromisoformat(el.attrib["time"])
        except ValueError:
            continue
        table = {"EUR": Decimal(1)}
        for c in el:
            cur, rate = c.attrib.get("currency"), c.attrib.get("rate")
            if cur and rate and re.fullmatch(r"[A-Z]{3}", cur):
                try:
                    v = Decimal(rate)
                except Exception:
                    continue
                if v > 0:
                    table[cur] = v
        if len(table) > 1:
            days[d] = table
    if not days:
        raise BooksError("The rate file contained no rates; ignored")
    return days


def cross(table, base, foreign):
    """base per 1 foreign, or None when either currency is not in that day's table."""
    if base not in table or foreign not in table:
        return None
    return (table[base] / table[foreign]).quantize(Decimal("0.00000001"))


def wanted_currencies(db, org, settings=None):
    settings = settings or JT.get_settings(db, org)
    base = JT.base_currency(org)
    want = {c for c in settings.get("fx_feed_currencies", []) if re.fullmatch(r"[A-Z]{3}", c)}
    want |= {a.foreign_currency for a in db.query(lm.LedgerAccount).filter(lm.LedgerAccount.org_id == org.id, lm.LedgerAccount.foreign_currency.isnot(None))}
    want |= {c for (c,) in db.query(JournalDraft.currency).filter(JournalDraft.org_id == org.id, JournalDraft.currency.isnot(None)).distinct()}
    want |= {c for (c,) in db.query(RepeatingJournal.currency).filter(RepeatingJournal.org_id == org.id, RepeatingJournal.currency.isnot(None)).distinct()}
    return sorted(c for c in want if c and c != base)


def apply_rates(db, org, days, currencies):
    """Store cross rates. Returns counts; never overwrites a rate that was not fetched from this feed."""
    base, out = JT.base_currency(org), dict(stored=0, updated=0, kept_manual=0, unsupported=[], dates=[])
    for cur in currencies:
        got = False
        for d, table in sorted(days.items()):
            r = cross(table, base, cur)
            if r is None:
                continue
            got = True
            row = db.query(FxRate).filter_by(org_id=org.id, currency=cur, rate_date=d).one_or_none()
            if row is None:
                db.add(FxRate(org_id=org.id, currency=cur, rate_date=d, rate=r, source=SOURCE))
                out["stored"] += 1
            elif row.source == SOURCE:
                if Decimal(row.rate) != r:
                    row.rate = r
                    out["updated"] += 1
            else:
                out["kept_manual"] += 1
        if not got:
            out["unsupported"].append(cur)
    out["dates"] = sorted({d.isoformat() for d in days})[-1:]
    db.flush()
    return out


def fetch_for_org(db, org, *, backfill=False, only_currencies=None, getter=None):
    getter = getter or http_get
    cur = only_currencies or wanted_currencies(db, org)
    if not cur:
        raise BooksError("There are no foreign currencies to fetch. Choose currencies, or mark an account as foreign-held first")
    try:
        days = parse_ecb(getter(ECB_90D if backfill else ECB_DAILY))
    except BooksError:
        raise
    except Exception as e:
        raise BooksError(f"Could not reach the rate source ({type(e).__name__}). Existing rates are unchanged; try again later or enter rates by hand", 502)
    res = apply_rates(db, org, days, cur)
    res.update(currencies=cur, source=SOURCE, backfill=backfill, at=datetime.utcnow().isoformat() + "Z")
    return res


# ---------------------------------------------------------------------------------------------------- status
def _key(org):
    return f"ledger.fxfeed:{org.id}"


def status(db, org):
    row = db.get(m.SystemSetting, _key(org))
    last = None
    if row and row.value:
        try:
            last = json.loads(row.value)
        except ValueError:
            pass
    s = JT.get_settings(db, org)
    return dict(enabled=bool(s.get("fx_feed_enabled")), currencies=s.get("fx_feed_currencies", []), effective_currencies=wanted_currencies(db, org, s), source=SOURCE,
                base=JT.base_currency(org), last_run=last)


def record(db, org, payload):
    row = db.get(m.SystemSetting, _key(org))
    if row is None:
        db.add(m.SystemSetting(key=_key(org), value=json.dumps(payload)))
    else:
        row.value = json.dumps(payload)
    db.flush()


def sweep_orgs(db, today, getter=None):
    """Called by the scheduler once per business day per organisation that opted in. One failure never stops the others."""
    summary = dict(orgs=0, stored=0, errors=[])
    cache = {}

    def cached(url):
        if url not in cache:
            cache[url] = (getter or http_get)(url)
        return cache[url]
    for org in db.query(m.Organisation).all():
        s = JT.get_settings(db, org)
        if not s.get("fx_feed_enabled"):
            continue
        last = status(db, org)["last_run"]
        if last and last.get("business_date") == today.isoformat() and last.get("ok"):
            continue
        try:
            r = fetch_for_org(db, org, getter=cached)
            record(db, org, dict(ok=True, business_date=today.isoformat(), **r))
            summary["orgs"] += 1
            summary["stored"] += r["stored"]
        except BooksError as e:
            db.rollback()
            record(db, org, dict(ok=False, business_date=today.isoformat(), error=str(e), at=datetime.utcnow().isoformat() + "Z"))
            summary["errors"].append(dict(org_id=org.id, error=str(e)))
        except Exception as e:                                                 # never let one organisation stop the sweep
            db.rollback()
            log.exception("fx feed failed for org %s", org.id)
            summary["errors"].append(dict(org_id=org.id, error=f"{type(e).__name__}"))
        db.commit()
    return summary
