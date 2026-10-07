"""Division 7A (private company loans) engine: minimum yearly repayment (ITAA 1936 s109E(6)), yearly loan schedule and deemed-dividend shortfall.
Pure functions. NOT assessed: distributable surplus (a deemed dividend is capped by it), Division 7A trust UPE sub-trust loans (PSLAs), loan amalgamation
across several advances, section 109N(1) conditions beyond a recorded written agreement date, and the commissioner's discretion. Tax agent review required."""
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from accfino.modules.taxation.engine.money import ZERO, D, q2


def min_yearly_repayment(opening_balance, benchmark_rate, remaining_term_years) -> Decimal:
    """balance x r / (1 - (1/(1+r))^n)."""
    bal, r, n = D(opening_balance), D(benchmark_rate), int(remaining_term_years)
    if n <= 0:
        return q2(bal * (1 + r))            # final year: the whole balance with interest
    if r == 0:
        return q2(bal / n)
    return q2(bal * r / (1 - (1 / (1 + r)) ** n))


def schedule(*, advance_date: date, principal, term_years: int, benchmark_by_fy: Dict[str, Decimal], repayments_by_fy: Dict[str, Decimal],
             fy_of, through_fy: str, agreement_date: Optional[date], lodgement_day: Optional[date] = None, interest_charged_by_fy: Optional[Dict[str, Decimal]] = None) -> dict:
    """Yearly schedule from the loan's first income year to `through_fy`. The loan year itself has no minimum repayment (the first is due the
    following year); every later year the MYR uses that year's benchmark rate and the remaining term."""
    first_fy = fy_of(advance_date)
    start_year, end_year = int(first_fy[:4]), int(through_fy[:4])
    rows, bal, flags = [], D(principal), []
    if term_years not in (7, 25):
        flags.append(dict(severity="warn", message=f"Terms other than 7 years (unsecured) or 25 years (secured over real property) are not complying terms (term entered: {term_years})."))
    if agreement_date is None:
        flags.append(dict(severity="error", message="No written loan agreement date recorded: the loan is likely a deemed dividend unless fully repaid before the lodgement day."))
    elif lodgement_day and agreement_date > lodgement_day:
        flags.append(dict(severity="error", message="The written agreement is dated after the lodgement day of the company's return for the loan year."))
    for y in range(start_year, end_year + 1):
        fy = f"{y}-{str(y + 1)[-2:]}"
        rate = benchmark_by_fy.get(fy)
        if rate is None:
            flags.append(dict(severity="review", message=f"No benchmark rate for {fy}: schedule stops here."))
            break
        paid = D(repayments_by_fy.get(fy))
        interest = q2(bal * rate)
        if y == start_year:
            myr, remaining, shortfall = ZERO, term_years, ZERO
            interest = ZERO
            closing = bal - paid
            note = "Loan year: no minimum yearly repayment; interest starts accruing next year."
        else:
            remaining = term_years - (y - start_year) + 1
            if remaining <= 0 or bal <= 0:
                rows.append(dict(fy=fy, opening=str(q2(bal)), benchmark_rate=str(rate), remaining_term=max(remaining, 0), minimum_repayment="0.00", repaid=str(q2(paid)), shortfall="0.00", interest="0.00", closing=str(q2(bal)), note="Loan fully repaid or term ended."))
                continue
            myr = min(min_yearly_repayment(bal, rate, remaining), q2(bal * (1 + rate)))
            shortfall = max(myr - paid, ZERO)
            closing = bal + interest - paid
            note = "Shortfall is a deemed unfranked dividend (capped by distributable surplus, not assessed)." if shortfall > 0 else ""
        rows.append(dict(fy=fy, opening=str(q2(bal)), benchmark_rate=str(rate), remaining_term=remaining, minimum_repayment=str(myr), repaid=str(q2(paid)), shortfall=str(q2(shortfall)),
                         interest=str(q2(interest)), closing=str(q2(max(closing, ZERO))), note=note))
        if shortfall > 0:
            flags.append(dict(severity="error", message=f"{fy}: minimum yearly repayment shortfall ${q2(shortfall):,.2f} (deemed dividend risk)."))
        ic = (interest_charged_by_fy or {}).get(fy)
        if ic is not None and y != start_year and q2(ic) < q2(interest):
            flags.append(dict(severity="error", message=f"{fy}: interest charged ${q2(ic):,.2f} is below the benchmark interest ${q2(interest):,.2f}."))
        bal = max(closing, ZERO)
    return dict(rows=rows, flags=flags, closing_balance=str(q2(bal)),
                not_assessed=["Distributable surplus cap", "Trust UPE / sub-trust arrangements", "Loan amalgamation of several advances", "Commissioner's discretion", "Franking of any deemed dividend"])
