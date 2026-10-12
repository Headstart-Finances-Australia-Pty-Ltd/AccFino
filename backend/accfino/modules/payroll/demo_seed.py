"""
DEMO / TEST payroll data. Development and testing ONLY - never run against a production organisation.

    python -m accfino.modules.payroll.demo_seed --status
    python -m accfino.modules.payroll.demo_seed --load            create the demo data (does nothing if it already exists: idempotent)
    python -m accfino.modules.payroll.demo_seed --reset           delete the demo organisations, their users and ALL their data (including the ledger)
    python -m accfino.modules.payroll.demo_seed --reload          reset, then load (a clean, repeatable demo environment)
    add  --sqlite /tmp/payroll_demo.db   to build an offline SQLite database instead of using DATABASE_URL

What it builds (all clearly named "(DEMO)"; every employee has is_demo = true):
  * 2 organisations, 27 employees, logins for every role (password: DEMO_PASSWORD, default below)
  * FY2026-27 history produced by the REAL services (create -> calculate -> approve -> finalise -> payslips -> ledger journal), so it all reconciles
  * an open "current" period for you to process, with timesheets in every state, pending leave, and edge-case employees
It is deliberately limited to FY2026-27: statutory rules are only loaded for that year, and the engine refuses to calculate outside them.
"""
import argparse
import logging
import os
import sys
from datetime import date, timedelta

from sqlalchemy import text

log = logging.getLogger("accfino.payroll.demo")
DEMO_SUFFIX = "(DEMO)"
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo-Payroll-1!")
TODAY = date(2026, 10, 5)
PHONE = "+61400000000"
FY_START_MONDAY = date(2026, 6, 29)

ORGS = [
    dict(key="harbour", name="Harbour & Co Pty Ltd (DEMO)", abn="51 824 753 556", domain="harbour.accfino.test"),
    dict(key="outback", name="Outback Supplies Pty Ltd (DEMO)", abn="53 004 085 616", domain="outback.accfino.test"),
]
ROLE_USERS = [("owner", "owner"), ("padmin", "payroll_admin"), ("pmanager", "payroll"), ("accountant", "accountant"), ("bookkeeper", "bookkeeper")]


def make_tfn(n: int) -> str:
    """A valid (check-digit correct) test TFN, deterministic from n."""
    w = (1, 4, 3, 7, 5, 8, 6, 9, 10)
    base = 100000 + (n * 7919) % 899999
    for attempt in range(1000):
        d = [int(c) for c in f"{base + attempt:08d}"[-8:]]
        s = sum(a * b for a, b in zip(d, w))
        last = s % 11
        if last <= 9:
            return "".join(map(str, d)) + str(last)
    raise RuntimeError("no TFN")


def is_demo_org(org) -> bool:
    return (org.name or "").endswith(DEMO_SUFFIX)


# ---------------------------------------------------------------------------------------------------------- reset / status --
def demo_orgs(db):
    from accfino.core import models as m
    return db.query(m.Organisation).filter(m.Organisation.name.like(f"%{DEMO_SUFFIX}")).all()


def reset(db, log=print) -> int:
    """Remove the demo organisations, ALL their data (ledger included) and the demo logins. Uses the platform's force-delete (triggers lifted inside one transaction)."""
    from accfino.core.platform_admin import force_delete as FD
    n = 0
    for org in demo_orgs(db):
        r = FD.delete_organisation(db, org.id, force=True)
        db.commit()
        log(f"  removed {r['name']}: {len(r['users_deleted'])} user(s), {r['journals_removed']} journal(s)")
        n += 1
    return n


def status(db) -> list:
    from accfino.modules.payroll.models.payroll import PayEmployee, PayPayslip, PayRun
    out = []
    for org in demo_orgs(db):
        out.append(dict(org_id=org.id, name=org.name, employees=db.query(PayEmployee).filter_by(org_id=org.id).count(), runs=db.query(PayRun).filter_by(org_id=org.id).count(),
                        payslips=db.query(PayPayslip).filter_by(org_id=org.id).count()))
    return out


# ------------------------------------------------------------------------------------------------------------------ helpers --
class Env:
    def __init__(self, db, org, owner_ctx, domain):
        from accfino.modules.payroll.access import Access
        self.db, self.org, self.ctx, self.domain = db, org, owner_ctx, domain
        self.a = Access(db, owner_ctx)
        self.emps, self.funds, self.cals, self.depts, self.items = {}, {}, {}, {}, {}

    def item(self, code):
        if code not in self.items:
            from accfino.modules.payroll.models.payroll import PayItem
            self.items[code] = self.db.query(PayItem).filter_by(org_id=self.org.id, code=code).one()
        return self.items[code]


