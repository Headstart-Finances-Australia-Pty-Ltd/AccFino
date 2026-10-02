"""Square REST calls AccFino needs: customer, card on file, payment, location check. Server-side only. Network goes through _client() so tests use a mock Square."""
import uuid
from typing import Optional

import httpx

API_VERSION = "2024-10-17"
HOSTS = {"sandbox": "https://connect.squareupsandbox.com", "production": "https://connect.squareup.com"}
_transport = None


class SquareError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400, category: str = ""):
        super().__init__(detail)
        self.code, self.detail, self.status, self.category = code, detail, status, category


def _client() -> httpx.Client:
    return httpx.Client(timeout=25, transport=_transport)


def _call(cfg, method: str, path: str, body: Optional[dict] = None) -> dict:
    url = HOSTS.get(cfg.environment, HOSTS["sandbox"]) + path
    headers = {"Authorization": f"Bearer {cfg.access_token}", "Square-Version": API_VERSION, "Content-Type": "application/json"}
    try:
        with _client() as c:
            r = c.request(method, url, headers=headers, json=body)
    except httpx.HTTPError:
        raise SquareError("unreachable", "Could not reach Square.", 503)
    try:
        j = r.json() if r.content else {}
    except ValueError:
        j = {}
    if r.status_code >= 400 or j.get("errors"):
        e = (j.get("errors") or [{}])[0]
        raise SquareError(e.get("code") or f"http_{r.status_code}", e.get("detail") or f"Square returned {r.status_code}.", r.status_code, e.get("category", ""))
    return j


def key() -> str:
    return uuid.uuid4().hex


def get_location(cfg) -> dict:
    return _call(cfg, "GET", f"/v2/locations/{cfg.location_id}").get("location", {})


def create_customer(cfg, *, idempotency_key: str, email: str, company: str, reference_id: str) -> dict:
    return _call(cfg, "POST", "/v2/customers", {"idempotency_key": idempotency_key, "email_address": email or None, "company_name": company, "reference_id": reference_id}).get("customer", {})


def create_card(cfg, *, source_id: str, customer_id: str, idempotency_key: str) -> dict:
    return _call(cfg, "POST", "/v2/cards", {"idempotency_key": idempotency_key, "source_id": source_id, "card": {"customer_id": customer_id}}).get("card", {})


def disable_card(cfg, card_id: str) -> None:
    _call(cfg, "POST", f"/v2/cards/{card_id}/disable", {})


def create_payment(cfg, *, card_id: str, customer_id: str, amount_cents: int, idempotency_key: str, email: str, note: str, reference_id: str) -> dict:
    return _call(cfg, "POST", "/v2/payments", {
        "idempotency_key": idempotency_key, "source_id": card_id, "customer_id": customer_id, "location_id": cfg.location_id, "autocomplete": True,
        "amount_money": {"amount": int(amount_cents), "currency": "AUD"}, "buyer_email_address": email or None, "note": note[:500], "reference_id": reference_id[:40]}).get("payment", {})
