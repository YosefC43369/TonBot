"""
TON address validation and normalization.

Uses pytoniq-core for authoritative parsing — not a regex.
Different textual representations of the same account are unified
into a single canonical form before storage.
"""

from __future__ import annotations

from dataclasses import dataclass

from pytoniq_core import Address as _TonAddress


class AddressValidationError(ValueError):
    """Raised when an address string cannot be parsed as a valid TON address."""
    

@dataclass(frozen=True, slots=True)
class NormalizedAddress:
    """
    A validated, canonical TON address.

    `canonical` is the bounceable base64url form (EQ…/UQ…).
    `raw` is the 0:<hex workchain:hash> form, useful for provider API calls.
    `original` preserves whatever the user typed — for display only.
    """
    
    canonical: str  # bounceable, urlsafe base64
    raw: str        # 0:<64-hex-chars>
    original: str   # as supplied — never used for identity or storage
    
    
def parse_address(address_str: str) -> NormalizedAddress:
    """
    Parse and normalize a TON address string.

    Accepts:
    - Friendly base64url (bounceable EQ… / non-bounceable UQ…)
    - Raw hex form  0:<64 hex chars>

    Raises:
        AddressValidationError: if the string is not a valid TON address.
    """
    raw = address_str.strip()
    if not raw:
        raise AddressValidationError("Address must not be empty.")
        
    try:
        addr = _TonAddress(raw)
    except Exception as exc:
        raise AddressValidationError(
            f"Invalid TON address: {raw!r}"
        ) from exc
        
    try:
        canonical = addr.to_str(is_bounceable=True, is_url_safe=True)
        raw_from = f"{addr.wc}:{addr.hash_part.hex()}"
    except Exception as exc:
        raise AddressValidationError(
            f"Could not serialize TON address: {raw!r}"
        ) from exc
    
    return NormalizedAddress(
        canonical=canonical,
        raw=raw_form,
        original=address_str,
    )
    
    
def addresses_are_equal(a: str, b: str) -> bool:
    """
    Return True if two address strings resolve to the same on-chain account.
    Raises AddressValidationError if either is invalid.
    """
    return parse_address(a).canonical == parse_address(b).canonical