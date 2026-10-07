"""Admin check for organisation web addresses (https://<name>.<TENANT_BASE_DOMAIN>).

Four steps, each reported on its own so the platform owner can see exactly what is missing:
  1. setting    TENANT_BASE_DOMAIN is set (and what an organisation address will look like)
  2. dns        a made-up name under the base domain resolves (= a wildcard DNS record exists)
  3. https      that address answers over HTTPS with a certificate the browser would trust (= a wildcard certificate covers it)
  4. routing    the answer comes from AccFino and AccFino reads the organisation name out of the address (= the proxy forwards the Host header)
Nothing is changed or stored. The probe name is random and never an organisation."""
import os
import secrets
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx

from accfino.core.tenancy import service as T

_resolver = socket.getaddrinfo          # replaced in tests
_transport = None                       # replaced in tests (httpx.MockTransport)


def _fix(step: str, base: str) -> str:
    return {
        "setting": "Set TENANT_BASE_DOMAIN on the server (for example TENANT_BASE_DOMAIN=" + (base or "accfino.com") + ") and restart AccFino.",
        "dns": f"Add a wildcard DNS record *.{base or 'accfino.com'} (a CNAME to your host's address, DNS-only if you use Cloudflare) so every organisation name resolves.",
        "https": f"The address resolves but HTTPS failed. A wildcard certificate for *.{base or 'accfino.com'} is needed (on Northflank: certificate generation 'Wildcard via DCV', or import one).",
        "routing": "HTTPS works but the request did not reach AccFino with the organisation name. Route the wildcard to the AccFino service and let the proxy pass the Host header unchanged.",
    }[step]


def check(scheme: Optional[str] = None) -> dict:
    base = T.base_domain()
    scheme = (scheme or os.environ.get("TENANT_SCHEME", "https")).strip().lower() or "https"
    out = {"base_domain": base, "scheme": scheme, "steps": [], "ok": False, "example": None}

    def add(key, ok, detail):
        out["steps"].append({"key": key, "ok": ok, "detail": detail, **({} if ok else {"fix": _fix(key, base.split(":")[0])})})
        return ok

    if not add("setting", bool(base), f"TENANT_BASE_DOMAIN = {base}" if base else "TENANT_BASE_DOMAIN is not set, so organisation addresses are off."):
        return out
    out["example"] = f"{scheme}://your-organisation.{base}"
    host_part = base.split(":")[0]
    probe = "check-" + secrets.token_hex(4)
    host = f"{probe}.{base}"
    try:
        addrs = _resolver(f"{probe}.{host_part}", None)
    except OSError:
        return (add("dns", False, f"{probe}.{host_part} does not resolve - there is no wildcard record *.{host_part}."), out)[1]
    add("dns", True, f"{probe}.{host_part} resolves (wildcard DNS is in place).")
    url = f"{scheme}://{host}/tenant/current"
    try:
        with httpx.Client(timeout=10, transport=_transport, follow_redirects=False) as c:
            r = c.get(url)
    except httpx.ConnectError as e:
        msg = str(e)
        add("https", False, "Could not connect over " + scheme.upper() + (" - certificate problem: " + msg[:140] if "certificate" in msg.lower() or "ssl" in msg.lower() else ": " + msg[:140]))
        return out
    except httpx.HTTPError as e:
        add("https", False, "Could not connect: " + str(e)[:140])
        return out
    add("https", True, f"{scheme.upper()} answered ({r.status_code}).")
    try:
        body = r.json()
    except ValueError:
        body = None
    me = isinstance(body, dict) and body.get("tenant") == probe                     # AccFino's own answer names the organisation it read from the address
    add("routing", me, "AccFino received the address and read the organisation name from it." if me else f"The answer ({r.status_code}) was not AccFino reading '{probe}' from the address.")
    out["ok"] = all(s["ok"] for s in out["steps"])
    return out
