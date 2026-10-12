"""Australian identifier validation and masking (pure). Checksums only prove an identifier is well-formed - never that it is registered or belongs to the person."""
import re

_ABN_W = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
_ACN_W = (8, 7, 6, 5, 4, 3, 2, 1)
_TFN_W = (1, 4, 3, 7, 5, 8, 6, 9, 10)
KINDS = ("abn", "acn", "tfn")


def digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def valid_abn(v) -> bool:
    d = digits(v)
    if len(d) != 11:
        return False
    n = [int(c) for c in d]
    n[0] -= 1
    return sum(w * x for w, x in zip(_ABN_W, n)) % 89 == 0


def valid_acn(v) -> bool:
    d = digits(v)
    if len(d) != 9:
        return False
    s = sum(int(c) * w for c, w in zip(d[:8], _ACN_W))
    return (10 - s % 10) % 10 == int(d[8])


def valid_tfn(v) -> bool:
    d = digits(v)
    return len(d) == 9 and sum(int(c) * w for c, w in zip(d, _TFN_W)) % 11 == 0


def validate(kind: str, v) -> str:
    """-> normalised digits or raises ValueError with a readable message."""
    if kind not in KINDS:
        raise ValueError(f"Unsupported identifier type '{kind}'")
    ok = dict(abn=valid_abn, acn=valid_acn, tfn=valid_tfn)[kind](v)
    if not ok:
        raise ValueError(f"That is not a well-formed {kind.upper()} (wrong length or check digit)")
    return digits(v)


def mask(kind: str, last: str) -> str:
    return {"tfn": f"*** *** {last[-3:]}", "abn": f"** *** *** {last[-3:]}", "acn": f"*** *** {last[-3:]}"}.get(kind, "***")


# which identifiers an entity type may carry
ENTITY_RULES = {
    "individual":  dict(allowed=("tfn", "abn"), required=()),
    "sole_trader": dict(allowed=("tfn", "abn"), required=("abn",)),
    "company":     dict(allowed=("abn", "acn", "tfn"), required=("acn",)),
    "trust":       dict(allowed=("abn", "tfn"), required=()),
    "partnership": dict(allowed=("abn", "tfn"), required=()),
    "smsf":        dict(allowed=("abn", "tfn"), required=("abn",)),
}
ENTITY_TYPES = tuple(ENTITY_RULES)
