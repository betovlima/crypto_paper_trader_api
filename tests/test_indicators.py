from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_paper_trader_api.indicators import FEATURE_COLUMNS, add_indicators, latest_complete_row


def synthetic_candles(rows: int = 320) -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC")
    base = 100 + np.linspace(0, 12, rows) + np.sin(np.arange(rows) / 8)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": base - 0.15,
            "high": base + 0.50,
            "low": base - 0.60,
            "close": base,
            "volume": 1000 + np.arange(rows) * 2,
            "value": (1000 + np.arange(rows) * 2) * base,
        }
    )


def test_all_indicators_are_available_after_warmup() -> None:
    result = add_indicators(synthetic_candles())
    latest = latest_complete_row(result)

    assert latest["ema_20"] > 0
    assert latest["ema_50"] > 0
    assert latest["ema_200"] > 0
    assert 0 <= latest["rsi_14"] <= 100
    assert latest["atr_14"] > 0
    assert latest["relative_volume"] > 0
    assert all(pd.notna(latest[column]) for column in FEATURE_COLUMNS)
