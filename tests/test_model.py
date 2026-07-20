from __future__ import annotations

import numpy as np
import pandas as pd

from crypto_paper_trader_api.indicators import add_indicators
from crypto_paper_trader_api.ml_model import XGBoostDirectionModel


def test_model_returns_a_probability() -> None:
    rows = 420
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC")
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0008, 0.004, rows)
    close = 100 * np.cumprod(1 + returns)
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close * (1 - rng.normal(0, 0.001, rows)),
            "high": close * 1.003,
            "low": close * 0.997,
            "close": close,
            "volume": rng.integers(900, 1800, rows),
            "value": close * rng.integers(900, 1800, rows),
        }
    )
    indicators = add_indicators(frame)
    model = XGBoostDirectionModel(0.001, 0.55, 0.42)
    result = model.fit_predict(indicators)

    assert 0 <= result.upward_probability <= 1
    assert abs(result.upward_probability + result.downward_probability - 1) < 1e-9
    assert result.training_rows >= 120
