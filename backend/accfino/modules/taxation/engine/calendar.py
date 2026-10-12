"""Compliance-calendar engine: due dates (with the weekend / public-holiday roll-forward) and the obligations an organisation's tax profile implies.
Pure functions; the service layer persists the result idempotently (one row per source_key)."""
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set

from accfino.modules.taxation.engine.rules import TaxRuleSet, fbt_bounds, fbt_year_label, fy_bounds

QUARTERS = {"Q1": (7, 9), "Q2": (10, 12), "Q3": (1, 3), "Q4": (4, 6)}     # activity-statement quarters are calendar quarters, whatever the financial year


def is_business_day(d: date, holidays: Set[date]) -> bool:
    return d.weekday() < 5 and d not in holidays


def next_business_day(d: date, holidays: Iterable[date] = ()) -> date:
    hs = set(holidays)
    while not is_business_day(d, hs):
        d += timedelta(days=1)
    return d


def _md(mmdd: str, year: int) -> date:
    m, dd = mmdd.split("-")
    return date(year, int(m), int(dd))


def month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), (m % 12) + 1, 1)) - timedelta(days=1)


def holidays_from(rs: TaxRuleSet, extra: Iterable[str] = ()) -> Set[date]:
    out = {date.fromisoformat(x) for x in (rs.get("public_holidays_national") or [])}
    out |= {date.fromisoformat(x) for x in extra if x}
    return out


def _ob(kind, title, fy, start, end, due, holidays, *, agent_due=None, source_key, note="", authority="ATO"):
    due_adj = next_business_day(due, holidays)
    ag = next_business_day(agent_due, holidays) if agent_due else None
    return dict(kind=kind, title=title, fy=fy, period_start=start, period_end=end, due_date=due_adj, original_due_date=due, agent_due_date=ag,
                source_key=source_key, note=note, authority=authority)


def activity_statements(rs: TaxRuleSet, fy: str, profile: dict, holidays: Set[date], fy_end_month: int = 6) -> List[dict]:
    """BAS (GST registered) or IAS for each period of the income year. profile: bas_frequency monthly|quarterly|annual|none, gst_registered, uses_agent_program."""
    freq = profile.get("bas_frequency") or "quarterly"
    if freq == "none":
        return []
    kind = "bas" if profile.get("gst_registered", True) else "ias"
    name = "BAS" if kind == "bas" else "IAS"
    start, end = fy_bounds(fy, fy_end_month)
    out: List[dict] = []
    agent = bool(profile.get("uses_agent_program"))
    if freq == "monthly":
        y, m = start.year, start.month
        for _ in range(12):
            ps, pe = date(y, m, 1), month_end(y, m)
            ny, nm = (y + (m == 12), (m % 12) + 1)
            due = date(ny, nm, int(rs.req("bas.monthly_due_day")))
            out.append(_ob(kind, f"{name} {ps.strftime('%b %Y')}", fy, ps, pe, due, holidays, source_key=f"{kind}:{ps.isoformat()}:monthly"))
            y, m = ny, nm
    elif freq == "quarterly":
        qd, qa = rs.get("bas.quarterly_due"), rs.get("bas.quarterly_due_agent")
        y = start.year
        # calendar quarters touching the income year, in date order
        for q, (m1, m2) in sorted(QUARTERS.items(), key=lambda kv: (0 if kv[1][0] >= 7 else 1, kv[1][0])):
            qy = y if m1 >= 7 else y + 1
            ps, pe = date(qy, m1, 1), month_end(qy, m2)
            if pe < start or ps > end:
                continue
            dy = qy if (m2 < 12) else qy + 1
            due = _md(qd[q], dy)
            ad = _md(qa[q], dy) if agent and qa else None
            out.append(_ob(kind, f"{name} {q} {ps.strftime('%b')}-{pe.strftime('%b %Y')}", fy, ps, pe, due, holidays, agent_due=ad, source_key=f"{kind}:{ps.isoformat()}:quarterly"))
    elif freq == "annual":
        due = _md(rs.text("bas.annual_gst_due"), end.year if end.month < 10 else end.year + 1)
        out.append(_ob(kind, f"Annual GST return {fy}", fy, start, end, due, holidays, source_key=f"{kind}:{start.isoformat()}:annual",
                       note="Annual GST reporters: confirm the due date with the ATO (it can depend on whether a tax agent lodges)."))
    return out


def fbt_obligations(rs: TaxRuleSet, fy: str, holidays: Set[date], fy_end_month: int = 6) -> List[dict]:
    """The FBT return for the FBT year that ENDS inside this income year (31 March)."""
    start, end = fy_bounds(fy, fy_end_month)
    y = end.year
    label = f"FBT{y}"
    ps, pe = fbt_bounds(label)
    if not (start <= pe <= end):
        return []
    self_due, agent_due = _md(rs.text("fbt.return_due_self"), y), _md(rs.text("fbt.return_due_agent"), y)
    return [_ob("fbt_return", f"FBT return {label} ({ps.strftime('%d %b %Y')} - {pe.strftime('%d %b %Y')})", fy, ps, pe, self_due, holidays, agent_due=agent_due,
                source_key=f"fbt_return:{label}", note="FBT payment is due 21 May (agent lodgement does not extend payment).")]


