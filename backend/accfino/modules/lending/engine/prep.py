"""Preparation between the classifier and the metrics: do not let the applicant's OWN money count as income.

The shared classifier labels any "TRANSFER FROM ..." credit as Income. For lending that overstates affordability, so credits shaped like transfers between the applicant's own accounts are treated as transfers
(not income) and listed for the agent to confirm. Salary, wages, benefits, dividends and rent are never reclassified, whatever the wording."""
import re
from typing import Dict, List, Tuple

_TRANSFER_IN = re.compile(r"\b(?:(?:INTERNET|ONLINE|MOBILE|FAST|OSKO|FUND|BPAY)\s+)?(?:TRANSFER|TFR|TRF)\s+(?:FROM|IN|CREDIT)\b|\bFROM\s+(?:SAVINGS|OFFSET|CHEQUE|MORTGAGE|REDRAW|CREDIT CARD)\b")
_REAL_INCOME = re.compile(r"SALARY|WAGES?\b|PAYROLL|\bPAY\b|CENTRELINK|SERVICES AUSTRALIA|DIVIDEND|\bRENT\b|PENSION|ATO\b|TAX REFUND|DISTRIBUTION")


def is_own_transfer_in(description: str) -> bool:
    d = str(description or "").upper()
    return bool(_TRANSFER_IN.search(d)) and not _REAL_INCOME.search(d)


def reclassify_transfers(lines: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """-> (lines, reviewed). Reclassified credits become Fund Transfer / transfers / not income and carry `reclassified` text; `reviewed` lists them for the agent."""
    out, reviewed = [], []
    for l in lines:
        credit = float(l.get("credit") or 0) > 0 and not l.get("is_debit")
        if credit and (l.get("is_income") or l.get("category") == "Income") and is_own_transfer_in(l.get("description")):
            n = dict(l, category="Fund Transfer", hem_group="transfers", is_income=False, exp_type="D", in_or_out="O", reclassified="Treated as a transfer between the applicant's own accounts, not income. Confirm with the applicant.")
            out.append(n)
            reviewed.append(dict(date=l.get("date"), description=str(l.get("description", ""))[:80], amount=round(float(l.get("credit") or 0), 2), reason=n["reclassified"]))
        else:
            out.append(l)
    return out, reviewed
