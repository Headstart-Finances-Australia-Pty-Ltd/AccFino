"""
Background scheduler for repeating journals. Only templates the user OPTED IN ("run automatically") are touched; everything else still needs "Run due now".

  * a daemon thread wakes every ACCFINO_SCHEDULER_SECONDS (default 900, minimum 30); ACCFINO_SCHEDULER=0 switches it off;
  * the business date uses ACCFINO_TZ (default Australia/Sydney), not the server's clock;
  * several workers/replicas can all run it: on PostgreSQL a session advisory lock lets one sweep at a time, each template row is locked (SKIP LOCKED),
    and an occurrence that already exists is never created again - so a double run cannot double-post;
  * auto-run templates that POST are only honoured while their creator is still an approver; otherwise they fall back to a draft;
  * every sweep writes a heartbeat (system_settings) that the screen shows, and an audit entry when it created anything.
"""
import json
import logging
import os
import threading
from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import text

from accfino_core import models as m
from accfino_core.ledger import journal_tools as JT
from accfino_core.ledger.journal_models import RepeatingJournal

log = logging.getLogger("accfino.scheduler")
LOCK_KEY = 872_401_113                     # arbitrary constant: "accfino repeating journals"
HEARTBEAT_KEY = "ledger.scheduler.heartbeat"


def business_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(os.getenv("ACCFINO_TZ", "Australia/Sydney"))).date()
    except Exception:
        return date.today()


def _ctx_for(db, org, tpl):
    """The creator's CURRENT standing: role from their membership, none if removed or suspended."""
    mem = db.query(m.OrgMembership).filter_by(org_id=org.id, user_id=tpl.created_by).first() if tpl.created_by else None
    role = mem.role if (mem is not None and mem.suspended_at is None) else "none"
    return SimpleNamespace(user_id=tpl.created_by, username="scheduler", role=role, is_admin=False, org=org)


def sweep(session_factory=None, today=None):
    """One pass over every organisation. Returns a summary dict (also stored as the heartbeat)."""
    if session_factory is None:
        from db_app.database import SessionLocal as session_factory
    today = today or business_today()
    db = session_factory()
    pg = db.get_bind().dialect.name == "postgresql"
    locked = False
    try:
        if pg:
            locked = bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar())
            if not locked:
                return dict(skipped="another instance is running the scheduler", today=today.isoformat())
        summary = dict(at=datetime.utcnow().isoformat() + "Z", today=today.isoformat(), organisations=0, templates=0, drafts=0, posted=0, errors=[])
        due = db.query(RepeatingJournal.org_id, RepeatingJournal.id).filter(RepeatingJournal.is_active.is_(True), RepeatingJournal.auto_run.is_(True),
                                                                            RepeatingJournal.next_date <= today).order_by(RepeatingJournal.org_id, RepeatingJournal.id).all()
        by_org = {}
        for org_id, tid in due:
            by_org.setdefault(org_id, []).append(tid)
        for org_id, tids in by_org.items():
            org = db.get(m.Organisation, org_id)
            if org is None:
                continue
            summary["organisations"] += 1
            for tid in tids:
                tpl = db.get(RepeatingJournal, tid)
                if tpl is None:
                    continue
                ctx = _ctx_for(db, org, tpl)
                try:
                    r = JT.run_repeating(db, org, ctx, as_at=today, template_id=tid, only_auto=True)
                except Exception as e:                                # one broken organisation must never stop the sweep
                    db.rollback()
                    log.exception("scheduler: template %s failed", tid)
                    summary["errors"].append(dict(id=tid, error=f"{type(e).__name__}: {e}"[:200]))
                    continue
                summary["templates"] += r["templates"]
                summary["drafts"] += r["drafts"]
                summary["posted"] += r["posted"]
                summary["errors"] += r["errors"]
                if r["drafts"] or r["posted"]:
                    try:
                        from accfino_core.security import audit
                        audit.write("ledger.repeating.auto_run", user_id=tpl.created_by, username="scheduler", org_id=org.id, entity="repeating_journal", entity_id=tid,
                                    detail=dict(drafts=r["drafts"], posted=r["posted"], as_at=today.isoformat()))
                    except Exception:
                        pass
        try:                                                       # automatic exchange-rate feed (opt-in per organisation, once per business day)
            from accfino_core.ledger import fx_feed
            summary["fx_feed"] = fx_feed.sweep_orgs(db, today)
        except Exception as e:
            db.rollback()
            log.exception("scheduler: rate feed failed")
            summary["fx_feed"] = dict(orgs=0, stored=0, errors=[dict(error=f"{type(e).__name__}")])
        row = db.get(m.SystemSetting, HEARTBEAT_KEY)
        payload = json.dumps(summary)
        if row is None:
            db.add(m.SystemSetting(key=HEARTBEAT_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
        return summary
    finally:
        try:
            if locked:
                db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
                db.commit()
        finally:
            db.close()


def heartbeat(db):
    row = db.get(m.SystemSetting, HEARTBEAT_KEY)
    try:
        return json.loads(row.value) if row and row.value else None
    except ValueError:
        return None


class _Runner:
    def __init__(self):
        self.thread, self.stop_event = None, threading.Event()

    def start(self, interval=None, first_delay=20):
        if os.getenv("ACCFINO_SCHEDULER", "1") in ("0", "false", "False", "no"):
            log.info("scheduler: disabled by ACCFINO_SCHEDULER")
            return False
        if self.thread and self.thread.is_alive():
            return True
        interval = max(30, int(interval or os.getenv("ACCFINO_SCHEDULER_SECONDS", "900")))
        self.stop_event.clear()

        def loop():
            if self.stop_event.wait(first_delay):
                return
            while True:
                try:
                    sweep()
                except Exception:
                    log.exception("scheduler sweep failed")
                if self.stop_event.wait(interval):
                    return
        self.thread = threading.Thread(target=loop, name="accfino-scheduler", daemon=True)
        self.thread.start()
        log.info("scheduler: started (every %ss)", interval)
        return True

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.thread = None


runner = _Runner()
start, stop = runner.start, runner.stop
