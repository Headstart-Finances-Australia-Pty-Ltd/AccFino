"""Portfolio maths: allocation and diversification. Weights are by market value."""
from typing import Dict, List

from accfino.modules.investments.engine.money import ZERO, D, q2


def allocate(items: List[dict], key: str) -> List[dict]:
    """items need `value`; groups by item[key] (None -> 'Unclassified'). Returns [{name, value, weight}] largest first."""
    total = sum((D(i["value"]) for i in items), ZERO)
    g: Dict[str, "D"] = {}
    for i in items:
        g[i.get(key) or "Unclassified"] = g.get(i.get(key) or "Unclassified", ZERO) + D(i["value"])
    return [dict(name=k, value=q2(v), weight=float(v / total) if total else 0.0) for k, v in sorted(g.items(), key=lambda kv: -kv[1])]


def diversification(items: List[dict], single_limit: float = 0.2) -> dict:
    """Herfindahl-Hirschman index on holdings, the effective number of holdings (1/HHI), top-1 and top-5 weight, and holdings above `single_limit` (advisory, not a recommendation)."""
    total = sum((D(i["value"]) for i in items), ZERO)
    if total <= 0 or not items:
        return dict(holdings=len(items), hhi=None, effective_holdings=None, top1=None, top5=None, over_limit=[], limit=single_limit)
    w = sorted(((float(D(i["value"]) / total), i.get("name") or i.get("code") or "?") for i in items), reverse=True)
    hhi = sum(x * x for x, _ in w)
    return dict(holdings=len(items), hhi=hhi, effective_holdings=1 / hhi, top1=w[0][0], top5=sum(x for x, _ in w[:5]), over_limit=[dict(name=n, weight=x) for x, n in w if x > single_limit], limit=single_limit)
