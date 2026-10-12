"""Risk and anomaly rules (pure). Alerts mean 'unusual - please review'. They never say fraud, never block anything and never change records."""
import datetime as dt
import statistics
from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from .money import D, pct, q2, s, ZERO
from .recurring import normalise_key

RULESET_VERSION = "risk-1.0"
DEFAULTS = dict(dup_window_days=3, dup_min_amount=100, round_min_amount=5000, round_multiple=1000, new_payee_min_amount=5000, new_payee_lookback_days=180,
                deviation_z=3, deviation_min_months=4, deviation_min_abs=500, recurring_change_pct=20, budget_overrun_pct=10, budget_overrun_min_abs=500,
                forecast_drop_pct=25, high_amount=25000)
RULES = {
    "RISK-DUP": "Possible duplicate payment", "RISK-ROUND": "Round-sum payment", "RISK-NEWPAYEE": "Large payment to a new payee", "RISK-DEVIATION": "Expense unusually different from its history",
    "RISK-RECURRING": "Recurring payment changed", "RISK-BALANCE": "Unusual account balance", "RISK-BUDGET": "Budget overrun", "RISK-FORECAST": "Forecast minimum balance worsened",
}


def _alert(rule, severity, ref, title, reason, evidence, baseline, dedupe, amount=None, date=None):
    return dict(rule=rule, rule_version=RULESET_VERSION, severity=severity, ref=ref, title=title, reason=reason, evidence=evidence, baseline=baseline, dedupe_key=dedupe,
                amount=s(amount) if amount is not None else None, event_date=date.isoformat() if date else None)


def _sev(amount, c, base="medium"):
    return "high" if D(amount) >= c["high_amount"] else base


def duplicates(payments: Sequence[dict], c: dict) -> List[dict]:
    """payments: outflows {id, date, contact, amount (positive), ref, label}. Same contact + same amount within N days, different record."""
    out, by = [], defaultdict(list)
    for p in payments:
        if D(p["amount"]) >= c["dup_min_amount"] and p.get("contact"):
            by[(p["contact"].strip().lower(), q2(p["amount"]))].append(p)
    for (cn, amt), items in sorted(by.items()):
        items = sorted(items, key=lambda p: (p["date"], str(p["id"])))
        for a, b in zip(items, items[1:]):
            if (b["date"] - a["date"]).days <= c["dup_window_days"]:
                out.append(_alert("RISK-DUP", _sev(amt, c), f"journal:{b['id']}", f"Possible duplicate payment to {b['contact']}",
                                  f"Two payments of {s(amt)} to {b['contact']} within {(b['date'] - a['date']).days} day(s).",
                                  dict(first=dict(id=a["id"], date=a["date"].isoformat(), ref=a.get("ref")), second=dict(id=b["id"], date=b["date"].isoformat(), ref=b.get("ref"))),
                                  dict(window_days=c["dup_window_days"]), f"dup:{a['id']}:{b['id']}", amt, b["date"]))
    return out


def round_sums(payments: Sequence[dict], c: dict, recurring_keys=()) -> List[dict]:
    out = []
    for p in payments:
        a = D(p["amount"])
        if a >= c["round_min_amount"] and a % D(c["round_multiple"]) == 0 and normalise_key(p.get("label", "")) not in recurring_keys:
            out.append(_alert("RISK-ROUND", "low", f"journal:{p['id']}", f"Round-sum payment of {s(a)}", f"{s(a)} is an exact multiple of {c['round_multiple']} and is not part of a recurring pattern.",
                              dict(id=p["id"], date=p["date"].isoformat(), contact=p.get("contact"), label=p.get("label")), dict(min_amount=c["round_min_amount"], multiple=c["round_multiple"]),
                              f"round:{p['id']}", a, p["date"]))
    return out


def new_payee(payments: Sequence[dict], history_contacts: set, c: dict) -> List[dict]:
    """history_contacts: lower-case contact names paid before the lookback window (so 'new' means never seen in prior history)."""
    out, seen = [], set()
    for p in sorted(payments, key=lambda p: (p["date"], str(p["id"]))):
        n = (p.get("contact") or "").strip().lower()
        if not n or n in history_contacts or n in seen:
            continue
        seen.add(n)
        if D(p["amount"]) >= c["new_payee_min_amount"]:
            out.append(_alert("RISK-NEWPAYEE", _sev(p["amount"], c, "medium"), f"journal:{p['id']}", f"Large payment to a new payee: {p['contact']}",
                              f"First payment to {p['contact']} in {c['new_payee_lookback_days']}+ days of history, for {s(p['amount'])}.",
                              dict(id=p["id"], date=p["date"].isoformat(), contact=p["contact"]), dict(lookback_days=c["new_payee_lookback_days"], min_amount=c["new_payee_min_amount"]),
                              f"newpayee:{n}:{p['date'].isoformat()}", p["amount"], p["date"]))
    return out