def make_user(db, email, name, username):
    import bcrypt
    from accfino.core.identity.user import User
    from accfino.core.migrate import ensure_user_security
    u = User(username=username, full_name=name, email=email, phone=PHONE, password=bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode(), home_company="")
    db.add(u)
    db.flush()
    ensure_user_security(db, u.id)
    return u


def make_org(db, spec):
    from accfino.core import models as m
    from accfino.core.security.context import OrgContext
    from accfino.shared.contracts import registry
    owner = make_user(db, f"demo.owner@{spec['domain']}", f"{spec['name'].split(' Pty')[0]} Owner", f"{spec['key']}.owner")
    org = m.Organisation(name=spec["name"], legal_name=spec["name"], abn=spec["abn"], entity_type="company", gst_registered=True, gst_basis="accrual", fy_end_month=6)
    db.add(org)
    db.flush()
    db.add(m.OrgMembership(org_id=org.id, user_id=owner.id, role="owner", is_default=True))
    org.admin_user_id = owner.id
    db.flush()
    registry.provision_org(db, org)                              # chart of accounts + payroll settings, pay items, leave types
    db.commit()
    return org, OrgContext(owner.id, owner.username, False, org, "owner")


def add_logins(db, env):
    from accfino.core import models as m
    users = {}
    for key, role in ROLE_USERS[1:]:
        u = make_user(db, f"demo.{key}@{env.domain}", f"Demo {key.title()}", f"{env.org.name.split()[0].lower()}.{key}")
        db.add(m.OrgMembership(org_id=env.org.id, user_id=u.id, role=role))
        users[key] = u
    db.flush()
    return users


def setup_org(env, spec_key):
    import accfino.modules.accounting.public as accounting
    from accfino.modules.payroll.services import config as C
    db, ctx, a = env.db, env.ctx, env.a
    bank = accounting.ensure_ledger_account(db, env.org.id, code="090", name="Business Cheque Account", account_type="bank")
    C.save_settings(db, ctx, a, {"payment_config": {"bsb": "062-000", "account": "12345678", "account_name": env.org.name.replace(" (DEMO)", ""), "apca_user_id": "301500", "bank_abbrev": "CBA", "description": "PAYROLL"},
                                 "accounting_map": {"payment_bank": bank["id"]}, "stp_config": {"bms_id": "ACCFINO-DEMO"}, "payslip_config": {"show_ytd": True, "show_leave": True, "footer": "DEMO DATA - not a real payslip."}})
    for name, usi, default, typ in (("AustralianSuper", "STA0100AU", True, "apra"), ("Aware Super", "SPS0001AU", False, "apra"), ("HostPlus", "HOS0100AU", False, "apra")):
        env.funds[name] = C.save_fund(db, ctx, a, {"name": name, "usi": usi, "is_default": default, "fund_type": typ})
    env.funds["Smith Family SMSF"] = C.save_fund(db, ctx, a, {"name": "Smith Family SMSF", "fund_type": "smsf", "abn": "51 824 753 556", "smsf_bsb": "063-000", "smsf_account": "55667788", "smsf_account_name": "Smith Family Super Fund"})
    for code, name in (("OPS", "Operations"), ("SAL", "Sales"), ("FIN", "Finance"), ("EXE", "Executive")):
        env.depts[code] = C.save_department(db, ctx, a, {"code": code, "name": name})
    C.save_location(db, ctx, a, {"code": "SYD", "name": "Sydney HQ", "state": "NSW"})
    env.cals["fortnightly"] = C.save_calendar(db, ctx, a, {"name": "Fortnightly (Mon start)", "frequency": "fortnightly", "anchor_start": FY_START_MONDAY, "pay_offset_days": 5, "is_default": True})
    env.cals["weekly"] = C.save_calendar(db, ctx, a, {"name": "Weekly casuals", "frequency": "weekly", "anchor_start": FY_START_MONDAY, "pay_offset_days": 5})
    env.cals["monthly"] = C.save_calendar(db, ctx, a, {"name": "Monthly executives", "frequency": "monthly", "anchor_start": date(2026, 7, 1), "pay_offset_days": 0})
    C.save_item(db, ctx, a, {"code": "SSPCT", "name": "Salary sacrifice super (% of ordinary earnings)", "kind": "salary_sacrifice_super", "calc_method": "percent_of_gross", "percent": 10})
    db.commit()


