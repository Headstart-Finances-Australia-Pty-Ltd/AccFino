"""
accfino_core.security.contact
-----------------------------
ONE definition of "a valid email address" and "a valid phone number", used by every place that creates or
changes a user: organisation signup, join-by-access-code, the legacy /auth/register, the profile page, and the
database-model guard (db_app.models.user). Keeping it in one pure module (stdlib only) means the frontend rules,
the API rules and the model rules can never drift apart.

Email    format-validated, trimmed and lower-cased. (No MX lookup: the app must work offline and in tests.)
Phone    Australian numbers (04xx xxx xxx, 02/03/07/08 xxxx xxxx, +61 ...) and international numbers (+<country><number>).
         Stored in E.164 ("+61412345678") so SMS codes and notifications can use it directly.

Existing accounts created before phone numbers were mandatory are NOT broken: `missing_contact()` reports what they lack and
the app asks them to complete their profile at next sign-in (see security.middleware and the My Account page).
"""
import contextvars
import re
from contextlib import contextmanager
from typing import Iterable, Optional

EMAIL_REQUIRED = "Email address is required."
EMAIL_INVALID = "Please enter a valid email address."
PHONE_REQUIRED = "Phone number is required."
PHONE_INVALID = "Please enter a valid phone number."

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_LOCAL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+$")
_DOMAIN = re.compile(rf"^{_LABEL}(?:\.{_LABEL})+$")
_TLD = re.compile(r"^[A-Za-z]{2,}$")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class ContactError(ValueError):
    """Carries one message per bad field: {"email": "...", "phone": "..."}."""

    def __init__(self, errors: dict):
        self.errors = errors
        super().__init__(" ".join(errors.values()))


# ------------------------------------------------------------------------------------------------ email --
def normalise_email(raw: Optional[str]) -> str:
    """-> the trimmed, lower-cased address. Raises ContactError({"email": ...})."""
    s = (raw or "").strip()
    if not s:
        raise ContactError({"email": EMAIL_REQUIRED})
    if len(s) > 200 or s.count("@") != 1 or any(c.isspace() for c in s):
        raise ContactError({"email": EMAIL_INVALID})
    local, domain = s.rsplit("@", 1)
    if (not local or len(local) > 64 or not _LOCAL.match(local) or local.startswith(".") or local.endswith(".") or ".." in local
            or not _DOMAIN.match(domain) or not _TLD.match(domain.rsplit(".", 1)[1])):
        raise ContactError({"email": EMAIL_INVALID})
    return s.lower()


def is_valid_email(raw: Optional[str]) -> bool:
    try:
        normalise_email(raw)
        return True
    except ContactError:
        return False


# ------------------------------------------------------------------------------------------------ phone --
def normalise_phone(raw: Optional[str]) -> str:
    """-> E.164 (+61412345678). Australian national format is assumed when there is no country code.
    Raises ContactError({"phone": ...})."""
    s = (raw or "").strip()
    if not s:
        raise ContactError({"phone": PHONE_REQUIRED})
    bad = ContactError({"phone": PHONE_INVALID})
    if re.search(r"[^\d\s()+.\-]", s) or "+" in s[1:]:
        raise bad
    digits = re.sub(r"\D", "", s)
    if s.startswith("+"):
        e164 = "+" + digits
    elif digits.startswith("00"):
        e164 = "+" + digits[2:]
    elif digits.startswith("0"):
        e164 = "+61" + digits[1:]                       # Australian national format: 0412 345 678, (02) 9999 9999
    elif digits.startswith("61") and len(digits) == 11:
        e164 = "+" + digits                              # 61412345678 typed without the plus
    else:
        raise bad
    if not _E164.match(e164):
        raise bad
    if e164.startswith("+61"):                           # Australia: 9 digits after the country code, starting 2-5, 7 or 8
        if not re.fullmatch(r"[2-578]\d{8}", e164[3:]):
            raise bad
    elif e164.startswith("+1"):                          # North America: 10 digits, area code starts 2-9
        if not re.fullmatch(r"[2-9]\d{9}", e164[2:]):
            raise bad
    return e164


