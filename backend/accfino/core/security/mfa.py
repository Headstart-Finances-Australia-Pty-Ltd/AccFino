"""TOTP multi-factor authentication (RFC 6238, compatible with Google/Microsoft Authenticator)."""
import base64
import io
import secrets

import bcrypt
import pyotp

ISSUER = "AccFino"


def new_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=ISSUER)


def qr_data_uri(uri: str) -> str:
    try:
        import qrcode
        img = qrcode.make(uri)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ""


def verify_code(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not secret or not code.isdigit():
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def new_recovery_codes(n: int = 8):
    codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(n)]
    hashes = [bcrypt.hashpw(c.encode(), bcrypt.gensalt(rounds=10)).decode() for c in codes]
    return codes, hashes


def use_recovery_code(hashes, code: str):
    """Returns remaining hashes if code matched, else None."""
    code = (code or "").strip().lower()
    for h in hashes or []:
        try:
            if bcrypt.checkpw(code.encode(), h.encode()):
                return [x for x in hashes if x != h]
        except Exception:
            continue
    return None
