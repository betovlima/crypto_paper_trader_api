"""Regression coverage for the snapshot extraction from TraderWorker."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from crypto_paper_trader_api.decision_snapshot_builder import build_decision_snapshot
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.strategy_codes import EMA_PULLBACK
from crypto_paper_trader_api.trading_profiles import DEFAULT_TRADING_PROFILE, get_trading_profile
from crypto_paper_trader_api.worker import TraderWorker


class _NoSignalDecision:
    def __getattr__(self, _name: str):
        return None


def test_worker_snapshot_delegation_preserves_values() -> None:
    experiment = Experiment(id="snapshot-test", trading_profile=DEFAULT_TRADING_PROFILE)
    account = StrategyAccount(
        id=123,
        experiment_id=experiment.id,
        strategy_code=EMA_PULLBACK,
    )
    profile = get_trading_profile(experiment.trading_profile)
    execution_data = {
        "close": 105.0,
        "high": 106.0,
        "low": 104.0,
        "ema_9": 103.0,
        "ema_20": 102.0,
        "ema_50": 101.0,
        "ema_200": 99.0,
        "rsi_14": 55.0,
        "atr_14": 2.0,
        "adx_14": 22.0,
        "average_volume_20": 500.0,
        "relative_volume": 1.2,
        "volatility_20": 0.01,
        "return_1": 0.01,
        "return_3": 0.03,
        "return_6": 0.05,
    }
    for period in (profile.fast_ema_period, profile.slow_ema_period, profile.regime_ema_period):
        execution_data[f"ema_{period}"] = float(period)
    trend_data = {
        "close": 105.0,
        "ema_20": 102.0,
        "ema_50": 101.0,
        "ema_200": 99.0,
        "rsi_14": 53.0,
        "adx_14": 23.0,
    }
    costs = SimpleNamespace(
        maker_fee_rate=0.001,
        taker_fee_rate=0.001,
        spread_rate=0.001,
        slippage_rate=0.001,
        estimated_round_trip_rate=0.004,
    )
    args = (
        experiment,
        account,
        datetime(2026, 11, 7, tzinfo=timezone.utc),
        pd.Series(execution_data),
        pd.Series(trend_data),
        object(),  # Non-hybrid strategies do not use prediction metrics.
        costs,
        0.02,
        "CASH",
        _NoSignalDecision(),
    )

    direct = build_decision_snapshot(*args)
    delegated = TraderWorker._build_decision_snapshot(None, *args)

    for snapshot in (direct, delegated):
        assert snapshot.strategy_code == EMA_PULLBACK
        assert snapshot.strategy_account_id == account.id
        assert snapshot.market_price == 105.0
        assert snapshot.required_gross_return == 0.02
        assert snapshot.position_before == "CASH"
        assert snapshot.estimated_round_trip_cost_rate == 0.004

    assert delegated.market_price == direct.market_price
    assert delegated.candle_timestamp == direct.candle_timestamp
    assert delegated.strategy_account_id == direct.strategy_account_id
