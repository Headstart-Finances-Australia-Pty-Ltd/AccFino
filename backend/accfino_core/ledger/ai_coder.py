"""
ai_coder - the two extra sources of bank-coding suggestions, used only when the organisation's own rules and learned memory have nothing:

  RDR  the platform's Ripple-Down-Rule table (db_app.models.RDRRule: keywords / regex / direction / thresholds -> a GL account NAME). Deterministic, no network.
       The rule's account name is mapped onto THIS organisation's chart of accounts; a name that does not exist here is skipped. Confidence 85%.
  LLM  Groq, through the existing shared key pool (rotation, cooldown, per-key model). The model is shown ONLY this organisation's postable accounts
       and must answer with one of their codes; anything else is discarded. Confidence is capped at 80% whatever the model says.

Safety rules that hold for both:
  * they only ever PROPOSE a draft in the review queue - nothing here can post, and the reviewer always sees the reason;
  * neither can reach the bulk-approve threshold (85% / 80% is below the lowest choice, 90%) - an AI/RDR suggestion always needs an individual decision;
  * approving one teaches the organisation's own classifier, so the next occurrence is coded by the organisation's memory (and gets its own, higher, confidence);
  * the LLM is OFF by default: turning it on sends bank NARRATIONS (with long digit runs and emails masked) and the account list to Groq. It is an organisation setting.
"""
import json
import logging
import re
from decimal import Decimal

from sqlalchemy import inspect

from accfino_core import models as m
from accfino_core.books import banking as K

log = logging.getLogger("accfino.ai_coder")
RDR_CONFIDENCE = Decimal("0.85")
LLM_CAP = Decimal("0.80")
LLM_FLOOR = Decimal("0.50")            # below this the model is guessing; say nothing instead
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
MAX_ACCOUNTS_IN_PROMPT = 150

SYSTEM_PROMPT = ("You are a bookkeeping assistant for an Australian small business. Given ONE bank statement line, choose the single best account from the list you are given. "
                 "Reply with JSON only, no prose: {\"account_code\": \"<a code from the list, or null>\", \"confidence\": <number 0 to 1>, \"reason\": \"<at most 15 words>\"}. "
                 "If you are not reasonably sure, use null. Never invent a code that is not in the list.")


class AiUnavailable(Exception):
    """No key in the pool, or every key is cooling down / failing."""


def mask(text):
    """Remove what should not leave the system: long digit runs (account/card/phone numbers) and email addresses."""
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text or "")
    return re.sub(r"\d{5,}", "#", t)[:200]


# ---------------------------------------------------------------------------------------------------- RDR --
_table_cache = {}


def _has_rdr_table(db):
    bind = db.get_bind()
    key = str(bind.url)
    if key not in _table_cache:
        try:
            _table_cache[key] = inspect(bind).has_table("rdr_rules")
        except Exception:
            _table_cache[key] = False
    return _table_cache[key]


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _safe_re(pat, text):
    try:
        return bool(re.search(pat, text)) if pat and len(pat) <= 200 else False
    except re.error:
        return False


def _rule_matches(rule, text, amount):
    kws = rule.contains_any
    if not kws and not rule.regex_any:
        return False                                   # a rule with no text condition would match every line
    if kws and not any(k.lower() in text for k in kws):
        return False
    if rule.regex_any and not any(_safe_re(rx, text) for rx in rule.regex_any):
        return False
    if rule.debit_only and amount >= 0:
        return False
    if rule.credit_only and amount <= 0:
        return False
    if rule.debit_gt is not None and not (amount < 0 and abs(amount) > Decimal(str(rule.debit_gt))):
        return False
    if rule.credit_gt is not None and not (amount > 0 and amount > Decimal(str(rule.credit_gt))):
        return False
    return True


def _postable(db, org):
    return [a for a in db.query(m.LedgerAccount).filter_by(org_id=org.id, is_active=True).order_by(m.LedgerAccount.code)
            if not a.system_key and a.account_type not in ("bank", "credit_card")]


def _direction_ok(acc, amount):
    return acc.account_class != "revenue" if amount < 0 else acc.account_class != "expense"


def _coding(acc, tax, source, why, confidence):
    return dict(account_id=acc.id, account_code=acc.code, account_name=acc.name, tax_code_id=tax.id if tax else None, tax_code=tax.code if tax else None,
                contact_name=None, description=None, source=source, why=why, confidence=confidence)


