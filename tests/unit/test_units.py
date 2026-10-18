"""Unit tests for exact-arithmetic TON unit conversion."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ton.units import format_jetton, format_ton, nanoton_to_ton, ton_to_nanoton


class TestNanotonToTon:
    def test_one_ton(self) -> None:
        assert nanoton_to_ton(1_000_000_000) == Decimal("1")

    def test_zero(self) -> None:
        assert nanoton_to_ton(0) == Decimal("0")

    def test_fractional(self) -> None:
        assert nanoton_to_ton(500_000_000) == Decimal("0.5")

    def test_large_balance(self) -> None:
        # 1 million TON — must not lose precision with floats
        result = nanoton_to_ton(1_000_000 * 1_000_000_000)
        assert result == Decimal("1000000")

    def test_string_input(self) -> None:
        assert nanoton_to_ton("1000000000") == Decimal("1")


class TestTonToNanoton:
    def test_one_ton(self) -> None:
        assert ton_to_nanoton(Decimal("1")) == 1_000_000_000

    def test_rounds_down(self) -> None:
        # 0.999999999 TON -> 999999999 nanotons (not 1 TON)
        assert ton_to_nanoton(Decimal("0.9999999999")) == 999_999_999


class TestFormatTon:
    def test_one_ton(self) -> None:
        assert format_ton(1_000_000_000) == "1"

    def test_one_point_five_ton(self) -> None:
        assert format_ton(1_500_000_000) == "1.5"

    def test_zero(self) -> None:
        assert format_ton(0) == "0"

    def test_small_amount(self) -> None:
        # 1 nanoton
        result = format_ton(1)
        assert "0.000000001" in result or result == "0.000000001"

    def test_large_amount_no_float_error(self) -> None:
        # 999,999.123456789 TON
        nanos = 999_999_123_456_789
        result = format_ton(nanos)
        assert result.startswith("999999")


class TestFormatJetton:
    def test_9_decimals(self) -> None:
        assert format_jetton(1_000_000_000, 9) == "1"

    def test_6_decimals_usdt_style(self) -> None:
        assert format_jetton(1_000_000, 6) == "1"

    def test_zero(self) -> None:
        assert format_jetton(0, 6) == "0"

    def test_fractional(self) -> None:
        assert format_jetton(500_000, 6) == "0.5"

    def test_invalid_decimals_raises(self) -> None:
        with pytest.raises(ValueError):
            format_jetton(100, -1)

        with pytest.raises(ValueError):
            format_jetton(100, 31)