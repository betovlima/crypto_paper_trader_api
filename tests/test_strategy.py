from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.ml_model import ModelPrediction
from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.strategy import HybridPaperStrategy


def prediction(expected_return: float = 0.02) -> ModelPrediction:
    return ModelPrediction(
        upward_probability=0.70,
        downward_probability=0.30,
        expected_return=expected_return,
        model_signal="BUY",
        accuracy=None,
        precision=None,
        recall=None,
        roc_auc=None,
        training_rows=200,
        top_features_json="[]",
    )


def bullish_row(low: float = 99, high: float = 103) -> pd.Series:
    return pd.Series(
        {
            "close": 101,
            "high": high,
            "low": low,
            "ema_20": 100,
            "ema_50": 99,
            "ema_200": 90,
            "rsi_14": 58,
            "atr_14": 2,
            "adx_14": 25,
            "relative_volume": 1.2,
        }
    )


def trend_row() -> pd.Series:
    return pd.Series(
        {
            "close": 101,
            "ema_20": 100,
            "ema_50": 98,
            "ema_200": 90,
            "rsi_14": 55,
            "adx_14": 24,
        }
    )


def open_experiment() -> Experiment:
    now = datetime.now(timezone.utc)
    return Experiment(
        id="strategy-test",
        market="BTCUSDT",
        execution_timeframe="15min",
        trend_timeframe="1hour",
        duration_hours=24,
        status="RUNNING",
        started_at=now - timedelta(hours=1),
        scheduled_end_at=now + timedelta(hours=23),
        initial_capital=1000,
        cash_balance=50,
        asset_quantity=9,
        average_entry_price=100,
        entry_time=now - timedelta(hours=1),
        initial_risk_per_unit=2,
        stop_loss_price=98,
        take_profit_price=102,
        trailing_stop_price=None,
        last_price=101,
        vip_level="API_SPOT",
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        fee_source="TEST",
        last_spread_rate=0.0002,
        average_spread_rate=0.0002,
        spread_observations=1,
        total_fees=0,
        total_spread_cost=0,
        total_slippage_cost=0,
        realized_pnl=0,
        max_equity=1000,
        max_drawdown_pct=0,
        consecutive_losses=0,
    )


def test_stop_is_conservatively_prioritized_when_stop_and_target_touch_same_candle() -> None:
    settings = Settings(data_dir="./test-data")
    strategy = HybridPaperStrategy(settings)
    costs = ExecutionCosts(0.002, 0.002, 0.0002, 0.0005, "TEST")
    experiment = open_experiment()

    decision = strategy.decide(
        experiment=experiment,
        execution_row=bullish_row(low=97, high=103),
        trend_row=trend_row(),
        prediction=prediction(),
        costs=costs,
        now=datetime.now(timezone.utc),
    )

    assert decision.final_signal == "SELL"
    assert decision.execution_reference_price == 98
    assert "protective_stop_triggered" in decision.reason


def test_fees_do_not_block_a_valid_hybrid_entry() -> None:
    settings = Settings(data_dir="./test-data")
    strategy = HybridPaperStrategy(settings)
    costs = ExecutionCosts(0.002, 0.002, 0.0002, 0.0005, "TEST")
    experiment = open_experiment()
    experiment.asset_quantity = 0
    experiment.cash_balance = 1000
    experiment.average_entry_price = None
    experiment.entry_time = None

    decision = strategy.decide(
        experiment=experiment,
        execution_row=bullish_row(),
        trend_row=trend_row(),
        prediction=prediction(expected_return=0.003),
        costs=costs,
        now=datetime.now(timezone.utc),
    )

    assert decision.final_signal == "BUY"
    assert costs.estimated_round_trip_rate == 0.0052
    assert "fees_are_accounting_only=true" in decision.reason
