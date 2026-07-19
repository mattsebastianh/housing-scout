"""Shared utility helpers used across the scout package."""
import os

import httpx


def safe_exc_str(exc: BaseException) -> str:
    """Return a safe string representation of an exception, redacting secrets.

    ScrapeOps and other services embed api_key in request URLs, so raw
    exception messages would leak secrets into logs and Telegram alerts.
    httpx errors are reduced to their type/status only; all other exceptions
    have any env var value ending in _KEY or _TOKEN (≥8 chars) replaced.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return type(exc).__name__
    text = str(exc)
    for name, value in os.environ.items():
        if name.endswith(("_KEY", "_TOKEN")) and len(value) >= 8:
            text = text.replace(value, f"[REDACTED:{name}]")
    return text
