import pandas as pd
import re, json, hashlib
from pathlib import Path
import requests

from db_app.database import SessionLocal
from db_app.models.rdr_rule import RDRRule
from main_app.backend.utils.groq_pool import resolve_groq_key, record_key_outcome, count_available_keys

CSV_PATH = "TNZ.csv"

# --- Groq config ---------------------------------------------------------
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Used only if a pool key has no per-key model override set. See
# GroqKeyPool.model (per-key override) managed via the /groq-pool admin
# API/UI -- most keys should just use this platform default instead of
# setting their own.
DEFAULT_MODEL = "openai/gpt-oss-20b"

# How many *different* pool keys to try before giving up on a single
# transaction. Each retry uses resolve_groq_key() again, which picks
# whichever healthy key is currently least-recently-used -- so a retry
# naturally lands on a different key rather than hammering the same
# rate-limited one.
MAX_KEY_ATTEMPTS = 3

ALLOWED = {"Inventory", "Fixed_Asset", "Transfer", "Revenue", "Expense", "Other"}


def clean_text(x) -> str:
    s = str(x or "")
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def safe_float(x, default=0.0) -> float:
    try:
        if pd.isna(x):
            return default
        return float(str(x).replace(",", "").strip())
    except Exception:
        return default

def pick_col(df, candidates):
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    return None


class NoGroqKeyAvailable(Exception):
    """Raised when every key in the pool is currently disabled or cooling
    down (or the pool is empty). Callers can catch this to fall back to
    RDR-only / keyword classification instead of hard-failing."""


def groq_chat_json(db, system: str, user: str) -> dict:
    """Calls Groq using a key from the pool, automatically retrying with a
    different pool key if one fails (rate limit, timeout, etc.) -- rather
    than a single hardcoded GROQ_API_KEY that has nowhere to fall back to.
    """
    last_error = None

    for attempt in range(MAX_KEY_ATTEMPTS):
        resolved = resolve_groq_key(db)
        if not resolved["groq_key"]:
            if attempt == 0:
                raise NoGroqKeyAvailable(
                    "No Groq key available -- the pool is empty, or every key is "
                    "currently disabled/cooling down. Add/enable a key via the "
                    "/groq-pool admin API."
                )
            break  # ran out of healthy keys mid-retry; surface the last real error instead

        model = resolved["model"] or DEFAULT_MODEL
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = requests.post(
                GROQ_API_URL,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {resolved['groq_key']}",
                },
                timeout=60,
            )
            resp.raise_for_status()
            record_key_outcome(db, resolved["pool_id"], success=True)
            return resp.json()
        except requests.exceptions.RequestException as e:
            record_key_outcome(db, resolved["pool_id"], success=False)
            last_error = e
            print(f"  [groq] key {resolved['key_preview']} failed ({type(e).__name__}), trying next key in pool...")
            continue

    if last_error:
        raise last_error
    raise NoGroqKeyAvailable("All pool keys exhausted without a successful response.")


SYSTEM = """
You are a strict bank-transaction classifier.

Return ONLY one label from this exact set:
- Inventory
- Fixed_Asset
- Transfer
- Revenue
- Expense
- Other

Definitions:
- Revenue: money coming in from sales/services, customer payments, income.
- Transfer: moving money between own accounts, internal transfers, savings, card payments to self.
- Inventory: purchases of stock/materials intended to be sold later or used to make items for sale (wholesale, bulk, cartons, supplier invoices).
- Fixed_Asset: long-term equipment/tools/vehicles/computers/furniture/machinery used over time.
- Expense: operating costs that are not inventory and not fixed assets.
- Other: use only if it doesn't fit above or is unclear.

Hard constraints:
- Output MUST be JSON ONLY like: {"label":"Expense"}
- The label value MUST be exactly one of: Inventory, Fixed_Asset, Transfer, Revenue, Expense, Other
- No extra keys. No extra text.
""".strip()

def cache_key(desc: str, debit: float, credit: float) -> str:
    raw = f"{desc.lower()}|{debit:.2f}|{credit:.2f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()

