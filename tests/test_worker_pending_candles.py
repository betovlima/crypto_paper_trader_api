"""Regression checks for chronological selection of closed candles."""

from datetime import datetime, timezone

import pandas as pd
import pytest

from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.worker import TraderWorker


def _utc(day_hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 20, day_hour, minute, tzinfo=timezone.utc)


def _experiment(
    started_at: datetime,
    last_processed: datetime | None = None,
) -> Experiment:
    return Experiment(
        id="test-pending-candles",
        market="BTCUSDT",
        execution_timeframe="1hour",
        started_at=started_at,
        last_processed_candle_at=last_processed,
    )


def _indicators() -> pd.DataFrame:
    timestamps = pd.date_range("2026-07-20 13:00", periods=5, freq="h", tz="UTC")
    required = (
        "ema_9", "ema_20", "ema_50", "ema_200", "rsi_14",
        "atr_14", "adx_14", "relative_volume", "volatility_20",
    )
    frame = pd.DataFrame({"timestamp": timestamps})
    for column in required:
        frame[column] = 1.0
    return frame


def test_initial_analysis_selects_only_candles_closed_after_start() -> None:
    worker = object.__new__(TraderWorker)
    pending, baseline = worker._select_pending_candle_indices(
        _experiment(_utc(16, 12)), _indicators()
    )

    assert pending == [3, 4]
    assert baseline is False


def test_initial_dashboard_uses_last_closed_candle_without_a_post_start_candle() -> None:
    worker = object.__new__(TraderWorker)
    pending, baseline = worker._select_pending_candle_indices(
        _experiment(_utc(19, 10)), _indicators()
    )

    assert pending == [4]
    assert baseline is True


def test_recovery_never_reprocesses_the_last_processed_candle() -> None:
    worker = object.__new__(TraderWorker)
    pending, baseline = worker._select_pending_candle_indices(
        _experiment(_utc(14, 30), last_processed=_utc(15)), _indicators()
    )

    assert pending == [3, 4]
    assert baseline is False


def test_up_to_date_experiment_has_no_pending_candles() -> None:
    worker = object.__new__(TraderWorker)
    pending, baseline = worker._select_pending_candle_indices(
        _experiment(_utc(14, 30), last_processed=_utc(17)), _indicators()
    )

    assert pending == []
    assert baseline is False


def test_invalid_indicators_are_filtered_before_pending_selection() -> None:
    worker = object.__new__(TraderWorker)
    frame = _indicators()
    frame.loc[3, "rsi_14"] = float("nan")
    pending, baseline = worker._select_pending_candle_indices(
        _experiment(_utc(16, 12)), frame
    )

    assert pending == [4]
    assert baseline is False


def test_missing_complete_indicators_raise_original_error() -> None:
    worker = object.__new__(TraderWorker)
    frame = _indicators()
    frame["atr_14"] = float("nan")

    with pytest.raises(
        ValueError, match="Not enough complete candles for strategy analysis"
    ):
        worker._select_pending_candle_indices(_experiment(_utc(16)), frame)
