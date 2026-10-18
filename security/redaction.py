"""
Utilities for scrubbing sensitive values before they reach logs,
Telegram messages, or exception traces.
"""

from __future__ import annotations

import re

# Patterns that look like API keys or tokens
_TOKEN_RE = re.compile(r"[0-9]{8,12}:[A-Za-z0-9_\-]{35,}", re.ASCII)
_API_KEY_RE = re.compile(r"[A-Za-z0-9]{32,}", re.ASCII)

# TonAPI bearer key prefix
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """
    Remove query-string tokens and embedded credentials from a URL.
    Safe to log or surface to the user.
    """
    # Strip ?token=... or &api_key=...
    url = re.sub(r"([?&])(token|api_key|key)=[^&]+", r"\1\2=[REDACTED]", url)
    # Strip http://user:pass@host
    url = re.sub(r"://[^@]+@", "://[REDACTED]@", url)
    return url
    
    
def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of headers with Authorization values removed."""
    sensitive = {"authorization", "x-api-key", "x-ton-api-key"}
    return {
        k: "[REDACTED]" if k.lower() in sensitive else v
        for k, v in headers.items()
    }


def safe_error_message(exc: Exception) -> str:
    """
    Return a user-safe error string that cannot leak credentials or
    internal paths.
    """
    msg = str(exc)
    msg = _TOKEN_RE.sub("[REDACTED]", msg)
    msg = _BEARER_RE.sub("Bearer [REDACTED]", msg)
    # Truncate to avoid wall-of-text in Telegram
    return msg[:256] if len(msg) > 256 else msg