def employee(env, num, first, last, *, dept="OPS", pos="", etype="full_time", salary=None, hourly=None, freq="fortnightly", start=date(2025, 7, 1), hpw=38, funds=(("AustralianSuper", 100),),
             tfn=True, bank=True, tax=None, bank_split=False, login=None, std_hours=False, dob=None, manager=None):
    from accfino.modules.payroll.services import employees as E
    db, ctx, a = env.db, env.ctx, env.a
    body = dict(employee_number=num, first_name=first, last_name=last, position=pos, employment_type=etype, start_date=start, pay_frequency=freq, calendar_id=env.cals[freq].id,
                department_id=env.depts[dept].id, pay_basis="hourly" if hourly else "salary", annual_salary=None if hourly else salary, hourly_rate=hourly, hours_per_week=hpw,
                email=f"{first}.{last}@{env.domain}".lower(), date_of_birth=dob or date(1985, 1, 1) + timedelta(days=(len(first) * 211 + len(last) * 97) % 4000), pay_standard_hours=std_hours,
                address_line1="1 Demo Street", suburb="Sydney", state="NSW", postcode="2000", manager_id=manager.id if manager else None)
    e = E.create_employee(db, ctx, a, body)
    e.is_demo = True
    t = dict(claims_tft=True, declaration_date=start)
    if tfn:
        t["tfn"] = make_tfn(int(num[1:]) + (1000 if env.domain.startswith("out") else 0))
    t.update(tax or {})
    E.set_tax(db, ctx, a, e.id, t)
    if funds:
        E.set_super(db, ctx, a, e.id, [dict(fund_id=env.funds[f].id, member_number=f"M{e.id:06d}", allocation_pct=p, choice_form_date=start) for f, p in funds])
    if bank:
        accts = [dict(account_name=f"{first} {last}", bsb="062-000", account_number=f"{10000000 + e.id * 37}", allocation_type="remainder")]
        if bank_split:
            accts = [dict(account_name=f"{first} {last} savings", bsb="063-000", account_number=f"{20000000 + e.id * 41}", allocation_type="fixed", allocation_value=200),
                     dict(account_name=f"{first} {last} everyday", bsb="062-000", account_number=f"{10000000 + e.id * 37}", allocation_type="remainder")]
        E.set_bank(db, ctx, a, e.id, accts)
    if login:
        e.user_id = login.id
    env.emps[num] = e
    return e


def assign(env, num, code, **kw):
    from accfino.modules.payroll.services import employees as E
    E.assign_item(env.db, env.ctx, env.a, env.emps[num].id, dict(pay_item_id=env.item(code).id, **kw))


def opening_leave(env, num, code, hours):
    from accfino.modules.payroll.models.payroll import PayLeaveType
    from accfino.modules.payroll.services import leave as L
    lt = env.db.query(PayLeaveType).filter_by(org_id=env.org.id, code=code).one()
    L.adjust(env.db, env.ctx, env.a, env.emps[num].id, lt.id, hours, "Opening balance (demo)", "opening", txn_date=date(2026, 7, 1))


def leave_request(env, num, code, start, end, *, decide=None, note="", hours=None):
    from accfino.modules.payroll.models.payroll import PayLeaveType
    from accfino.modules.payroll.services import leave as L
    lt = env.db.query(PayLeaveType).filter_by(org_id=env.org.id, code=code).one()
    r = L.request_leave(env.db, env.ctx, env.a, dict(employee_id=env.emps[num].id, leave_type_id=lt.id, start_date=start, end_date=end, hours=hours, reason=note or "Demo"))
    if decide is not None:
        L.decide(env.db, env.ctx, env.a, r.id, decide, "" if decide else (note or "Not approved (demo)"))
    return r


