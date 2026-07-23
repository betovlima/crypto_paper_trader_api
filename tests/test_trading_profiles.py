from __future__ import annotations

import pytest

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.trading_profiles import (
    BALANCED_INTRADAY,
    CONSERVATIVE_SWING,
    FAST_INTRADAY,
    get_trading_profile,
    list_trading_profiles,
)
from crypto_paper_trader_api.worker import create_experiment_record


def test_profiles_expose_distinct_timeframes_and_ema_structures() -> None:
    swing = get_trading_profile(CONSERVATIVE_SWING)
    balanced = get_trading_profile(BALANCED_INTRADAY)
    fast = get_trading_profile(FAST_INTRADAY)

    assert (swing.decision_timeframe, swing.trend_timeframe) == ("1hour", "4hour")
    assert (swing.fast_ema_period, swing.slow_ema_period, swing.regime_ema_period) == (
        20,
        50,
        200,
    )
    assert (balanced.decision_timeframe, balanced.trend_timeframe) == ("30min", "1hour")
    assert (balanced.fast_ema_period, balanced.slow_ema_period, balanced.regime_ema_period) == (
        9,
        21,
        50,
    )
    assert (fast.decision_timeframe, fast.trend_timeframe) == ("15min", "1hour")
    assert (fast.fast_ema_period, fast.slow_ema_period, fast.regime_ema_period) == (
        5,
        13,
        34,
    )
    assert len(list_trading_profiles()) == 3


def test_experiment_keeps_selected_profile_and_resolved_timeframes() -> None:
    settings = Settings()
    profile = get_trading_profile(BALANCED_INTRADAY)
    experiment = create_experiment_record(
        market="BTCUSDT",
        execution_timeframe=profile.decision_timeframe,
        trend_timeframe=profile.trend_timeframe,
        duration_hours=24,
        initial_capital=1000,
        settings=settings,
        trading_profile=profile.code,
    )

    assert experiment.trading_profile == BALANCED_INTRADAY
    assert experiment.execution_timeframe == "30min"
    assert experiment.trend_timeframe == "1hour"


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported trading profile"):
        get_trading_profile("UNKNOWN_PROFILE")
