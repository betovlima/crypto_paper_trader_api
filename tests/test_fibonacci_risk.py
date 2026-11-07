from __future__ import annotations

import pandas as pd
import pytest

from crypto_paper_trader_api.risk_management.fibonacci import (
    bullish_extension_price,
    bullish_retracement_price,
    calculate_bullish_fibonacci_stop,
    detect_latest_bullish_impulse,
)


def history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-07-20", periods=10, freq="30min", tz="UTC"),
            "high": [100, 99, 98, 97, 100, 103, 106, 109, 110, 109],
            "low": [98, 97, 96, 90, 95, 99, 102, 105, 107, 106],
            "atr_14": [5.0] * 10,
        }
    )


def test_fibonacci_levels_for_bullish_impulse() -> None:
    assert bullish_retracement_price(90, 110, 0.618) == pytest.approx(97.64)
    assert bullish_extension_price(90, 110, 1.272) == pytest.approx(115.44)


def test_detects_latest_confirmed_bullish_impulse_without_future_rows() -> None:
    impulse = detect_latest_bullish_impulse(
        history(), pivot_bars=2, min_impulse_atr=2.0
    )

    assert impulse is not None
    assert impulse.low_index == 3
    assert impulse.high_index == 8
    assert impulse.low_price == 90
    assert impulse.high_price == 110
    assert impulse.size_atr == 4.0


def test_fibonacci_stop_applies_atr_buffer() -> None:
    result = calculate_bullish_fibonacci_stop(
        history(),
        current_price=108,
        retracement_ratio=0.618,
        buffer_atr_multiplier=0.25,
        pivot_bars=2,
        min_impulse_atr=2.0,
    )

    assert result is not None
    assert result.retracement_price == pytest.approx(97.64)
    assert result.atr_buffer == pytest.approx(1.25)
    assert result.stop_price == pytest.approx(96.39)