def timesheet(env, num, week_start, daily, *, ot=0, state="approved", sat=0, reason="Missing a day (demo)"):
    from accfino.modules.payroll.services import timesheets as T
    e = env.emps[num]
    lines = [dict(work_date=week_start + timedelta(days=i), pay_item_id=env.item("ORD").id, hours=h, break_minutes=30) for i, h in enumerate(daily) if h]
    if ot:
        lines.append(dict(work_date=week_start + timedelta(days=len([h for h in daily if h]) - 1), pay_item_id=env.item("OT15").id, hours=ot))
    if sat:
        lines.append(dict(work_date=week_start + timedelta(days=5), pay_item_id=env.item("SAT").id, hours=sat))
    ts = T.save(env.db, env.ctx, env.a, dict(employee_id=e.id, week_start=week_start, lines=lines, notes="Demo timesheet"))
    if state in ("submitted", "approved", "rejected"):
        T.submit(env.db, env.ctx, env.a, ts.id)
    if state == "approved":
        T.decide(env.db, env.ctx, env.a, ts.id, True)
    if state == "rejected":
        T.decide(env.db, env.ctx, env.a, ts.id, False, reason)
    return ts


def run_period(env, cal_key, start, *, inputs=(), finalise=True, label=""):
    """Create, calculate, approve and finalise a pay run through the real services. Fails loudly if the data has an error (a seed bug, never swallowed)."""
    from accfino.modules.payroll.services import config as C, payruns as R
    db, ctx, a = env.db, env.ctx, env.a
    cal = env.cals[cal_key]
    p = C.period_containing(cal, start)
    r = R.create_run(db, ctx, a, dict(calendar_id=cal.id, period_start=p["period_start"], period_end=p["period_end"], pay_date=p["pay_date"]))
    for num, code, kw in inputs:
        R.add_input(db, ctx, a, r.id, dict(employee_id=env.emps[num].id, pay_item_id=env.item(code).id, **kw))
    R.calculate(db, ctx, a, r.id)
    if r.error_count:
        bad = [(x.employee_name, x.errors) for x in db.query(__import__("accfino.modules.payroll.models.payroll", fromlist=["PayRunEmployee"]).PayRunEmployee).filter_by(run_id=r.id) if x.errors]
        raise RuntimeError(f"demo seed: {r.run_no} {label} has errors: {bad}")
    if finalise:
        R.approve(db, ctx, a, r.id)
        R.finalise(db, ctx, a, r.id)
    db.commit()
    return r


def fortnight_starts(n):
    return [FY_START_MONDAY + timedelta(days=14 * i) for i in range(n)]


def week_starts(n):
    return [FY_START_MONDAY + timedelta(days=7 * i) for i in range(n)]


