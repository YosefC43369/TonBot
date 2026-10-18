"""
Input validation and Telegram message sanitization.

Prevents Markdown/HTML injection from untrusted blockchain metadata.
"""

from __future__ import annotations

import re


# Characters that must be escaped in Telegram MarkdownV2
_MDV2_SPECIAL = r"\_*[]()~`>#+-=|{}.!"
_MDV2_ESCAPE_RE = re.compile(r"([" + re.escape(_MDV2_SPECIAL) + r"])")


def escape_mdv2(text: str) -> str:
    """Escape a string for safe use inside a MarkdownV2 Telegram message."""
    return _MDV2_ESCAPE_RE.sub(r"\\\1", text)


def sanitize_label(label: str, max_length: int = 64) -> str:
    """
    Sanitize a user-supplied wallet label.
    Strips control characters, limits length.
    """
    # Strip non-printable / control chars
    label = re.sub(r"[\x00-\x1f\x7f]", "", label)
    label = label.strip()
    return label[:max_length]


def validate_command_arg(arg: str, max_length: int = 128) -> str:
    """
    Basic guard for command arguments — strip whitespace, cap length.
    Callers are responsible for semantic validation (e.g. address format).
    """
    return arg.strip()[:max_length]