def rdr_suggest(db, org, description, amount):
    """First matching platform RDR rule whose account exists in this organisation's chart."""
    if not _has_rdr_table(db):
        return None
    from db_app.models.rdr_rule import RDRRule
    amt = Decimal(str(amount))
    text = _norm(description)
    if not text:
        return None
    by_name = {}
    for a in _postable(db, org):
        by_name.setdefault(_norm(a.name), a)
        by_name.setdefault(_norm(f"{a.code} {a.name}"), a)
    taxes = {_norm(t.name): t for t in db.query(m.TaxCode).filter_by(org_id=org.id)} | {_norm(t.code): t for t in db.query(m.TaxCode).filter_by(org_id=org.id)}
    for rule in db.query(RDRRule).order_by(RDRRule.priority.desc(), RDRRule.id):
        if not _rule_matches(rule, text, amt):
            continue
        acc = by_name.get(_norm(rule.then))
        if acc is None or not _direction_ok(acc, amt):
            continue
        tax = taxes.get(_norm(rule.then_gst_category)) if rule.then_gst_category else None
        return _coding(acc, tax, "rdr", f"Platform rule '{rule.name or rule.id}'", RDR_CONFIDENCE)
    return None


# ---------------------------------------------------------------------------------------------------- LLM --
def _default_chat(system, prompt):
    """One chat completion through the shared Groq key pool. Its own DB session: the pool commits key health as it goes and must not commit the caller's work."""
    import requests
    from db_app.database import SessionLocal
    from main_app.backend.utils.groq_pool import record_key_outcome, resolve_groq_key
    db = SessionLocal()
    try:
        last = None
        for _ in range(3):
            resolved = resolve_groq_key(db)
            if not resolved["groq_key"]:
                raise AiUnavailable("No Groq key is available - the pool is empty or every key is disabled or cooling down")
            payload = {"model": resolved["model"] or DEFAULT_MODEL, "temperature": 0, "max_tokens": 300,
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            try:
                r = requests.post(GROQ_URL, json=payload, timeout=20, headers={"Content-Type": "application/json", "Authorization": f"Bearer {resolved['groq_key']}"})
                r.raise_for_status()
                record_key_outcome(db, resolved["pool_id"], success=True)
                return ((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            except requests.exceptions.RequestException as e:
                record_key_outcome(db, resolved["pool_id"], success=False)
                last = e
        raise AiUnavailable(f"Groq did not answer: {type(last).__name__}")
    finally:
        db.close()


chat_backend = _default_chat            # replaced in tests; the model call is the only thing that ever leaves the system


def new_state(max_calls=25):
    return dict(calls=0, max_calls=max_calls, cache={}, unavailable=False, unavailable_reason=None, accounts={})


def _candidates(db, org, amount, state):
    d = "out" if amount < 0 else "in"
    if d not in state["accounts"]:
        state["accounts"][d] = [a for a in _postable(db, org) if _direction_ok(a, amount)][:MAX_ACCOUNTS_IN_PROMPT]
    return state["accounts"][d]


def _parse(reply):
    """The first complete JSON object in the reply (models sometimes wrap it in a code fence or reasoning text). Nested objects and arrays are handled: the
    OUTERMOST object that starts first wins, not an inner one."""
    if not reply:
        return None
    text = re.sub(r"<think>.*?</think>", "", reply, flags=re.S)
    dec, i = json.JSONDecoder(), text.find("{")
    while i != -1:
        try:
            obj, _end = dec.raw_decode(text, i)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


def llm_suggest(db, org, description, amount, state):
    amt = Decimal(str(amount))
    key = (K.merchant_key(description) or _norm(description), "out" if amt < 0 else "in")
    if key in state["cache"]:
        return state["cache"][key]                         # same merchant seen again in this run: no second call
    if state["unavailable"] or state["calls"] >= state["max_calls"]:
        return None
    cands = _candidates(db, org, amt, state)
    if not cands:
        return None
    by_code = {a.code: a for a in cands}
    lines = "\n".join(f"{a.code} | {a.name} | {a.account_type}" for a in cands)
    prompt = (f"Bank line: \"{mask(description)}\"\nDirection: {'money going OUT (a payment)' if amt < 0 else 'money coming IN (a receipt)'}\n"
              f"Approximate amount (AUD): {abs(amt).quantize(Decimal('1'))}\n\nAccounts:\n{lines}")
    state["calls"] += 1
    try:
        reply = chat_backend(SYSTEM_PROMPT, prompt)
    except AiUnavailable as e:
        state["unavailable"], state["unavailable_reason"] = True, str(e)
        return None
    except Exception as e:                                 # a network or parsing failure must never break suggestion generation
        log.warning("llm suggestion failed: %s", e)
        return None
    obj = _parse(reply)
    result = None
    if obj and obj.get("account_code") not in (None, "", "null"):
        acc = by_code.get(str(obj["account_code"]).strip())
        try:
            conf = Decimal(str(obj.get("confidence", 0)))
        except Exception:
            conf = Decimal(0)
        conf = max(Decimal(0), min(conf, Decimal(1)))
        if acc is not None and conf >= LLM_FLOOR:           # a code that is not in this organisation's list is discarded, never trusted
            reason = re.sub(r"\s+", " ", str(obj.get("reason") or "")).strip()[:120]
            result = _coding(acc, None, "llm", f"AI suggestion{': ' + reason if reason else ''}", min(conf, LLM_CAP))
    state["cache"][key] = result
    return result
