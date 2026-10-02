"""Automatic subscription billing through Square (card on file).

Flow: the Organisation Admin saves a card (Square's secure form -> token -> Square stores it, we keep only ids + last 4) and presses "Subscribe".
From then on AccFino charges the organisation's plan (+ add-ons) at the start of each monthly/yearly period, extends the paid-up date, and retries a
declined card on day 3 and day 6 (the organisation keeps working through the 7-day grace period). Prices are AUD incl. GST, read from the plans admins edit.

Safety: a charge row (unique idempotency key) is written BEFORE Square is called, so two workers or a restart can never take the same renewal twice."""
import calendar
import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from accfino_core import models as m
from accfino_core.billing import square_client as SQ
from accfino_core.billing.models import BillingCharge, OrgBilling
from accfino_core.openfeed_cdr import seal, unseal
from accfino_core.subscription import service as S
from accfino_core.subscription.models import Addon, OrgSubscription, Plan

log = logging.getLogger("accfino.billing")
MAX_ATTEMPTS = 3                       # first try + two retries (day 3 and day 6), inside the 7-day grace period
RETRY_DAYS = 3
PENDING_STALE = timedelta(minutes=10)
_K = {"token": "square.access_token", "app": "square.application_id", "loc": "square.location_id", "env": "square.environment"}


class BillingError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ---------------------------------------------------------------------------------------------------- platform configuration --
def _get(db, key):
    r = db.get(m.SystemSetting, key)
    return (r.value or "").strip() if r else ""


def _put(db, key, value):
    r = db.get(m.SystemSetting, key)
    if r is None:
        db.add(m.SystemSetting(key=key, value=value))
    else:
        r.value = value
    db.flush()


class SquareCfg:
    """The PLATFORM's Square account (the one AccFino collects subscriptions into). Server environment wins over what the administrator saved."""
    def __init__(self, db):
        e = os.environ.get
        self.access_token = e("SQUARE_ACCESS_TOKEN", "").strip() or (unseal(_get(db, _K["token"])) or "" if _get(db, _K["token"]) else "")
        self.application_id = e("SQUARE_APPLICATION_ID", "").strip() or _get(db, _K["app"])
        self.location_id = e("SQUARE_LOCATION_ID", "").strip() or _get(db, _K["loc"])
        env = e("SQUARE_ENVIRONMENT", "").strip() or _get(db, _K["env"]) or "sandbox"
        self.environment = env if env in SQ.HOSTS else "sandbox"
        self.locked = bool(e("SQUARE_ACCESS_TOKEN", "").strip())

    @property
    def ready(self) -> bool:
        return bool(self.access_token and self.application_id and self.location_id)

    def missing(self) -> list:
        return [n for n, v in (("Access token", self.access_token), ("Application ID", self.application_id), ("Location ID", self.location_id)) if not v]


def square_status(db) -> dict:
    c = SquareCfg(db)
    return {"configured": c.ready, "missing": c.missing(), "environment": c.environment, "application_id": c.application_id, "location_id": c.location_id,
            "locked_by_environment": c.locked, "has_token": bool(c.access_token)}


def save_square(db, *, access_token=None, application_id=None, location_id=None, environment=None, clear=False):
    if environment is not None and environment not in SQ.HOSTS:
        raise BillingError("bad_environment", "Environment must be sandbox or production.", 422)
    if clear:
        _put(db, _K["token"], "")
    elif access_token and access_token.strip():
        _put(db, _K["token"], seal(access_token.strip()))
    for k, v in (("app", application_id), ("loc", location_id), ("env", environment)):
        if v is not None:
            _put(db, _K[k], v.strip())


def test_square(db) -> dict:
    c = SquareCfg(db)
    if not c.ready:
        return {"ok": False, "message": "Still needed: " + ", ".join(c.missing()) + "."}
    try:
        loc = SQ.get_location(c)
    except SQ.SquareError as e:
        return {"ok": False, "message": "Square said: " + (e.detail or e.code)}
    cur, country = loc.get("currency"), loc.get("country")
    if cur and cur != "AUD":
        return {"ok": False, "message": f"This Square location charges in {cur}. AccFino bills in AUD - use your Australian location."}
    return {"ok": True, "message": f"Connected to Square location \"{loc.get('name', c.location_id)}\" ({country or 'AU'}, {cur or 'AUD'}, {c.environment})."}


