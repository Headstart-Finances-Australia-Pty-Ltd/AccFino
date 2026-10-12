"""
accfino.core.security.secrets
-----------------------------
Field-level sealing of stored credentials (Basiq/Square/OpenFeed keys, ...). Moved here from the OpenFeed module because every
module that stores a secret needs it; the algorithm, key derivation and salt are unchanged, so existing sealed values still decrypt.
"""
import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    raw = os.environ.get("FIELD_ENCRYPTION_KEY", "").strip()
    if raw:
        key = raw.encode()
    else:                                                               # derived from the app secret: stable across restarts, never stored
        from accfino.core.security import tokens
        key = base64.urlsafe_b64encode(hashlib.sha256(("openfeed|" + tokens._secret()).encode()).digest())
    return Fernet(key)


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(blob: str) -> Optional[str]:
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError, AttributeError):
        return None