def income_tax_return(rs: TaxRuleSet, fy: str, holidays: Set[date], fy_end_month: int = 6, profile: Optional[dict] = None) -> List[dict]:
    """Self-lodger date for everyone; for a COMPANY or SMSF that uses the tax-agent program the agent date (28 February for most small companies) is added. Other entity
    types' agent dates vary by client category, so none is invented: the user enters it on the obligation."""
    start, end = fy_bounds(fy, fy_end_month)
    yr = end.year if end.month < 10 else end.year + 1
    due = _md(rs.text("income_tax_return.self_lodge_due"), yr)
    agent = None
    if (profile or {}).get("uses_agent_program") and (profile or {}).get("entity_type") in ("company", "smsf") and rs.has_value("income_tax_return.agent_due_company"):
        agent = _md(rs.text("income_tax_return.agent_due_company"), yr + 1)
    note = ("Self-lodger due date. Most small companies lodging through a tax agent are due 28 February: the agent date is shown. Confirm the client's category in the agent lodgment program."
            if agent else "Self-lodger due date. If a registered tax agent lodges, enter the agent's lodgement-program date on this obligation.")
    return [_ob("income_tax_return", f"Income tax return {fy}", fy, start, end, due, holidays, agent_due=agent, source_key=f"income_tax_return:{fy}", note=note)]


def tpar(rs: TaxRuleSet, fy: str, holidays: Set[date], fy_end_month: int = 6) -> List[dict]:
    start, end = fy_bounds(fy, fy_end_month)
    due = _md(rs.text("bas.tpar_due"), end.year)
    return [_ob("tpar", f"Taxable payments annual report {fy}", fy, start, end, due, holidays, source_key=f"tpar:{fy}",
                note="Only for businesses that pay contractors in the relevant industries (building and construction, cleaning, couriers, IT, security etc.).")]


def div7a_obligations(rs: TaxRuleSet, fy: str, holidays: Set[date], fy_end_month: int = 6) -> List[dict]:
    start, end = fy_bounds(fy, fy_end_month)
    return [_ob("div7a_repayment", f"Division 7A minimum yearly repayments by {end.strftime('%d %b %Y')}", fy, start, end, end, holidays, source_key=f"div7a_repayment:{fy}",
                note="Repayments must be made by the end of the income year. Written loan agreements are due before the company's lodgement day.", authority="ATO")]


def generate(rs: TaxRuleSet, fy: str, profile: dict, holidays: Set[date], fy_end_month: int = 6) -> List[dict]:
    out = activity_statements(rs, fy, profile, holidays, fy_end_month)
    out += income_tax_return(rs, fy, holidays, fy_end_month, profile)
    if profile.get("fbt_registered"):
        out += fbt_obligations(rs, fy, holidays, fy_end_month)
    if profile.get("tpar_required"):
        out += tpar(rs, fy, holidays, fy_end_month)
    if profile.get("has_div7a_loans"):
        out += div7a_obligations(rs, fy, holidays, fy_end_month)
    if profile.get("payroll_tax_registered"):
        out += payroll_tax_returns(rs, fy, profile.get("state"), holidays, fy_end_month)
    return out


def payroll_tax_returns(rs: TaxRuleSet, fy: str, state: Optional[str], holidays: Set[date], fy_end_month: int = 6) -> List[dict]:
    """Monthly payroll tax returns for a REGISTERED employer: due `monthly_due_day` days after month end, rolled to the next business day using weekends, national holidays and the
    organisation's own state holidays. Some states fold June into an annual reconciliation with its own date: noted, not invented."""
    cfg = rs.get(f"payroll_tax.states.{state}") if state else None
    if not isinstance(cfg, dict) or not cfg.get("monthly_due_day"):
        return []
    start, end = fy_bounds(fy, fy_end_month)
    out, y, m = [], start.year, start.month
    for _ in range(12):
        ps, pe = date(y, m, 1), month_end(y, m)
        ny, nm = (y + (m == 12), (m % 12) + 1)
        due = date(ny, nm, int(cfg["monthly_due_day"]))
        exc = (cfg.get("due_exceptions") or {}).get(ps.strftime("%Y-%m"))               # a revenue office's published exception (e.g. NSW December return) beats the 7th
        if exc:
            due = date.fromisoformat(exc)
        out.append(_ob("payroll_tax", f"{state} payroll tax return {ps.strftime('%b %Y')}", fy, ps, pe, due, holidays, source_key=f"payroll_tax:{state}:{ps.isoformat()}",
                       note="Confirm the date with the state revenue office: the June return may be replaced by an annual reconciliation with a different date.", authority=f"{state} revenue office"))
        y, m = ny, nm
    return out
