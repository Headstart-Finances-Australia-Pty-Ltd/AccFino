"""
AI assistance beyond bank-line coding. Three features, all ADVISORY - nothing here can post, approve, or change anything:

  1. journal_from_text   "Accrue $4,500 audit fees for December, reverse in January" -> a proposed journal that fills the editor. Accounts must be codes from the
                         organisation's own chart (anything else is discarded), the amounts are validated by the same preview engine as a hand-typed journal, and the
                         person still reviews and posts it themselves.
  2. review_draft        an approver's second opinion on a submitted draft: what it does, and anything that looks wrong. The deterministic checks (lock date, suspense,
                         control accounts, weekend, round numbers...) are always shown; the model adds a short plain-English read.
  3. explain_profit_loss "why did profit change?" The movements are computed by AccFino; the model only writes the commentary, and if it quotes ANY number that is not
                         in the data it was given, the commentary is withheld and only the computed table is shown.

Rules for all three: separate opt-in (org setting llm_assist, approvers turn it on, off by default); the model sees account codes/names and amounts but never contact
names; long digit runs and emails in free text are masked; 20 calls per organisation per hour; the model is the shared Groq pool via ai_coder.chat_backend.
"""
import json
import re
import time
from collections import defaultdict, deque
from decimal import Decimal

from accfino.core import models as m
from accfino.modules.accounting.models import ledger as lm
from accfino.modules.accounting.books.common import BooksError
from accfino.modules.accounting.ledger import ai_coder as AI
from accfino.modules.accounting.ledger import journal_tools as JT
from accfino.modules.accounting.ledger import service as L

Z = Decimal("0.00")
HOURLY_LIMIT = 20
_calls = defaultdict(deque)


def _limit(org_id):
    now, q = time.time(), _calls[org_id]
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= HOURLY_LIMIT:
        raise BooksError(f"AI assistance is limited to {HOURLY_LIMIT} requests per hour per organisation. Try again shortly", 429)
    q.append(now)


def _require_on(db, org):
    if not JT.get_settings(db, org).get("llm_assist"):
        raise BooksError("AI assistance is switched off for this organisation. An approver can turn it on under Ledger > AI assistant", 403)


def _ask(system, prompt):
    """One model call; failures become clean messages. Returns the raw reply text."""
    try:
        return AI.chat_backend(system, prompt)
    except AI.AiUnavailable as e:
        raise BooksError(f"AI is not available right now: {e}", 503)
    except Exception as e:
        raise BooksError(f"The AI service did not answer ({type(e).__name__}). Nothing was changed", 502)


def _json(reply):
    obj = AI._parse(reply)
    if obj is None:
        raise BooksError("The AI reply could not be understood, so nothing was proposed. Try rephrasing", 422)
    return obj


def _dec(v):
    try:
        d = Decimal(str(v).replace(",", "").replace("$", ""))
    except Exception:
        return None
    return d.quantize(Decimal("0.01")) if d.is_finite() else None


# ------------------------------------------------------------------------------------------------ 1. journal from text
JOURNAL_SYSTEM = ("You are a bookkeeping assistant for an Australian small business. Turn the user's description into ONE journal using ONLY the accounts listed. "
                  "Reply with JSON only: {\"narration\": \"...\", \"lines\": [{\"account_code\": \"...\", \"debit\": 0.00 or \"credit\": 0.00, \"description\": \"...\"}], "
                  "\"reverse_next_month\": true|false, \"notes\": \"one short sentence on any assumption\"}. Each line has EITHER debit OR credit. Total debits must equal total credits. "
                  "Do not include GST lines (the user chooses GST separately). If the request is not a journal, or you cannot map it to the listed accounts, reply {\"error\": \"reason\"}.")