def deviations(monthly: Dict[str, Dict[str, Decimal]], names: Dict[str, str], current_month: str, c: dict) -> List[dict]:
    """monthly: {account_key: {YYYY-MM: amount}} expense accounts. Flags when the current month is >= z standard deviations from the prior months' mean AND moved by at least min_abs."""
    out = []
    for key, m in sorted(monthly.items()):
        prior = [D(v) for k, v in sorted(m.items()) if k < current_month]
        if len(prior) < c["deviation_min_months"] or current_month not in m:
            continue
        cur = D(m[current_month])
        mean = sum(prior, ZERO) / len(prior)
        sd = Decimal(str(statistics.pstdev([float(x) for x in prior])))
        diff = cur - mean
        if abs(diff) < c["deviation_min_abs"]:
            continue
        floor = max(sd, abs(mean) * Decimal("0.05"), Decimal("1"))
        z = (abs(diff) / floor).quantize(Decimal("0.1"))
        if z >= c["deviation_z"]:
            out.append(_alert("RISK-DEVIATION", "medium", f"account:{key}", f"{names.get(key, key)} is unusual this month",
                              f"{current_month}: {s(cur)} vs average {s(mean)} over {len(prior)} months ({'+' if diff > 0 else ''}{s(diff)}, {z} standard deviations).",
                              dict(month=current_month, amount=s(cur)), dict(mean=s(mean), stdev=s(sd), months=len(prior), z=str(z)), f"dev:{key}:{current_month}", abs(diff)))
    return out


def recurring_changes(series: Sequence[dict], c: dict) -> List[dict]:
    out = []
    for r in series:
        base, last = abs(D(r["monthly_amount"])), abs(D(r["latest_amount"]))
        if base == 0:
            continue
        ch = pct(last - base, base)
        if ch is not None and abs(ch) >= c["recurring_change_pct"]:
            out.append(_alert("RISK-RECURRING", "medium", f"recurring:{r['key']}", f"Recurring payment changed: {r['label']}", f"Latest {s(last)} vs usual {s(base)} ({ch}%).",
                              dict(latest=s(last), month=r["last_month"]), dict(usual=s(base), months_seen=r["months_seen"], cv=str(r["cv"])), f"recchg:{r['key']}:{r['last_month']}", abs(last - base)))
    return out


def balances(accounts: Sequence[dict], as_at: dt.date) -> List[dict]:
    """accounts: {id, code, name, type, class, balance} in the books' natural sign. Flags bank overdrafts and control accounts with the wrong sign."""
    out = []
    for a in accounts:
        b = D(a["balance"])
        if a["type"] == "bank" and b < 0:
            out.append(_alert("RISK-BALANCE", "high", f"account:{a['id']}", f"Bank account {a['code']} is overdrawn", f"{a['name']} balance is {s(b)}.", dict(balance=s(b), as_at=as_at.isoformat()), dict(expected="zero or positive"),
                              f"bal:{a['id']}:{as_at.isoformat()[:7]}", abs(b), as_at))
        elif a.get("system_key") == "ar_control" and b < 0 or a.get("system_key") == "ap_control" and b < 0:
            out.append(_alert("RISK-BALANCE", "medium", f"account:{a['id']}", f"{a['name']} has an unusual balance", f"Balance {s(b)} is the opposite sign to normal.", dict(balance=s(b), as_at=as_at.isoformat()),
                              dict(expected="normal sign"), f"bal:{a['id']}:{as_at.isoformat()[:7]}", abs(b), as_at))
    return out


def budget_overruns(rows: Sequence[dict], c: dict, scenario: str) -> List[dict]:
    """rows from budget.rows_vs_actual for the year to date. Only expense overruns (actual above budget by pct and min_abs)."""
    out = []
    for r in rows:
        if r["account_class"] != "expense" or r["budget"] <= 0:
            continue
        over = r["actual"] - r["budget"]
        if over >= c["budget_overrun_min_abs"] and pct(over, r["budget"]) >= c["budget_overrun_pct"]:
            out.append(_alert("RISK-BUDGET", "medium", f"account:{r['account_id']}", f"{r['name']} is over budget", f"Actual {s(r['actual'])} vs budget {s(r['budget'])} (+{pct(over, r['budget'])}%).",
                              dict(actual=s(r["actual"])), dict(budget=s(r["budget"]), scenario=scenario), f"bud:{r['account_id']}:{scenario}", over))
    return out


def forecast_movement(previous: Optional[dict], current: dict, c: dict) -> List[dict]:
    if not previous:
        return []
    p, n = D(previous["minimum"]), D(current["minimum"])
    drop = p - n
    base = max(abs(p), Decimal(1))
    if drop > 0 and pct(drop, base) >= c["forecast_drop_pct"] and drop >= c["deviation_min_abs"]:
        return [_alert("RISK-FORECAST", "high" if n < 0 else "medium", f"forecast:{current['snapshot_id']}", "Forecast minimum balance is lower than the previous forecast",
                       f"Lowest projected balance moved from {s(p)} to {s(n)} ({s(drop)} lower).", dict(minimum=s(n), snapshot=current["snapshot_id"]), dict(previous_minimum=s(p), previous_snapshot=previous["snapshot_id"]),
                       f"fc:{previous['snapshot_id']}:{current['snapshot_id']}", drop)]
    return []
