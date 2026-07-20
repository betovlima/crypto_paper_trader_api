from __future__ import annotations

from datetime import datetime, timedelta, timezone

from coinex_paper_trader.config import Settings
from coinex_paper_trader.execution_costs import ExecutionCosts
from coinex_paper_trader.models import StrategyAccount
from coinex_paper_trader.worker import TraderWorker


def worker_without_client(settings: Settings) -> TraderWorker:
    return TraderWorker(settings)


def account_with_position() -> StrategyAccount:
    return StrategyAccount(
        experiment_id="experiment",
        strategy_code="CURRENT_HYBRID",
        display_name="Current Hybrid",
        initial_capital=1000,
        cash_balance=0,
        asset_quantity=0.01,
        average_entry_price=100_000,
        entry_time=datetime.now(timezone.utc) - timedelta(minutes=5),
        stop_loss_price=98_000,
        take_profit_price=105_000,
        max_equity=1000,
    )


def costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="TEST",
    )


def test_live_stop_loss_is_checked_between_candles() -> None:
    settings = Settings(max_daily_loss_pct=0.99)
    worker = worker_without_client(settings)
    account = account_with_position()

    reason = worker._live_exit_reason(
        account=account,
        market_price=97_950,
        best_bid=97_900,
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert reason == "LIVE_STOP_LOSS"


def test_live_take_profit_is_checked_between_candles() -> None:
    settings = Settings(max_daily_loss_pct=0.99)
    worker = worker_without_client(settings)
    account = account_with_position()

    reason = worker._live_exit_reason(
        account=account,
        market_price=105_150,
        best_bid=105_100,
        costs=costs(),
        now=datetime.now(timezone.utc),
    )

    assert reason == "LIVE_TAKE_PROFIT"