# ------------------------------------------------------------------------------------------------------------ pricing & dates --
def add_period(d: date, period: str) -> date:
    months = 12 if period == "yearly" else 1
    y, mo = d.year + (d.month - 1 + months) // 12, (d.month - 1 + months) % 12 + 1
    return date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def amount_for(db, sub: OrgSubscription, period: Optional[str] = None) -> Decimal:
    """Plan price for the period + each add-on (add-ons are priced monthly; a year is 10 months, the same 'two months free' as the plans). AUD incl. GST."""
    period = period or sub.billing_period or "monthly"
    plan = db.get(Plan, sub.plan_id)
    if plan is None:
        return Decimal("0")
    total = Decimal(plan.price_yearly if period == "yearly" else plan.price_monthly)
    for aid in dict.fromkeys(S._loads(sub.addons)):
        a = db.get(Addon, aid)
        if a:
            total += Decimal(a.price_monthly) * (10 if period == "yearly" else 1)
    return total.quantize(Decimal("0.01"))


def cents(x: Decimal) -> int:
    return int((x * 100).to_integral_value())


def due_date(sub: OrgSubscription) -> Optional[date]:
    if sub.status in ("cancelled", "expired"):
        return None
    return sub.trial_ends if sub.status == "trial" else sub.period_end


# ------------------------------------------------------------------------------------------------------------------ the card --
def _contact(db, org_id):
    try:
        from accfino_core import org_admin as OA
        c = OA.org_contact(db, org_id)
        return c.get("email") or "", c.get("name") or ""
    except Exception:
        return "", ""


def get_billing(db, org_id) -> OrgBilling:
    b = db.get(OrgBilling, org_id)
    if b is None:
        b = OrgBilling(org_id=org_id, auto_renew=False, failure_count=0)
        db.add(b)
        db.flush()
    return b


def save_card(db, org, user_id: int, source_id: str) -> OrgBilling:
    """source_id is the one-time token from Square's browser form. We never see the card number."""
    cfg = SquareCfg(db)
    if not cfg.ready:
        raise BillingError("not_configured", "Card payments are not switched on for this platform yet. Please contact AccFino support.", 503)
    if not source_id:
        raise BillingError("no_token", "The card could not be read. Please try again.", 400)
    b = get_billing(db, org.id)
    email, _ = _contact(db, org.id)
    try:
        if not b.square_customer_id:
            cust = SQ.create_customer(cfg, idempotency_key=f"accfino-cust-{org.id}", email=email, company=org.name, reference_id=f"org-{org.id}")
            b.square_customer_id = cust.get("id")
        card = SQ.create_card(cfg, source_id=source_id, customer_id=b.square_customer_id, idempotency_key=SQ.key())
    except SQ.SquareError as e:
        raise BillingError("card_rejected", "Your card could not be saved: " + (e.detail or "Square declined it.") + " Please check the details or try another card.", 402)
    old = b.card_id
    b.card_id, b.card_brand, b.card_last4 = card.get("id"), (card.get("card_brand") or "").title(), card.get("last_4")
    b.card_exp_month, b.card_exp_year = card.get("exp_month"), card.get("exp_year")
    b.failure_count, b.next_attempt_on, b.last_error, b.updated_by = 0, None, None, user_id
    db.flush()
    if old and old != b.card_id:                                                      # the replaced card must not stay chargeable
        try:
            SQ.disable_card(cfg, old)
        except SQ.SquareError:
            log.info("old card %s could not be disabled", old)
    return b


def remove_card(db, org_id: int):
    b = db.get(OrgBilling, org_id)
    if b is None or not b.card_id:
        return
    cfg = SquareCfg(db)
    if cfg.ready:
        try:
            SQ.disable_card(cfg, b.card_id)
        except SQ.SquareError:
            pass
    b.card_id = b.card_brand = b.card_last4 = None
    b.card_exp_month = b.card_exp_year = None
    b.auto_renew, b.failure_count, b.next_attempt_on = False, 0, None
    db.flush()


# ----------------------------------------------------------------------------------------------------------------- charging --
def _settle_fail(db, row: BillingCharge, b: OrgBilling, sub: OrgSubscription, err: SQ.SquareError, today: date):
    row.status, row.error, row.settled_at = "failed", (err.detail or err.code)[:290], datetime.utcnow()
    b.failure_count = (b.failure_count or 0) + 1
    b.last_error = row.error
    b.next_attempt_on = today + timedelta(days=RETRY_DAYS) if b.failure_count < MAX_ATTEMPTS else None
    sub.status = "past_due"
    db.flush()
    try:
        from accfino_core import notifications as N
        again = f" We will try again on {b.next_attempt_on.strftime('%d %b %Y')}." if b.next_attempt_on else " We will not retry automatically."
        N.notify_org_admin(db, sub.org_id, "billing_failed", "AccFino subscription payment failed",
                           f"We could not take your AccFino subscription payment ({row.error}).{again} Please update your card in Settings > Business Setup > Organisation > Subscription "
                           f"to keep your organisation active.", dedupe_minutes=60 * 12)
    except Exception as e:                                                             # a failed e-mail must never undo the billing record
        log.warning("billing failure notice not sent for org %s: %s", sub.org_id, e)


