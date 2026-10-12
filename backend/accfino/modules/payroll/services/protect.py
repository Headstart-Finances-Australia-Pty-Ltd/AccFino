"""Protection of sensitive payroll fields: validation, sealing (Fernet via core.security.secrets) and masking."""
import re
from typing import Optional

from accfino.core.security import secrets as _secrets
from accfino.modules.payroll.services.errors import PayrollError

_TFN_W = (1, 4, 3, 7, 5, 8, 6, 9, 10)


def clean_digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def valid_tfn(v) -> bool:
    d = clean_digits(v)
    return len(d) == 9 and sum(int(c) * w for c, w in zip(d, _TFN_W)) % 11 == 0


def seal_tfn(v) -> tuple:
    """-> (sealed, last3). Raises PayrollError for an invalid TFN."""
    d = clean_digits(v)
    if not valid_tfn(d):
        raise PayrollError("That is not a valid Tax File Number (9 digits with a correct check digit)")
    return _secrets.seal(d), d[-3:]


def reveal(blob: Optional[str]) -> Optional[str]:
    return _secrets.unseal(blob) if blob else None


def mask_tfn(last3: Optional[str]) -> Optional[str]:
    return f"*** *** {last3}" if last3 else None


def norm_bsb(v) -> str:
    d = clean_digits(v)
    if len(d) != 6:
        raise PayrollError("BSB must be 6 digits (e.g. 062-000)")
    return f"{d[:3]}-{d[3:]}"


def seal_account(v) -> tuple:
    d = clean_digits(v)
    if not 5 <= len(d) <= 9:
        raise PayrollError("Bank account number must be 5 to 9 digits")
    return _secrets.seal(d), d[-4:]


def mask_account(last4: Optional[str]) -> Optional[str]:
    return f"•••• {last4}" if last4 else None


SENSITIVE_KEYS = {"tfn", "tfn_enc", "account", "account_number", "account_enc"}


def scrub(d: Optional[dict]) -> Optional[dict]:
    """Remove anything sensitive from a dict before it is written to the audit trail, logs or an API response."""
    if d is None:
        return None
    return {k: ("***" if k in SENSITIVE_KEYS else v) for k, v in d.items()}