# ------------------------------------------------------------------------------------------------------------------ the data --
def load_harbour(db, spec, log=print):
    from accfino.modules.payroll.models.payroll import PayPayment, PaySuperContribution
    from accfino.modules.payroll.services import employees as E, payments as P, payruns as R, stp as STP, superfunds as SF
    org, ctx = make_org(db, spec)
    env = Env(db, org, ctx, spec["domain"])
    logins = add_logins(db, env)
    olivia_login = make_user(db, f"demo.olivia@{spec['domain']}", "Olivia Chen", "harbour.olivia")
    from accfino.core import models as m
    db.add(m.OrgMembership(org_id=org.id, user_id=olivia_login.id, role="employee"))
    db.flush()
    setup_org(env, "harbour")

    oli = employee(env, "E0001", "Olivia", "Chen", dept="FIN", pos="Finance Manager", salary=128000, funds=(("Aware Super", 100),), tax=dict(has_study_loan=True, study_loan_type="HELP"), login=olivia_login, dob=date(1988, 3, 14))
    employee(env, "E0002", "Liam", "Nguyen", dept="SAL", pos="Account Executive", salary=96000, manager=oli)
    employee(env, "E0003", "Priya", "Raman", dept="FIN", pos="Accounts Officer", etype="part_time", salary=57000, hpw=22.8, manager=oli)
    employee(env, "E0004", "Marcus", "Reid", dept="OPS", pos="Warehouse Casual", etype="casual", hourly=34.5, freq="weekly")
    employee(env, "E0005", "Sofia", "Rossi", dept="OPS", pos="Warehouse Casual", etype="casual", hourly=33.0, freq="weekly")
    employee(env, "E0006", "Daniel", "Park", dept="SAL", pos="Sales Rep (new starter)", salary=88000, start=date(2026, 9, 8), manager=oli, dob=date(1999, 6, 2))
    employee(env, "E0007", "Hannah", "Wells", dept="EXE", pos="Chief Operating Officer", salary=145000, freq="monthly", funds=(("HostPlus", 100),))
    employee(env, "E0008", "Tom", "Baxter", dept="OPS", pos="Operations Lead", salary=82000)
    employee(env, "E0009", "Grace", "Lim", dept="FIN", pos="Payroll Clerk", etype="part_time", hourly=38.0, hpw=30, std_hours=True, bank_split=True)
    employee(env, "E0010", "Ethan", "Brooks", dept="OPS", pos="Contractor-style Engineer", salary=70000, funds=(("Smith Family SMSF", 100),), tax=dict(residency="foreign_resident", claims_tft=False))
    employee(env, "E0011", "Zara", "Khan", dept="SAL", pos="Sales Manager (second job)", salary=105000, tax=dict(claims_tft=False), manager=oli)
    employee(env, "E0012", "Noah", "Fisher", dept="OPS", pos="Technician", salary=90000, dob=date(1960, 1, 20))
    employee(env, "E0013", "Richard", "Stone", dept="EXE", pos="Chief Financial Officer", salary=180000, freq="monthly", funds=(("AustralianSuper", 50), ("HostPlus", 50)))
    for n, c, h in (("E0001", "AL", 120), ("E0001", "PL", 60), ("E0002", "AL", 80), ("E0003", "AL", 60), ("E0003", "PL", 30), ("E0008", "AL", 90), ("E0008", "PL", 40), ("E0009", "AL", 40), ("E0011", "AL", 70),
                    ("E0012", "AL", 64), ("E0007", "AL", 150), ("E0013", "AL", 100), ("E0010", "AL", 50)):
        opening_leave(env, n, c, h)
    assign(env, "E0001", "SSUPER", amount=300)                  # salary sacrifice
    assign(env, "E0002", "TOOL"); assign(env, "E0002", "UNION"); assign(env, "E0002", "GIVING", amount=10)       # allowance + multiple deductions
    assign(env, "E0011", "LOAN", amount=50)
    assign(env, "E0013", "ADDSUPER", amount=200)
    db.commit()

    # --- history: casual timesheets for 12 weeks (28 Jun .. 20 Sep) then pay runs ---
    pattern = {"E0004": ([8, 8, 8, 8, 0], 0), "E0005": ([6, 7, 6, 7, 6], 0)}
    for i, ws in enumerate(week_starts(12)):
        timesheet(env, "E0004", ws, [8, 8, 8, 8, 8] if i % 3 else [8, 8, 8, 8, 4], ot=3 if i % 4 == 0 else 0)             # overtime on some weeks
        timesheet(env, "E0005", ws, [6, 7, 6, 7, 6], sat=4 if i % 5 == 2 else 0)                                         # Saturday penalty on some weeks
    leave_request(env, "E0008", "LWP", date(2026, 8, 17), date(2026, 8, 21), decide=True, note="Unpaid week")
    db.commit()
    fn = fortnight_starts(6)
    for i, st in enumerate(fn):
        if i == 3:                                                  # Noah resigns in the 10-23 Aug period: final pay incl. unused annual leave
            E.terminate_employee(db, ctx, env.a, env.emps["E0012"].id, date(2026, 8, 21), "Resigned")
            db.commit()
        if i == 5:
            leave_request(env, "E0008", "AL", date(2026, 9, 14), date(2026, 9, 18), decide=True, note="Family holiday")
        extra = []
        if i == 3:
            from accfino.modules.payroll.services import leave as L
            sug = L.payout_suggestion(db, ctx, env.a, env.emps["E0012"].id)
            extra.append(("E0012", "TLEAVE", dict(amount=sug[0]["amount"], note="Unused annual leave on resignation")))
        run_period(env, "fortnightly", st, inputs=extra, label=f"fortnight {i + 1}")
    for i, ws in enumerate(week_starts(12)):
        run_period(env, "weekly", ws, label=f"week {i + 1}")
    for i, mth in enumerate((date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1))):
        run_period(env, "monthly", mth, inputs=[("E0007", "BONUS", dict(amount=12000, note="Annual performance bonus"))] if i == 2 else [], label=f"month {i + 1}")

    # --- payments, super and STP for part of the history; the rest is left for testers ---
    runs = db.query(__import__("accfino.modules.payroll.models.payroll", fromlist=["PayRun"]).PayRun).filter_by(org_id=org.id).order_by(__import__("accfino.modules.payroll.models.payroll", fromlist=["PayRun"]).PayRun.pay_date).all()
    fort = [r for r in runs if r.frequency == "fortnightly"]
    for r in fort[:5]:
        b = P.prepare(db, ctx, env.a, r.id)
        P.complete(db, ctx, env.a, b.id)
        P.reconcile(db, ctx, env.a, b.id)
    for r in fort[:4]:
        ids = [c.id for c in db.query(PaySuperContribution).filter_by(run_id=r.id, status="pending")]
        SF.mark_paid(db, ctx, env.a, ids, f"CH-{r.run_no}")
    for r in fort[:3]:
        ev = STP.prepare_pay_event(db, ctx, env.a, r.id)
        STP.mock_submit(db, ctx, env.a, ev.id)
    STP.prepare_pay_event(db, ctx, env.a, fort[5].id)
    db.commit()

    # --- the OPEN current period (21 Sep - 4 Oct) for testers: created, calculated, left in REVIEW ---
    employee(env, "E0014", "Isla", "Moore", dept="FIN", pos="EDGE: no bank account", salary=75000, start=date(2026, 9, 1), bank=False)
    employee(env, "E0015", "Jack", "Hill", dept="SAL", pos="EDGE: no TFN", salary=60000, start=date(2026, 9, 1), tfn=False)
    employee(env, "E0016", "Kira", "Stone", dept="OPS", pos="EDGE: no super fund", salary=65000, start=date(2026, 9, 1), funds=())
    employee(env, "E0017", "Leo", "Zero", dept="OPS", pos="EDGE: casual, no hours", etype="casual", hourly=30, freq="weekly", start=date(2026, 9, 1))
    ws = week_starts(13)[12]                                                                                    # week of 21 Sep
    timesheet(env, "E0004", ws, [8, 8, 8, 8, 8], ot=2, state="approved")
    timesheet(env, "E0005", ws, [6, 7, 6, 7, 6], state="submitted")
    timesheet(env, "E0004", ws + timedelta(days=7), [8, 8, 0, 0, 0], state="submitted")                          # week of 28 Sep
    leave_request(env, "E0001", "AL", date(2026, 10, 12), date(2026, 10, 16), note="Pending approval")
    leave_request(env, "E0003", "PL", date(2026, 10, 5), date(2026, 10, 6), note="Carer's leave - pending", hours=9.12)
    leave_request(env, "E0004", "CL", date(2026, 9, 29), date(2026, 9, 30), decide=False, note="Rejected: insufficient notice (demo)")
    db.commit()
    from accfino.modules.payroll.services import config as C
    p = C.period_containing(env.cals["fortnightly"], date(2026, 9, 21))
    cur = R.create_run(db, ctx, env.a, dict(calendar_id=env.cals["fortnightly"].id, period_start=p["period_start"], period_end=p["period_end"], pay_date=p["pay_date"],
                                           employee_ids=[e.id for n, e in env.emps.items() if e.pay_frequency == "fortnightly" and e.status == "active"]))
    R.calculate(db, ctx, env.a, cur.id)
    db.commit()
    return org