def charge_now(db, org_id: int, *, today: Optional[date] = None, period: Optional[str] = None) -> dict:
    """Charge the organisation for its next period. Returns {status: paid|failed|skipped|free, ...}. Safe to call twice."""
    today = today or date.today()
    cfg = SquareCfg(db)
    sub, b = db.get(OrgSubscription, org_id), db.get(OrgBilling, org_id)
    if sub is None or b is None or not b.card_id or not b.square_customer_id:
        return {"status": "skipped", "reason": "no card or plan"}
    if not cfg.ready:
        return {"status": "skipped", "reason": "square not configured"}
    if period:
        sub.billing_period = period
    amt = amount_for(db, sub)
    start = today if (sub.period_end is None or sub.period_end < today or sub.status == "trial") else sub.period_end
    end = add_period(start, sub.billing_period)
    if amt <= 0:                                                                       # free plan: nothing to take, just roll the period on
        sub.status, sub.period_end, sub.trial_ends = "active", end, None
        b.failure_count, b.next_attempt_on = 0, None
        db.flush()
        return {"status": "free", "period_end": end.isoformat()}
    key = f"accfino-{org_id}-{start.isoformat()}-{sub.billing_period}-{b.failure_count or 0}"
    row = db.query(BillingCharge).filter_by(idempotency_key=key).first()
    if row is not None and row.status == "paid":
        return {"status": "skipped", "reason": "already paid"}
    if row is not None and row.status == "pending" and datetime.utcnow() - (row.created_at or datetime.utcnow()) < PENDING_STALE:
        return {"status": "skipped", "reason": "another worker is charging"}
    if row is None:
        row = BillingCharge(org_id=org_id, idempotency_key=key, amount_cents=cents(amt), plan_id=sub.plan_id, billing_period=sub.billing_period,
                            period_start=start, period_end=end, status="pending")
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:
            return {"status": "skipped", "reason": "another worker is charging"}
        db.commit()                                                                    # the claim is visible to every worker BEFORE money moves
        sub, b = db.get(OrgSubscription, org_id), db.get(OrgBilling, org_id)
    email, _ = _contact(db, org_id)
    plan = db.get(Plan, sub.plan_id)
    try:
        pay = SQ.create_payment(cfg, card_id=b.card_id, customer_id=b.square_customer_id, amount_cents=row.amount_cents, idempotency_key=key, email=email,
                                note=f"AccFino {plan.name if plan else sub.plan_id} ({sub.billing_period}) {start.isoformat()} to {end.isoformat()}", reference_id=f"org-{org_id}")
    except SQ.SquareError as e:
        _settle_fail(db, row, b, sub, e, today)
        return {"status": "failed", "error": row.error, "attempt": b.failure_count}
    if pay.get("status") not in ("COMPLETED", "APPROVED"):
        _settle_fail(db, row, b, sub, SQ.SquareError("payment_" + str(pay.get("status")).lower(), f"Payment status {pay.get('status')}"), today)
        return {"status": "failed", "error": row.error, "attempt": b.failure_count}
    row.status, row.square_payment_id, row.receipt_url, row.settled_at, row.error = "paid", pay.get("id"), pay.get("receipt_url"), datetime.utcnow(), None
    sub.status, sub.period_end, sub.trial_ends = "active", end, None
    b.failure_count, b.next_attempt_on, b.last_error = 0, None, None
    db.flush()
    return {"status": "paid", "amount": float(amt), "period_end": end.isoformat(), "payment_id": row.square_payment_id, "receipt_url": row.receipt_url}


def subscribe(db, org_id: int, period: str, user_id: int) -> dict:
    """'Subscribe' pressed: pick monthly/yearly, turn automatic renewal on and take the first payment now (unless the period is already paid)."""
    if period not in ("monthly", "yearly"):
        raise BillingError("bad_period", "Choose monthly or yearly.", 422)
    b = db.get(OrgBilling, org_id)
    sub = db.get(OrgSubscription, org_id)
    if sub is None:
        raise BillingError("no_plan", "This organisation has no plan yet. Ask AccFino support to assign one.", 409)
    if b is None or not b.card_id:
        raise BillingError("no_card", "Add a card first.", 409)
    b.auto_renew, b.updated_by = True, user_id
    sub.billing_period = period
    today = date.today()
    if sub.status == "active" and sub.period_end and sub.period_end > today:           # already paid up: renewal starts on the paid-up date
        db.flush()
        return {"status": "scheduled", "period_end": sub.period_end.isoformat()}
    return charge_now(db, org_id, today=today)