# ---------------------------
# Ripple Down Rules (RDR) layer -- now Postgres-backed (db_app.models.RDRRule)
# instead of data/rdr_rules.json. Managed via /rdr/rules in the app, or
# directly in the rdr_rules table. Run db_app/migrate_rdr_to_db.py once to
# import any existing rdr_rules.json.
# ---------------------------
def load_rdr_rules(db) -> list[dict]:
    rules = db.query(RDRRule).order_by(RDRRule.priority.desc()).all()
    return [r.to_dict() for r in rules]

def rdr_apply(rules: list[dict], desc: str, debit: float, credit: float):
    d = (desc or "").lower()

    for rule in rules:
        cond = rule.get("if", {}) or {}

        if "debit_gt" in cond and not (debit > float(cond["debit_gt"])):
            continue
        if "credit_gt" in cond and not (credit > float(cond["credit_gt"])):
            continue

        if "contains_any" in cond:
            if not any(str(k).lower() in d for k in cond["contains_any"]):
                continue

        if "regex_any" in cond:
            if not any(re.search(rx, d) for rx in cond["regex_any"]):
                continue

        return rule.get("then")

    return None


def extract_label_from_content(content: str) -> str:
    content = (content or "").strip()
    try:
        data = json.loads(content)
        return (data.get("label") or "").strip()
    except Exception:
        m = re.search(r'"label"\s*:\s*"([^"]+)"', content)
        return (m.group(1).strip() if m else "")

def classify_llm(db, desc: str, debit: float, credit: float) -> str:
    user = f"""Transaction:
Description: {desc}
Debit (money out): {debit}
Credit (money in): {credit}
Return JSON now."""
    resp = groq_chat_json(db, SYSTEM, user)
    content = (resp.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
    label = extract_label_from_content(content)

    if label not in ALLOWED:
        label = "Other"
    return label

def direction_guard(label: str, debit: float, credit: float) -> str:
    if debit > 0 and credit <= 0 and label == "Revenue":
        return "Other"
    if credit > 0 and debit <= 0 and label == "Expense":
        return "Other"
    return label

def classify(db, rules: list[dict], desc: str, debit: float, credit: float) -> str:
    # 1) RDR override first (fast + consistent, no API call needed)
    forced = rdr_apply(rules, desc, debit, credit)
    if forced in ALLOWED:
        return forced

    # 2) LLM fallback (Groq, via key pool)
    try:
        label = classify_llm(db, desc, debit, credit)
    except NoGroqKeyAvailable as e:
        print(f"  WARNING: {e} -- classifying as 'Other' for this row.")
        return "Other"

    # 3) Guards
    label = direction_guard(label, debit, credit)
    return label

def main():
    df = pd.read_csv(CSV_PATH).dropna(how="all")

    db = SessionLocal()
    rules = load_rdr_rules(db)
    print(f"Loaded {len(rules)} RDR rules from Postgres")
    print(f"{count_available_keys(db)} Groq key(s) currently healthy in the pool")

    col_desc = pick_col(df, ["Description", "Narration", "Details", "Transaction Details", "Merchant", "Memo"])
    col_debit = pick_col(df, ["Debit", "Out", "Money Out", "Spent", "Withdrawal", "Amount"])
    col_credit = pick_col(df, ["Credit", "In", "Money In", "Received", "Deposit"])
    col_date = pick_col(df, ["Date", "Transaction Date", "Posted Date"])

    if not col_desc:
        print("ERROR: Could not find a description-like column. Your columns are:")
        print(list(df.columns))
        db.close()
        return

    cache = {}
    printed = 0

    try:
        for r in df.itertuples(index=False):
            desc = clean_text(getattr(r, col_desc, ""))
            if not desc:
                continue

            debit = safe_float(getattr(r, col_debit, 0.0)) if col_debit else 0.0
            credit = safe_float(getattr(r, col_credit, 0.0)) if col_credit else 0.0
            date = clean_text(getattr(r, col_date, "")) if col_date else ""

            k = cache_key(desc, debit, credit)
            if k in cache:
                label = cache[k]
            else:
                label = classify(db, rules, desc, debit, credit)
                cache[k] = label

            printed += 1
            print(f"{date}\t{desc}\tDebit={debit}\tCredit={credit}\t->\t{label}")

        if printed == 0:
            print("No rows printed (empty file or empty description column).")
    finally:
        db.close()

if __name__ == "__main__":
    main()