def load_outback(db, spec, log=print):
    from accfino.modules.payroll.models.payroll import PayRun
    from accfino.modules.payroll.services import payments as P, payruns as R
    org, ctx = make_org(db, spec)
    env = Env(db, org, ctx, spec["domain"])
    add_logins(db, env)
    setup_org(env, "outback")
    employee(env, "E0001", "Mason", "Clarke", dept="OPS", pos="Store Manager", salary=76000)
    ruby = employee(env, "E0002", "Ruby", "Evans", dept="SAL", pos="Sales Lead", salary=64000, tax=dict(has_study_loan=True, study_loan_type="HELP"))
    employee(env, "E0003", "Jackson", "Hall", dept="OPS", pos="Casual", etype="casual", hourly=31.0, freq="weekly")
    employee(env, "E0004", "Lily", "Wood", dept="FIN", pos="Bookkeeper", etype="part_time", salary=48000, hpw=24)
    employee(env, "E0005", "Oscar", "Bell", dept="EXE", pos="General Manager (high earner)", salary=210000, tax=dict(has_study_loan=True, study_loan_type="HELP"), funds=(("HostPlus", 100),))
    employee(env, "E0006", "Chloe", "Ward", dept="SAL", pos="Sales Rep", salary=59000, funds=(("Aware Super", 100),))
    employee(env, "E0007", "Henry", "Cox", dept="OPS", pos="Casual", etype="casual", hourly=29.0, freq="weekly")
    employee(env, "E0008", "Ava", "Reid", dept="OPS", pos="EDGE: casual, zero earnings", etype="casual", hourly=28.0, freq="weekly")
    assign(env, "E0006", "SSPCT", rate=10)
    for n, c, h in (("E0001", "AL", 70), ("E0002", "AL", 50), ("E0004", "AL", 30), ("E0005", "AL", 140), ("E0006", "AL", 40)):
        opening_leave(env, n, c, h)
    db.commit()
    for i, ws in enumerate(week_starts(12)):
        timesheet(env, "E0003", ws, [8, 8, 7, 8, 8], ot=2 if i % 6 == 1 else 0)
        timesheet(env, "E0007", ws, [5, 5, 5, 5, 0])
    for i, st in enumerate(fortnight_starts(6)):
        run_period(env, "fortnightly", st, label=f"fortnight {i + 1}")
        if i == 2:                                                  # a CORRECTION: Ruby's backdated pay rise -> reverse the run and issue a corrected one
            run3 = db.query(PayRun).filter_by(org_id=org.id, run_type="regular").order_by(PayRun.id.desc()).first()
            R.reverse(db, ctx, env.a, run3.id, "Backdated pay rise for Ruby Evans was missed", date(2026, 8, 20))
            ruby.annual_salary = 66000
            db.commit()
            run_period(env, "fortnightly", st, label="corrected fortnight 3")
    for i, ws in enumerate(week_starts(12)):
        run_period(env, "weekly", ws, label=f"week {i + 1}")
    for r in db.query(PayRun).filter_by(org_id=org.id, run_type="regular", frequency="fortnightly").order_by(PayRun.pay_date).all()[:3]:
        if not r.reversed_by_run_id:
            P.complete(db, ctx, env.a, P.prepare(db, ctx, env.a, r.id).id)
    db.commit()
    return org


