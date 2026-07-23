from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from crypto_paper_trader_api.adaptive_pattern_analysis import (
    CandlestickPatternDetector,
    TimeSeriesPatternAnalyzer,
)
from crypto_paper_trader_api.indicators import add_indicators
from crypto_paper_trader_api.schemas import ExperimentCreate


def test_intraday_decision_timeframe_rejects_values_below_thirty_minutes() -> None:
    with pytest.raises(ValueError, match="minimum intraday decision timeframe is 30 minutes"):
        ExperimentCreate(
            market="SOLUSDT",
            execution_timeframe="15min",
            trend_timeframe="1hour",
        )

    request = ExperimentCreate(
        market="SOLUSDT",
        execution_timeframe="30min",
        trend_timeframe="1hour",
    )
    assert request.execution_timeframe == "30min"
    assert request.trend_timeframe == "1hour"


def test_trend_timeframe_cannot_be_shorter_than_decision_timeframe() -> None:
    with pytest.raises(ValueError, match="trend timeframe must be equal to or greater"):
        ExperimentCreate(
            market="SOLUSDT",
            execution_timeframe="4hour",
            trend_timeframe="1hour",
        )


def test_candlestick_detector_recognizes_shooting_star() -> None:
    frame = pd.DataFrame(
        [
            {"open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5},
            {"open": 100.5, "high": 105.0, "low": 100.45, "close": 100.8},
        ]
    )
    patterns = CandlestickPatternDetector.current_patterns(frame)
    assert "SHOOTING_STAR" in patterns


def test_pattern_analyzer_uses_only_selected_asset_history() -> None:
    count = 1200
    timestamps = pd.date_range("2024-01-01", periods=count, freq="1h", tz="UTC")
    steps = np.arange(count)
    base = 100 + np.sin(steps / 12) * 2 + steps * 0.005
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base + np.sin(steps / 5) * 0.2,
            "volume": 1000 + np.cos(steps / 7) * 100,
        }
    )
    indicators = add_indicators(frame)

    summary = TimeSeriesPatternAnalyzer().analyze(
        market="SOLUSDT",
        execution_timeframe="1hour",
        trend_timeframe="4hour",
        frame=indicators,
        pattern_window_candles=24,
        horizon_candles=1,
        neighbor_count=32,
        max_history_candles=10000,
        estimated_round_trip_cost=0.001,
    )

    assert summary.status == "READY"
    assert summary.market == "SOLUSDT"
    assert summary.execution_timeframe == "1hour"
    assert summary.trend_timeframe == "4hour"
    assert summary.history_candles_analyzed == count
    assert summary.similar_pattern_count == 32
    assert summary.expected_next_return is not None
    assert summary.forecast_horizon_candles == 1
    assert summary.range_state in {"RANGE_BOUND", "RANGE_LIKELY", "NOT_RANGE_BOUND"}
    assert summary.range_bound_score is not None
    assert summary.range_support is not None
    assert summary.range_resistance is not None


def test_sideways_indicators_expose_range_bound_evidence() -> None:
    count = 500
    timestamps = pd.date_range("2025-01-01", periods=count, freq="1h", tz="UTC")
    steps = np.arange(count)
    close = 100.0 + np.sin(steps / 3.0) * 0.65 + np.sin(steps / 11.0) * 0.25
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - np.sin(steps / 2.0) * 0.08,
            "high": close + 0.42,
            "low": close - 0.42,
            "close": close,
            "volume": 1000.0 + np.cos(steps / 5.0) * 40.0,
        }
    )
    indicators = add_indicators(frame)
    latest = indicators.dropna(subset=["range_bound_score"]).iloc[-1]

    assert latest["range_bound_score"] >= 50
    assert 0 <= latest["range_position_24"] <= 1
    assert np.isfinite(latest["bollinger_zscore_20"])
    assert np.isfinite(latest["stochastic_k_14"])


def test_candlestick_detector_scans_the_configured_recent_window() -> None:
    frame = pd.DataFrame(
        [
            {"open": 100.0, "high": 100.7, "low": 95.0, "close": 100.5},
            {"open": 100.5, "high": 101.2, "low": 100.1, "close": 100.9},
        ]
    )

    assert "HAMMER" not in CandlestickPatternDetector.current_patterns(frame)
    assert "HAMMER" in CandlestickPatternDetector.patterns_in_window(frame)
