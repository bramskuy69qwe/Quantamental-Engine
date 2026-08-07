"""One redaction helper for every provider credential that rides a URL.

WHY THIS MODULE EXISTS. httpx puts the FULL request URL — query string
included — into `HTTPStatusError`'s message, and this codebase logs exception
text into the rotating JSON log at `data/logs/risk_engine.jsonl`. Any provider
that authenticates with a query parameter therefore leaks its key on the first
transport error.

This has now happened twice with two different parameter names:

  * 2026-07-30 — Finnhub's `token=`. Capping the `httpx` logger at WARNING
    silenced the per-request INFO echo, but the exception text still carried
    it, so `core/news_fetcher` grew a local `token=` scrubber.
  * 2026-08-07 — FRED's `api_key=`. The new calendar fetcher redacted it, but
    `core/regime_fetcher` had been calling the SAME FRED key since v2.5 with
    NO redaction at all (`log.error("US10Y fetch failed: %s", e)`), so a
    single 429 would have written the key in cleartext.

Two modules solving the same problem privately is how the second one got
missed. Anything logging an exception from a keyed HTTP call must route it
through `redact()` here — never `str(e)`.

The pattern is deliberately parameter-NAME driven and generous: new providers
bring new spellings, and a false-positive redaction costs nothing while a
false negative is a credential in a log file that is retained through
rotation.
"""
from __future__ import annotations

import re

# Query-parameter names that carry a credential. Matched case-insensitively,
# and the value is taken up to the next delimiter (& # space quote).
_SECRET_PARAMS = (
    "api_key", "apikey", "api-key",
    "token", "access_token", "auth_token",
    "key", "secret", "password", "passwd", "signature",
)

_QS_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(p) for p in _SECRET_PARAMS) + r")=([^&\s\"'<>]+)"
)

# `Authorization: Bearer xxx` / `X-MBX-APIKEY: xxx` style header echoes.
_HDR_RE = re.compile(r"(?i)(bearer|x-mbx-apikey:?)\s+([A-Za-z0-9_\-\.]{8,})")


def redact(value: object) -> str:
    """Stringify *value* with any URL/header credential replaced by ``***``.

    Safe on exceptions, strings, or anything else — it stringifies first.
    """
    out = _QS_RE.sub(lambda m: f"{m.group(1)}=***", str(value))
    return _HDR_RE.sub(lambda m: f"{m.group(1)} ***", out)