def load(db, log=print) -> dict:
    existing = {o.name for o in demo_orgs(db)}
    done = []
    for spec, fn in ((ORGS[0], load_harbour), (ORGS[1], load_outback)):
        if spec["name"] in existing:
            log(f"  {spec['name']}: already present, skipped (use --reload for a clean copy)")
            continue
        log(f"  building {spec['name']} ...")
        fn(db, spec, log)
        done.append(spec["name"])
        db.commit()
    return {"created": done, "orgs": status(db)}


# ----------------------------------------------------------------------------------------------------------------------- CLI --
def _session(sqlite_path=None):
    if sqlite_path:
        os.environ.setdefault("DATABASE_URL", "postgresql://offline:offline@localhost/none")
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from accfino.shared.contracts import registry
        registry.load_all(); registry.import_all_models()
        import accfino.core.subscription.models, accfino.core.tenancy.models  # noqa: F401
        from accfino.core import models as m
        eng = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})   # NOT StaticPool: the platform force-delete inspects the schema on a second pooled connection

        @event.listens_for(eng, "connect")
        def _c(dbapi, _):
            dbapi.isolation_level = None
            dbapi.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(eng, "begin")
        def _b(conn):
            conn.exec_driver_sql("BEGIN")
        m.Base.metadata.create_all(eng)
        return sessionmaker(bind=eng, autoflush=False)()
    from accfino.shared.db.database import SessionLocal
    return SessionLocal()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    for f in ("status", "load", "reset", "reload"):
        g.add_argument(f"--{f}", action="store_true")
    ap.add_argument("--sqlite", help="build/use an offline SQLite database file instead of DATABASE_URL")
    ap.add_argument("--yes", action="store_true", help="skip the production safety prompt")
    a = ap.parse_args(argv)
    db = _session(a.sqlite)
    if not a.sqlite and not a.yes and a.status is False:
        url = os.environ.get("DATABASE_URL", "")
        if input(f"This changes the database at {url.split('@')[-1] or '(default)'}. Demo organisations are named '(DEMO)' and only they are touched. Type YES to continue: ") != "YES":
            return 1
    try:
        if a.status:
            print(status(db) or "no demo organisations")
        if a.reset or a.reload:
            print("Resetting demo data ..."); print(f"  {reset(db)} organisation(s) removed")
        if a.load or a.reload:
            print("Loading demo data ..."); print(load(db))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
