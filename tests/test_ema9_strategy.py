from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_strategy import Ema9Setup91Strategy
from crypto_paper_trader_api.strategy_codes import EMA9_SETUP_91, EMA9_SETUP_91_COST_AWARE


def account(code: str) -> StrategyAccount:
    return StrategyAccount(
        experiment_id="experiment",
        strategy_code=code,
        display_name=code,
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
        setup_status="IDLE",
    )


def costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        spread_rate=0.0001,
        slippage_rate=0.0005,
        fee_source="TEST",
    )


def row(ema9: float, high: float = 101, low: float = 99, close: float = 100) -> pd.Series:
    return pd.Series({"ema_9": ema9, "high": high, "low": low, "close": close})


def test_ema9_down_to_up_reversal_arms_setup() -> None:
    strategy = Ema9Setup91Strategy(Settings(), cost_aware=False)
    item = account(EMA9_SETUP_91)

    decision = strategy.analyze_candle(
        account=item,
        current_row=row(99.8, high=101, low=99),
        previous_row=row(99.5),
        previous_previous_row=row(100.0),
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert decision.setup_status == "ARMED"
    assert item.setup_status == "ARMED"
    assert item.entry_trigger_price == 101
    assert item.initial_setup_stop_price == 99


def test_fees_do_not_reject_a_valid_ema9_setup() -> None:
    settings = Settings()
    strategy = Ema9Setup91Strategy(settings, cost_aware=True)
    item = account(EMA9_SETUP_91_COST_AWARE)

    decision = strategy.analyze_candle(
        account=item,
        current_row=row(99.8, high=100.01, low=99.79, close=100),
        previous_row=row(99.5),
        previous_previous_row=row(100.0),
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert decision.setup_status == "ARMED"
    assert item.setup_status == "ARMED"
    assert "fees_are_accounting_only=true" in decision.reason



def test_strict_reversal_without_cross_does_not_arm_setup() -> None:
    strategy = Ema9Setup91Strategy(Settings(), mode=Ema9Setup91Strategy.CLASSIC)
    item = account(EMA9_SETUP_91_COST_AWARE)

    decision = strategy.analyze_candle(
        account=item,
        current_row=row(99.8, high=101.0, low=99.9, close=100.5),
        previous_row=row(99.5),
        previous_previous_row=row(100.0),
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert decision.setup_status == "IDLE"
    assert item.setup_status == "IDLE"
    assert "strict_reversal_without_ema9_cross" in decision.reason


def test_classic_variant_arms_exit_below_bearish_reversal_candle() -> None:
    strategy = Ema9Setup91Strategy(Settings(), mode=Ema9Setup91Strategy.CLASSIC)
    item = account(EMA9_SETUP_91_COST_AWARE)
    item.asset_quantity = 1.0
    item.cash_balance = 0.0
    item.stop_loss_price = 95.0
    item.setup_status = "IN_POSITION"

    decision = strategy.analyze_candle(
        account=item,
        current_row=row(100.0, high=102.0, low=98.0, close=99.0),
        previous_row=row(100.5),
        previous_previous_row=row(100.0),
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert decision.setup_status == "EXIT_ARMED"
    assert decision.final_signal == "HOLD"
    assert item.exit_trigger_price == 98.0
    assert item.trailing_stop_price is None


def test_trend_follower_raises_stop_to_latest_closed_candle_low() -> None:
    strategy = Ema9Setup91Strategy(Settings(), mode=Ema9Setup91Strategy.TREND_FOLLOWER)
    item = account(EMA9_SETUP_91_COST_AWARE)
    item.asset_quantity = 1.0
    item.cash_balance = 0.0
    item.stop_loss_price = 95.0
    item.setup_status = "IN_POSITION"

    decision = strategy.analyze_candle(
        account=item,
        current_row=row(101.0, high=104.0, low=99.0, close=103.0),
        previous_row=row(100.5),
        previous_previous_row=row(100.0),
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert decision.final_signal == "HOLD"
    assert item.trailing_stop_price == 99.0
    assert item.stop_loss_price == 95.0
    assert item.stop_management_mode == "TREND_FOLLOWER"
