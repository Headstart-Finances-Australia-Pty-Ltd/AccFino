"""
currency_service.py
Fetches live exchange rates from Google Finance and converts amounts to AUD.
Results are cached for 1 hour to avoid hammering the API.
"""
import time
import logging
import re
import urllib.request

logger = logging.getLogger(__name__)

# In-memory cache: currency -> (rate_to_AUD, fetched_at_epoch)
_RATE_CACHE: dict[str, tuple[float, float]] = {}
_CACHE_TTL_SECS = 3600  # 1 hour

# Popular currencies with known reasonable fallback rates (used if Google fetch fails)
_FALLBACK_RATES_TO_AUD: dict[str, float] = {
    "AUD": 1.0,
    "USD": 1.55,
    "EUR": 1.70,
    "GBP": 1.97,
    "JPY": 0.0104,
    "INR": 0.0186,
    "CNY": 0.214,
    "CAD": 1.14,
    "CHF": 1.76,
    "NZD": 0.92,
    "SGD": 1.16,
    "HKD": 0.199,
    "KRW": 0.00113,
    "SEK": 0.151,
    "NOK": 0.148,
    "DKK": 0.228,
    "MXN": 0.0804,
    "BRL": 0.282,
    "ZAR": 0.0849,
    "AED": 0.422,
    "THB": 0.0444,
    "MYR": 0.350,
    "IDR": 0.0000959,
    "PHP": 0.0271,
    "PKR": 0.00559,
    "BDT": 0.0141,
    "VND": 0.0000607,
}

SUPPORTED_CURRENCIES = sorted(_FALLBACK_RATES_TO_AUD.keys())


def _fetch_from_google(from_currency: str) -> float | None:
    """
    Fetch exchange rate from_currency -> AUD using Google Finance.
    Returns float (rate) or None on failure.
    """
    if from_currency == "AUD":
        return 1.0
    try:
        url = f"https://www.google.com/finance/quote/{from_currency}-AUD"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Google Finance embeds the rate in a data-last-price attribute or
        # inside a <div class="YMlKec fxKbKc"> element.
        patterns = [
            r'data-last-price="([0-9.]+)"',
            r'class="YMlKec fxKbKc"[^>]*>([0-9.,]+)<',
            r'"([0-9]+\.[0-9]+)"[^}]*"AUD"',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                rate = float(m.group(1).replace(",", ""))
                if 0 < rate < 1_000_000:
                    logger.info(f"Google Finance rate {from_currency}->AUD = {rate}")
                    return rate

        logger.warning(f"Could not parse Google Finance rate for {from_currency}/AUD")
    except Exception as e:
        logger.warning(f"Google Finance fetch failed for {from_currency}: {e}")
    return None


def get_rate_to_aud(currency: str) -> float:
    """
    Return the exchange rate: 1 <currency> = X AUD.
    Tries Google Finance first, falls back to hardcoded rates.
    Results are cached for 1 hour.
    """
    currency = (currency or "AUD").upper().strip()
    if currency == "AUD":
        return 1.0

    now = time.time()
    cached = _RATE_CACHE.get(currency)
    if cached and (now - cached[1]) < _CACHE_TTL_SECS:
        return cached[0]

    rate = _fetch_from_google(currency)
    if rate is None:
        rate = _FALLBACK_RATES_TO_AUD.get(currency, 1.0)
        logger.warning(f"Using fallback rate for {currency}: {rate}")

    _RATE_CACHE[currency] = (rate, now)
    return rate


def convert_to_aud(amount: float, currency: str) -> tuple[float, float]:
    """
    Convert amount from currency to AUD.
    Returns (aud_amount, rate_used).
    """
    if not amount:
        return 0.0, 1.0
    currency = (currency or "AUD").upper().strip()
    if currency == "AUD":
        return float(amount), 1.0
    rate = get_rate_to_aud(currency)
    return round(float(amount) * rate, 4), rate