def is_valid_phone(raw: Optional[str]) -> bool:
    try:
        normalise_phone(raw)
        return True
    except ContactError:
        return False


def format_phone(e164: Optional[str]) -> str:
    """Human-friendly display: +61412345678 -> 0412 345 678; others are returned as stored."""
    p = (e164 or "").strip()
    if re.fullmatch(r"\+61[2-578]\d{8}", p):
        n = "0" + p[3:]
        return f"{n[:4]} {n[4:7]} {n[7:]}" if n.startswith("04") else f"({n[:2]}) {n[2:6]} {n[6:]}"
    return p


# ------------------------------------------------------------------------------------------------ both --
def validate_contact(email: Optional[str], phone: Optional[str]) -> tuple:
    """Validate BOTH fields and report every problem at once. -> (email, phone_e164)."""
    errors, out_e, out_p = {}, None, None
    try:
        out_e = normalise_email(email)
    except ContactError as e:
        errors.update(e.errors)
    try:
        out_p = normalise_phone(phone)
    except ContactError as e:
        errors.update(e.errors)
    if errors:
        raise ContactError(errors)
    return out_e, out_p


def platform_admin_email() -> str:
    """The platform administrator's login email (ADMIN_EMAIL, default admin@accfino.com)."""
    import os
    return (os.environ.get("ADMIN_EMAIL") or "admin@accfino.com").strip().lower()


def is_platform_admin_email(email: Optional[str]) -> bool:
    """True for the platform administrator account: it is never asked for email / phone details or verification."""
    return (email or "").strip().lower() == platform_admin_email()


def missing_contact(email: Optional[str], phone: Optional[str]) -> list:
    """Which of 'email' / 'phone' an EXISTING account lacks (or has in an unusable form). [] = profile complete.
    The platform administrator (admin@accfino.com) is exempt: it is never asked to add or verify contact details."""
    if is_platform_admin_email(email):
        return []
    out = []
    if not is_valid_email(email):
        out.append("email")
    if not is_valid_phone(phone):
        out.append("phone")
    return out


def http_422(err: ContactError):
    from fastapi import HTTPException
    return HTTPException(422, " ".join(err.errors[k] for k in ("email", "phone") if k in err.errors))


# ------------------------------------------------------------------------------------- the model guard --
_ALLOW = contextvars.ContextVar("accfino_allow_incomplete_contact", default=False)


@contextmanager
def allow_incomplete_contact(db=None):
    """ONLY for bootstrap code that must create the platform's first administrator before a phone number is known.
    Lifts the model guard (and, on PostgreSQL, the database trigger for this transaction). Flush inside the block."""
    token = _ALLOW.set(True)
    try:
        if db is not None and db.bind is not None and db.bind.dialect.name == "postgresql":
            from sqlalchemy import text
            db.execute(text("SET LOCAL accfino.allow_incomplete_contact = 'on'"))
        yield
    finally:
        _ALLOW.reset(token)


def enforce_on_insert(user) -> None:
    """Called by the User model before INSERT: no user row can be created without a valid email and phone. Also stores the normalised forms."""
    if _ALLOW.get():
        return
    user.email, user.phone = validate_contact(user.email, user.phone)


def enforce_on_update(user, changed: Iterable[str]) -> None:
    """Called before UPDATE: an email/phone that is being CHANGED must be valid (existing incomplete rows may still be saved for other reasons)."""
    if _ALLOW.get():
        return
    errors = {}
    if "email" in changed:
        try:
            user.email = normalise_email(user.email)
        except ContactError as e:
            errors.update(e.errors)
    if "phone" in changed:
        try:
            user.phone = normalise_phone(user.phone)
        except ContactError as e:
            errors.update(e.errors)
    if errors:
        raise ContactError(errors)
