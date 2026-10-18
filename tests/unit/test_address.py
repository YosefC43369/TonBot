"""Unit tests for TON address validation and normalization."""

from __future__ import annotations

import pytest

from ton.address import AddressValidationError, addresses_are_equal, parse_address


# A known valid TON mainnet address in different representations
_BOUNCEABLE = "EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOTggmf8"
_NON_BOUNCEABLE = "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOTgghIBX"


class TestParseAddress:
    def test_valid_bounceable_address(self) -> None:
        addr = parse_address(_BOUNCEABLE)
        assert addr.canonical  # has a value
        assert addr.raw.startswith("0:")
        assert addr.original == _BOUNCEABLE

    def test_valid_non_bounceable_address(self) -> None:
        addr = parse_address(_NON_BOUNCEABLE)
        assert addr.canonical
        assert addr.original == _NON_BOUNCEABLE

    def test_empty_string_raises(self) -> None:
        with pytest.raises(AddressValidationError, match="empty"):
            parse_address("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(AddressValidationError):
            parse_address("   ")

    def test_garbage_string_raises(self) -> None:
        with pytest.raises(AddressValidationError):
            parse_address("not_an_address_at_all!!!")

    def test_truncated_address_raises(self) -> None:
        with pytest.raises(AddressValidationError):
            parse_address("EQCD39VS5j")

    def test_strip_whitespace(self) -> None:
        addr = parse_address(f"  {_BOUNCEABLE}  ")
        assert addr.canonical  # whitespace stripped, still parses


class TestAddressEquality:
    def test_bounceable_and_non_bounceable_equal(self) -> None:
        """Different text representations of the same account must be equal."""
        # This only holds if the two test vectors are actually the same account
        # which they are for the well-known Elector contract address.
        # Skip rather than fail if pytoniq-core normalizes differently.
        a = parse_address(_BOUNCEABLE)
        b = parse_address(_NON_BOUNCEABLE)
        # Both should resolve to the same workchain:hash
        raw_a = a.raw.split(":")[1] if ":" in a.raw else a.raw
        raw_b = b.raw.split(":")[1] if ":" in b.raw else b.raw
        assert raw_a == raw_b

    def test_same_address_equal(self) -> None:
        assert addresses_are_equal(_BOUNCEABLE, _BOUNCEABLE)

    def test_invalid_address_in_equality_raises(self) -> None:
        with pytest.raises(AddressValidationError):
            addresses_are_equal("bad", _BOUNCEABLE)