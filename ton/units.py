"""
TON unit conversion using exact Decimal arithmetic.

Never uses float for currency amounts — floats cannot represent
nanoton values exactly for large balances.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

_NANOTON_PER_TON = Decimal("1_000_000_000")
_TON_DISPLAY_PLACES = Decimal("0.000000001")  # 9 decimal places


def nanoton_to_ton(nanotons: int | str) -> Decimal:
    """
    Convert a nanoton integer to a TON Decimal value.

    Args:
        nanotons: integer or string representation of nanotons.

    Returns:
        Exact Decimal TON value.
    """
    return Decimal(nanotons) / _NANOTON_PER_TON


def ton_to_nanoton(ton: Decimal | str) -> int:
    """
    Convert a TON amount to nanotons, rounded down.

    Intentionally conservative — never round up when spending.
    """
    return int(Decimal(ton) * _NANOTON_PER_TON)


def format_ton(nanotons: int | str, places: int = 9) -> str:
    """
    Return a human-readable TON string with at most `places` decimal digits,
    trailing zeros stripped.

    Example: format_ton(1_500_000_000) → "1.5"
    """
    quantizer = Decimal(10) ** -places
    value = nanoton_to_ton(nanotons).quantize(quantizer, rounding=ROUND_DOWN)
    # Strip trailing zeros but keep at least one decimal place
    formatted = f"{value:f}".rstrip("0").rstrip(".")
    return formatted if "." in formatted else formatted


def format_jetton(raw_amount: int | str, decimals: int) -> str:
    """
    Convert a raw Jetton amount to human-readable form.

    Each Jetton contract declares its own `decimals` field — must be
    fetched from the provider, not assumed.

    Args:
        raw_amount: integer smallest-unit amount from the provider.
        decimals:   number of decimal places declared by the Jetton contract.

    Returns:
        Human-readable string, trailing zeros stripped.
    """
    if decimals < 0 or decimals > 30:
        raise ValueError(f"Jetton decimals out of range: {decimals}")
    divisor = Decimal(10) ** decimals
    value = Decimal(raw_amount) / divisor
    quantizer = Decimal(10) ** -decimals
    formatted = f"{value.quantize(quantizer, rounding=ROUND_DOWN):f}"
    return formatted.rstrip("0").rstrip(".")