def journal_from_text(db, org, text, on_date):
    _require_on(db, org)
    text = (text or "").strip()
    if len(text) < 8:
        raise BooksError("Describe the journal in a sentence, for example: Accrue $4,500 audit fees for December and reverse it in January")
    if len(text) > 1000:
        raise BooksError("Please keep the description under 1,000 characters")
    _limit(org.id)
    accs = [a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id, is_active=True).order_by(lm.LedgerAccount.code)
            if not a.system_key and not a.foreign_currency][:200]
    by_code = {a.code: a for a in accs}
    listing = "\n".join(f"{a.code} | {a.name} | {a.account_type}" for a in accs)
    reply = _ask(JOURNAL_SYSTEM, f"Today is {on_date.isoformat()}.\nDescription: \"{AI.mask(text)}\"\n\nAccounts:\n{listing}")
    obj = _json(reply)
    if obj.get("error"):
        raise BooksError(f"The assistant could not draft that: {str(obj['error'])[:200]}", 422)
    lines, problems = [], []
    for i, l in enumerate(obj.get("lines") or [], start=1):
        a = by_code.get(str(l.get("account_code", "")).strip())
        if a is None:
            problems.append(f"Line {i}: the assistant chose an account ('{l.get('account_code')}') that is not in your chart - line dropped")
            continue
        dr, cr = _dec(l.get("debit")) or Z, _dec(l.get("credit")) or Z
        if (dr > 0) == (cr > 0):
            problems.append(f"Line {i}: needs either a debit or a credit - line dropped")
            continue
        lines.append(dict(account_id=a.id, debit=str(dr) if dr > 0 else "", credit=str(cr) if cr > 0 else "", description=str(l.get("description") or "")[:200] or None))
    if len(lines) < 2:
        raise BooksError("The assistant did not produce a usable journal" + (f" ({problems[0]})" if problems else "") + ". Nothing was changed", 422)
    payload = dict(date=on_date.isoformat(), narration=str(obj.get("narration") or text)[:500], amounts_are="no_tax", lines=lines)
    pv = JT.preview(db, org, payload)
    return dict(proposal=payload, preview=pv, notes=str(obj.get("notes") or "")[:300], reverse_next_month=bool(obj.get("reverse_next_month")), dropped=problems,
                balanced=pv["balanced"], errors=pv["errors"], advisory="Generated by AI - check every account and amount before posting. Nothing has been saved.")


# ------------------------------------------------------------------------------------------------ 2. review a draft
REVIEW_SYSTEM = ("You review a proposed accounting journal for an Australian small business, as a careful second pair of eyes. Reply with JSON only: "
                 "{\"summary\": \"one sentence on what it does\", \"verdict\": \"ok\"|\"check\"|\"concern\", \"points\": [\"short point\", ...up to 5]}. "
                 "Only raise points you can support from the lines shown (wrong-looking account for the narration, an odd direction, a missing side, a suspicious round figure, "
                 "a date/period oddity). Do not invent facts. If nothing looks wrong, verdict is ok and points is empty.")


def review_draft(db, org, draft):
    _require_on(db, org)
    _limit(org.id)
    accs = {a.id: a for a in db.query(lm.LedgerAccount).filter_by(org_id=org.id)}
    lines = []
    for l in draft.lines or []:
        a = accs.get(int(l.get("account_id") or 0))
        if a is None:
            continue
        lines.append(f"{a.code} {a.name} | debit {l.get('debit') or 0} | credit {l.get('credit') or 0} | {AI.mask(l.get('description') or '')}")
    checks = []
    try:
        data = JT._draft_as_data(draft)
        pv = JT.preview(db, org, dict(date=data["date"], lines=data["lines"], amounts_are=data["amounts_are"], currency=data.get("currency"), exchange_rate=str(data["exchange_rate"]) if data.get("exchange_rate") else None))
        checks = list(pv["warnings"]) + [f"Error: {e}" for e in pv["errors"]]
    except BooksError as e:
        checks = [f"Error: {e}"]
    prompt = f"Date: {draft.journal_date}\nNarration: {AI.mask(draft.narration or '')}\nCurrency: {draft.currency or 'base'}\nLines:\n" + "\n".join(lines)
    obj = _json(_ask(REVIEW_SYSTEM, prompt))
    verdict = obj.get("verdict") if obj.get("verdict") in ("ok", "check", "concern") else "check"
    points = [re.sub(r"\s+", " ", str(p)).strip()[:200] for p in (obj.get("points") or [])[:5] if str(p).strip()]
    return dict(draft_id=draft.id, summary=str(obj.get("summary") or "")[:250], verdict=verdict, points=points, checks=checks,
                advisory="AI second opinion - advisory only. It cannot approve or change the journal.")


