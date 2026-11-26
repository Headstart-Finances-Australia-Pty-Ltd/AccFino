"""Reports AI token usage to Prama Monitor (Observability > Platforms > Accfino > AI usage).

It uses the same settings as OpenTelemetry, so nothing extra has to be configured:
  OTEL_EXPORTER_OTLP_ENDPOINT = https://monitor.prama-ai.workers.dev/api/otlp
  OTEL_EXPORTER_OTLP_HEADERS  = Authorization=Bearer <INGEST_TOKEN>
(or PRAMA_INGEST_TOKEN / PRAMA_AI_USAGE_URL if you prefer to set them separately).

Reporting runs in a background thread and never raises, so it can't slow down or break the app.
"""
import os
import threading
import time
from urllib.parse import unquote

import requests

APP_NAME = "accfino"

# Approximate list prices in USD per million tokens (input, output). Used only for the
# cost estimate on the dashboard; unknown models are reported with cost 0.
_PRICES = {
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.8, 4.0),
}


def _settings():
    token = os.environ.get("PRAMA_INGEST_TOKEN", "").strip()
    if not token:
        for part in unquote(os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "")).split(","):
            key, _, val = part.partition("=")
            if key.strip().lower() == "authorization" and val.strip().lower().startswith("bearer"):
                token = val.strip()[6:].strip()
    url = os.environ.get("PRAMA_AI_USAGE_URL", "").strip()
    if not url:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")
        if endpoint.endswith("/api/otlp"):
            url = endpoint[: -len("/otlp")] + "/ingest/ai-usage"
    return url, token


def _cost(model, input_tokens, output_tokens):
    for prefix, (pin, pout) in _PRICES.items():
        if str(model).startswith(prefix):
            return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)
    return 0


def _trace_id():
    try:
        from opentelemetry import trace
        ctx = trace.get_current_span().get_span_context()
        return format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
    except Exception:
        return None


def _send(url, token, event):
    try:
        requests.post(url, json=event, timeout=5, headers={"Authorization": f"Bearer {token}"})
    except Exception as e:  # never break the app
        print(f"[accfino] Prama AI usage report failed: {e}")


def report_ai_usage(provider, model, input_tokens, output_tokens, duration_ms=None, operation="chat"):
    """Call after each AI request. Does nothing if Prama Monitor is not configured."""
    url, token = _settings()
    if not url or not token:
        return
    event = {
        "app": APP_NAME, "provider": provider, "model": model, "operation": operation,
        "input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0),
        "cost_usd": _cost(model, int(input_tokens or 0), int(output_tokens or 0)),
        "duration_ms": duration_ms, "trace_id": _trace_id(),
    }
    threading.Thread(target=_send, args=(url, token, event), daemon=True).start()


def report_anthropic(resp, started_at=None, operation="chat"):
    """Convenience wrapper for an anthropic `messages.create` response."""
    try:
        usage = getattr(resp, "usage", None)
        if usage is None:
            return
        duration = int((time.time() - started_at) * 1000) if started_at else None
        report_ai_usage("anthropic", getattr(resp, "model", "unknown"),
                        getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0),
                        duration_ms=duration, operation=operation)
    except Exception:
        pass
