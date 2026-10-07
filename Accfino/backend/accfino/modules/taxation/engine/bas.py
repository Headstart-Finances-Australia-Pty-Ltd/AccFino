"""BAS / IAS label engine. Takes the figures the ledger and payroll already produce and arranges them on the activity-statement labels,
with the source of every number. Pure functions. The ledger remains the only source of financial data: nothing here recomputes GST."""
from decimal import ROUND_DOWN, Decimal
from typing import Dict, Optional

from accfino.modules.taxation.engine.money import ZERO, D, q2, whole
from accfino.modules.taxation.engine.rules import TaxRuleSet

GST_LABELS = ("G1", "G2", "G3", "G10", "G11", "1A", "1B")
# The order labels appear on the ATO form. PostgreSQL stores JSON as JSONB, which does NOT keep key order, so every consumer (screen, CSV, workpaper) must order by this list,
# never by the dict's own order.
LABEL_ORDER = ("G1", "G2", "G3", "G10", "G11", "1A", "1B", "W1", "W2", "W3", "W4", "W5", "4", "T1", "T2", "T7", "T11", "5A", "F1", "6A", "8A", "8B", "9")


def ordered_labels(final: dict) -> list:
    """Label keys in form order; any unknown key goes last (alphabetical) so nothing is ever dropped."""
    known = [k for k in LABEL_ORDER if k in final]
    return known + sorted(k for k in final if k not in LABEL_ORDER)
KINDS = ("source", "calculated", "user_entered", "assumption", "estimate")


def _lab(value, kind, source, note="") -> dict:
    return dict(value=str(q2(value)), kind=kind, source=source, note=note)


def build_labels(rs: TaxRuleSet, *, kind: str, gst: Optional[dict], payg: Optional[dict], profile: dict, instalment_applies: bool = True,
                 instalment_income: Optional[Decimal] = None) -> dict:
    """kind 'bas' (GST registered) or 'ias'. gst = accounting GST summary fields ({'G1': '19250.00', ...}); payg = {'W1': .., 'W2': ..}."""
    labels: Dict[str, dict] = {}
    notes = []
    if kind == "bas":
        f = (gst or {}).get("fields", {})
        for lb in GST_LABELS:
            if lb in f or lb in ("G1", "G10", "G11", "1A", "1B"):
                labels[lb] = _lab(D(f.get(lb)), "source", "Ledger GST report (journal lines by tax code)")
    pg = payg or {}
    w1, w2 = D(pg.get("W1")), D(pg.get("W2"))
    w3, w4 = D(pg.get("W3")), D(pg.get("W4"))
    if w1 or w2 or w3 or w4 or pg.get("has_payroll"):
        labels["W1"] = _lab(w1, "source", "Payroll journals in the ledger (wages expense)")
        labels["W2"] = _lab(w2, "source", "Payroll journals in the ledger (credits to PAYG withholding payable)")
        labels["W3"] = _lab(w3, "user_entered", "Not held in AccFino: enter if you withhold from other payments")
        labels["W4"] = _lab(w4, "user_entered", "Not held in AccFino: enter if you withhold where no ABN is quoted")
        labels["W5"] = _lab(w2 + w3 + w4, "calculated", "W2 + W3 + W4")
        labels["4"] = _lab(w2 + w3 + w4, "calculated", "= W5")
    # PAYG instalment
    method = (profile.get("payg_instalment_method") or "none")
    inst = ZERO
    if instalment_applies and method == "amount" and profile.get("payg_instalment_amount") not in (None, ""):
        inst = D(profile["payg_instalment_amount"])
        labels["T7"] = _lab(inst, "user_entered", "Amount notified by the ATO (tax profile)")
        labels["5A"] = _lab(inst, "calculated", "= T7")
    elif instalment_applies and method == "rate" and profile.get("payg_instalment_rate") not in (None, ""):
        rate = D(profile["payg_instalment_rate"])
        base = instalment_income if instalment_income is not None else ZERO
        labels["T1"] = _lab(base, "estimate", "Sales excluding GST from the ledger (G1 - 1A). Instalment income may include other ordinary income not in this figure: review.")
        labels["T2"] = _lab(rate, "user_entered", "Rate notified by the ATO (tax profile), % of instalment income")
        inst = (base * rate / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_DOWN)           # ATO worked example: 341.70 is entered as 341 at T11 and 5A (cents ignored)
        labels["T11"] = _lab(inst, "calculated", "T1 x T2, cents ignored (as in the ATO's example)")
        labels["5A"] = _lab(inst, "calculated", "= T11")
    elif instalment_applies and method in ("amount", "rate"):
        labels["5A"] = _lab(ZERO, "assumption", "Instalment method selected but the amount/rate is not entered in the tax profile")
    # FBT instalment (user entered; AccFino does not estimate it)
    f1 = D(profile.get("fbt_instalment_amount")) if (instalment_applies and profile.get("fbt_registered")) else ZERO
    if f1:
        labels["F1"] = _lab(f1, "user_entered", "FBT instalment notified by the ATO (tax profile)")
        labels["6A"] = _lab(f1, "calculated", "= F1")
    owe = D(labels.get("1A", {}).get("value")) + D(labels.get("4", {}).get("value")) + inst + f1
    credit = D(labels.get("1B", {}).get("value"))
    labels["8A"] = _lab(owe, "calculated", "1A + 4 + 5A + 6A")
    labels["8B"] = _lab(credit, "calculated", "1B")
    labels["9"] = _lab(owe - credit, "calculated", "8A - 8B (positive = you pay the ATO; negative = refund)")
    return labels