def run_due(db_factory, today: Optional[date] = None) -> dict:
    """Charge every organisation whose period has ended (retrying declines on schedule). One transaction per organisation; never raises."""
    today = today or date.today()
    out = {"paid": 0, "failed": 0, "free": 0, "skipped": 0, "errors": 0}
    db = db_factory()
    try:
        ids = [r[0] for r in db.query(OrgBilling.org_id).filter(OrgBilling.auto_renew.is_(True), OrgBilling.card_id.isnot(None)).all()]
    finally:
        db.close()
    for org_id in ids:
        db = db_factory()
        try:
            sub, b = db.get(OrgSubscription, org_id), db.get(OrgBilling, org_id)
            due = due_date(sub) if sub else None
            if due is None or today < due or (b.failure_count or 0) >= MAX_ATTEMPTS or (b.next_attempt_on and today < b.next_attempt_on):
                out["skipped"] += 1
                continue
            res = charge_now(db, org_id, today=today)
            db.commit()
            out[res["status"] if res["status"] in out else "skipped"] += 1
        except Exception:
            db.rollback()
            log.exception("billing run failed for org %s", org_id)
            out["errors"] += 1
        finally:
            db.close()
    return out


# ------------------------------------------------------------------------------------------------------------------ read views --
def org_view(db, org_id: int) -> dict:
    cfg = SquareCfg(db)
    b, sub = db.get(OrgBilling, org_id), db.get(OrgSubscription, org_id)
    plan = db.get(Plan, sub.plan_id) if sub else None
    due = due_date(sub) if sub else None
    charges = db.query(BillingCharge).filter_by(org_id=org_id).order_by(BillingCharge.id.desc()).limit(12).all()
    return {"available": cfg.ready, "square": {"applicationId": cfg.application_id, "locationId": cfg.location_id, "environment": cfg.environment} if cfg.ready else None,
            "has_plan": plan is not None, "plan_name": plan.name if plan else None, "billing_period": sub.billing_period if sub else None, "status": sub.status if sub else None,
            "period_end": sub.period_end.isoformat() if sub and sub.period_end else None,
            "amount_next": float(amount_for(db, sub)) if sub and plan else None,
            "prices": {"monthly": float(amount_for(db, sub, "monthly")), "yearly": float(amount_for(db, sub, "yearly"))} if sub and plan else None, "next_charge_on": due.isoformat() if due and b and b.auto_renew else None,
            "card": {"brand": b.card_brand, "last4": b.card_last4, "exp_month": b.card_exp_month, "exp_year": b.card_exp_year} if b and b.card_id else None,
            "auto_renew": bool(b and b.auto_renew), "failure_count": b.failure_count if b else 0, "last_error": b.last_error if b else None,
            "charges": [{"id": c.id, "date": (c.settled_at or c.created_at).isoformat() + "Z" if (c.settled_at or c.created_at) else None, "amount": c.amount_cents / 100, "status": c.status,
                         "plan_id": c.plan_id, "billing_period": c.billing_period, "period_start": c.period_start.isoformat() if c.period_start else None,
                         "period_end": c.period_end.isoformat() if c.period_end else None, "receipt_url": c.receipt_url, "error": c.error} for c in charges]}


def admin_overview(db) -> dict:
    rows = []
    for b in db.query(OrgBilling).order_by(OrgBilling.org_id).all():
        org, sub = db.get(m.Organisation, b.org_id), db.get(OrgSubscription, b.org_id)
        due = due_date(sub) if sub else None
        rows.append({"org_id": b.org_id, "org_name": org.name if org else f"#{b.org_id}", "plan_id": sub.plan_id if sub else None, "billing_period": sub.billing_period if sub else None,
                     "status": sub.status if sub else None, "period_end": sub.period_end.isoformat() if sub and sub.period_end else None,
                     "card": f"{b.card_brand or ''} ···· {b.card_last4}" if b.card_id else None, "auto_renew": bool(b.auto_renew), "failure_count": b.failure_count or 0,
                     "last_error": b.last_error, "next_charge_on": due.isoformat() if due and b.auto_renew else None})
    recent = db.query(BillingCharge).order_by(BillingCharge.id.desc()).limit(25).all()
    return {"organisations": rows, "recent": [{"id": c.id, "org_id": c.org_id, "amount": c.amount_cents / 100, "status": c.status, "error": c.error,
                                                "date": (c.settled_at or c.created_at).isoformat() + "Z" if (c.settled_at or c.created_at) else None} for c in recent]}