# ------------------------------------------------------------------------------------------------ 3. explain P&L
EXPLAIN_SYSTEM = ("You explain changes in a small business's profit and loss to its owner in plain English. Use ONLY the figures in the data provided and quote them exactly as "
                  "written there - do not round, convert, add up or invent any number. Reply with JSON only: {\"commentary\": \"3 to 5 short sentences\"}. Mention the biggest drivers "
                  "first. Do not give tax or investment advice.")
_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _norm_num(s):
    return s.replace(",", "").rstrip(".")


def numbers_in(text):
    return {_norm_num(x) for x in _NUM.findall(text or "")}


def explain_profit_loss(db, org, d1, d2, c1, c2):
    _require_on(db, org)
    if d1 > d2 or c1 > c2:
        raise BooksError("A 'from' date is after its 'to' date")
    a, b = L.profit_and_loss(db, org, d1, d2), L.profit_and_loss(db, org, c1, c2)

    def flat(pl):
        out = {}
        for sec, sign in (("income", 1), ("cost_of_sales", -1), ("expenses", -1), ("other_income", 1), ("other_expenses", -1)):
            for r in pl[sec]:
                out[(r["code"], r["name"])] = (Decimal(r["amount"]) if "amount" in r else Decimal(str(r.get("balance", "0")))) * sign
        return out
    fa, fb = flat(a), flat(b)
    moves = []
    for k in set(fa) | set(fb):
        cur, prev = fa.get(k, Z), fb.get(k, Z)
        if cur != prev:
            moves.append(dict(code=k[0], name=k[1], current=str(cur), previous=str(prev), change=str(cur - prev)))
    moves.sort(key=lambda r: abs(Decimal(r["change"])), reverse=True)
    moves = moves[:12]
    head = {k: (a[k], b[k]) for k in ("total_income", "gross_profit", "total_expenses", "net_profit")}
    table = dict(current_period=f"{d1} to {d2}", comparison_period=f"{c1} to {c2}", headline={k: dict(current=v[0], previous=v[1], change=str(Decimal(v[0]) - Decimal(v[1]))) for k, v in head.items()}, movements=moves)
    out = dict(**table, commentary=None, note=None)
    if not moves and a["net_profit"] == b["net_profit"]:
        out["note"] = "There is no difference between the two periods."
        return out
    _limit(org.id)
    prompt = "Data (sign: income and profit positive, costs shown as negative contributions):\n" + json.dumps(table, indent=1)
    obj = _json(_ask(EXPLAIN_SYSTEM, prompt))
    text = re.sub(r"\s+", " ", str(obj.get("commentary") or "")).strip()[:900]
    allowed = numbers_in(prompt) | {_norm_num(str(Decimal(x)).rstrip("0").rstrip(".")) for x in numbers_in(prompt) if x.replace(".", "", 1).isdigit()}
    extra = sorted(n for n in numbers_in(text) if n not in allowed and n not in {"1", "2", "3", "4", "5"})
    if not text:
        out["note"] = "The assistant returned no commentary."
    elif extra:
        out["note"] = f"AI commentary withheld: it quoted a figure that is not in your data ({', '.join(extra[:3])}). The computed table above is accurate."
    else:
        out["commentary"] = text
    out["advisory"] = "The figures are computed by AccFino. The commentary is AI-written and only allowed to repeat those figures."
    return out