def apply_overrides(labels: dict, overrides: dict) -> dict:
    """Final label values after reviewer overrides ({label: {'value': '12.00', 'reason': ...}}). Summary labels are re-derived so totals stay consistent."""
    final = {k: dict(v) for k, v in labels.items()}
    for lb, ov in (overrides or {}).items():
        if lb in ("8A", "8B", "9", "W5", "4"):
            continue                                            # derived: override the inputs instead
        cur = final.get(lb, dict(value="0.00", kind="user_entered", source="", note=""))
        final[lb] = dict(cur, value=str(q2(ov["value"])), kind="user_entered", source=f"Override: {ov.get('reason', '')}", note=cur.get("source", ""))
    w2, w3, w4 = (D(final.get(k, {}).get("value")) for k in ("W2", "W3", "W4"))
    if "W2" in final or "W3" in final or "W4" in final:
        final["W5"] = _lab(w2 + w3 + w4, "calculated", "W2 + W3 + W4")
        final["4"] = _lab(w2 + w3 + w4, "calculated", "= W5")
    owe = sum((D(final.get(k, {}).get("value")) for k in ("1A", "4", "5A", "6A")), ZERO)
    credit = D(final.get("1B", {}).get("value"))
    final["8A"], final["8B"], final["9"] = _lab(owe, "calculated", "1A + 4 + 5A + 6A"), _lab(credit, "calculated", "1B"), _lab(owe - credit, "calculated", "8A - 8B")
    return final


FLOOR_LABELS = ("T11", "5A")                    # instalments: the ATO's example ignores cents (341.70 -> 341)


def lodgement_figures(final: dict) -> dict:
    """Whole-dollar figures to key into the ATO form, worked the way the FORM works: each entered label is rounded first (instalments cents-ignored, the rest half-up: the ATO's
    rounding rule for the other labels is not confirmed), and the totals W5, 4, 8A, 8B and 9 are then added up from those whole-dollar entries."""
    def whole_label(k, v):
        return D(v["value"]).quantize(Decimal("1"), rounding=ROUND_DOWN) if k in FLOOR_LABELS else whole(v["value"])
    out = {k: whole_label(k, v) for k, v in final.items() if k not in ("T2", "W5", "4", "8A", "8B", "9", "6A")}
    if any(k in final for k in ("W2", "W3", "W4")):
        out["W5"] = out.get("W2", ZERO) + out.get("W3", ZERO) + out.get("W4", ZERO)
        out["4"] = out["W5"]
    if "F1" in out:
        out["6A"] = out["F1"]
    out["8A"] = sum((out.get(k, ZERO) for k in ("1A", "4", "5A", "6A")), ZERO)
    out["8B"] = out.get("1B", ZERO)
    out["9"] = out["8A"] - out["8B"]
    return {k: str(v) for k, v in out.items()}


def sanity_checks(final: dict, rs: TaxRuleSet) -> list:
    """Reasonableness checks that need no database. Returns [{key, severity, message}]."""
    out = []
    g1, a1 = D(final.get("G1", {}).get("value")), D(final.get("1A", {}).get("value"))
    rate = rs.dec("gst.rate") or Decimal("0.10")
    if g1 > 0:
        implied = q2(g1 * rate / (1 + rate))
        if a1 > implied + Decimal("1"):
            out.append(dict(key="1a_exceeds_g1", severity="error", message=f"GST on sales (1A {q2(a1)}) is more than 1/11 of total sales (G1 {q2(g1)} -> maximum {implied}). Check tax codes."))
        if a1 * 11 < g1 * Decimal("0.2"):
            out.append(dict(key="1a_low", severity="warn", message="GST on sales is very low against total sales: most sales appear GST-free or untaxed. Confirm that is correct."))
    elif a1 > 0:
        out.append(dict(key="1a_without_g1", severity="error", message="GST on sales (1A) reported with no total sales (G1)."))
    g10, g11, b1 = D(final.get("G10", {}).get("value")), D(final.get("G11", {}).get("value")), D(final.get("1B", {}).get("value"))
    if (g10 + g11) > 0 and b1 > q2((g10 + g11) * rate / (1 + rate)) + Decimal("1"):
        out.append(dict(key="1b_exceeds_purchases", severity="error", message=f"GST credits (1B {q2(b1)}) exceed 1/11 of purchases (G10+G11 {q2(g10 + g11)}). Check tax codes."))
    if b1 > a1 and (b1 - a1) > Decimal("5000"):
        out.append(dict(key="large_refund", severity="warn", message=f"A GST refund of {q2(b1 - a1)} is claimed. The ATO may review large refunds: keep tax invoices ready."))
    w1, w2 = D(final.get("W1", {}).get("value")), D(final.get("W2", {}).get("value"))
    if w1 > 0 and w2 == 0:
        out.append(dict(key="wages_no_payg", severity="warn", message="Wages are reported at W1 but no PAYG is withheld at W2. Confirm employees are within the tax-free threshold or have a withholding variation."))
    if w2 > w1:
        out.append(dict(key="payg_exceeds_wages", severity="error", message="PAYG withheld (W2) is more than total wages (W1)."))
    return out
