"""Regression tests for live protective exits and same-cycle order blocking."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.strategy_codes import CURRENT_HYBRID, EMA_CROSSOVER
from crypto_paper_trader_api.trading_profiles import (
    DEFAULT_TRADING_PROFILE,
    get_trading_profile,
)
from crypto_paper_trader_api.worker import TraderWorker


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
PRICE = 100.0
BID = 99.98


def _costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0005,
        spread_rate=0.0004,
        slippage_rate=0.0005,
        fee_source="TEST",
    )


def _account(account_id: int, strategy_code: str, *, open_position: bool = True,
             atr: float | None = 2.0) -> SimpleNamespace:
    return SimpleNamespace(
        id=account_id,
        strategy_code=strategy_code,
        has_open_position=open_position,
        last_atr_14=atr,
        last_event="PREVIOUS_EVENT",
        last_status_message="Previous status",
    )


def _experiment() -> Experiment:
    return Experiment(
        id="live-protection-test",
        market="BTCUSDT",
        trading_profile=DEFAULT_TRADING_PROFILE,
        execution_timeframe="30min",
        trend_timeframe="1hour",
        initial_capital=1000.0,
        scheduled_end_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _monitor(worker, accounts, events):
    session = Mock()
    experiment = _experiment()
    costs = _costs()
    blocked = worker._monitor_live_protective_exits(
        session=session,
        experiment=experiment,
        accounts=accounts,
        market_price=PRICE,
        best_bid=BID,
        costs=costs,
        profile=get_trading_profile(DEFAULT_TRADING_PROFILE),
        now=NOW,
        events=events,
    )
    return blocked, session, experiment, costs


def test_live_stop_refreshes_risk_before_selling_and_records_event() -> None:
    worker = TraderWorker(Settings())
    account = _account(7, CURRENT_HYBRID)
    events = {CURRENT_HYBRID: ("PRICE_UPDATE", "Market and portfolio data updated.")}
    order = []
    worker.broker.update_dynamic_risk_levels = Mock(side_effect=lambda **_: order.append("update"))
    worker._live_exit_reason = Mock(side_effect=lambda **_: order.append("check") or "LIVE_STOP_LOSS")
    worker.broker.sell = Mock(side_effect=lambda **_: order.append("sell"))

    blocked, _, _, costs = _monitor(worker, [account], events)

    assert order == ["update", "check", "sell"]
    assert blocked == {7}
    assert worker.broker.sell.call_args.kwargs["best_bid"] == BID
    assert worker.broker.sell.call_args.kwargs["decision_id"] is None
    assert worker.broker.sell.call_args.kwargs["reason"] == "LIVE_STOP_LOSS"
    assert worker.broker.update_dynamic_risk_levels.call_args.kwargs["atr"] == 2.0
    assert worker._live_exit_reason.call_args.kwargs["costs"] is costs
    assert events[CURRENT_HYBRID] == (
        "LIVE_STOP_LOSS",
        worker._event_message("LIVE_STOP_LOSS"),
    )
    assert account.last_event == "LIVE_STOP_LOSS"
    assert account.last_status_message == events[CURRENT_HYBRID][1]


def test_without_exit_signal_risk_refresh_does_not_sell_or_change_event() -> None:
    worker = TraderWorker(Settings())
    account = _account(7, CURRENT_HYBRID)
    expected = ("PRICE_UPDATE", "Market and portfolio data updated.")
    events = {CURRENT_HYBRID: expected}
    worker.broker.update_dynamic_risk_levels = Mock()
    worker._live_exit_reason = Mock(return_value=None)
    worker.broker.sell = Mock()

    blocked, _, _, _ = _monitor(worker, [account], events)

    assert blocked == set()
    worker.broker.update_dynamic_risk_levels.assert_called_once()
    worker._live_exit_reason.assert_called_once()
    worker.broker.sell.assert_not_called()
    assert events[CURRENT_HYBRID] == expected
    assert account.last_event == "PREVIOUS_EVENT"


def test_closed_or_atr_missing_positions_are_not_evaluated_for_protective_exit() -> None:
    worker = TraderWorker(Settings())
    accounts = [
        _account(1, CURRENT_HYBRID, open_position=False),
        _account(2, EMA_CROSSOVER, atr=None),
        _account(3, "OTHER", atr=0.0),
    ]
    events = {item.strategy_code: ("PRICE_UPDATE", "Updated") for item in accounts}
    worker.broker.update_dynamic_risk_levels = Mock()
    worker._live_exit_reason = Mock()
    worker.broker.sell = Mock()

    blocked, _, _, _ = _monitor(worker, accounts, events)

    assert blocked == set()
    worker.broker.update_dynamic_risk_levels.assert_not_called()
    worker._live_exit_reason.assert_not_called()
    worker.broker.sell.assert_not_called()
    assert all(event[0] == "PRICE_UPDATE" for event in events.values())


def test_multiple_protective_exits_mark_each_account_exactly_once() -> None:
    worker = TraderWorker(Settings())
    accounts = [_account(1, CURRENT_HYBRID), _account(2, EMA_CROSSOVER)]
    events = {item.strategy_code: ("PRICE_UPDATE", "Updated") for item in accounts}
    worker.broker.update_dynamic_risk_levels = Mock()
    worker._live_exit_reason = Mock(side_effect=["LIVE_STOP_LOSS", "LIVE_TAKE_PROFIT"])
    worker.broker.sell = Mock()

    blocked, _, _, _ = _monitor(worker, accounts, events)

    assert blocked == {1, 2}
    assert worker.broker.sell.call_count == 2
    assert [call.kwargs["account"].id for call in worker.broker.sell.call_args_list] == [1, 2]
    assert events[CURRENT_HYBRID][0] == "LIVE_STOP_LOSS"
    assert events[EMA_CROSSOVER][0] == "LIVE_TAKE_PROFIT"


def test_live_cycle_does_not_override_exit_with_same_cycle_candle_analysis() -> None:
    worker = TraderWorker(Settings())
    stopped = _account(7, CURRENT_HYBRID)
    watched = _account(8, EMA_CROSSOVER)
    session = Mock()
    worker.client.get_latest_price = AsyncMock(return_value=PRICE)
    worker._resolve_execution_costs = AsyncMock(return_value=_costs())
    worker._strategy_accounts = Mock(return_value=[stopped, watched])
    worker.broker.update_dynamic_risk_levels = Mock()
    worker._live_exit_reason = Mock(side_effect=["LIVE_STOP_LOSS", None])
    worker.broker.sell = Mock()
    worker._analysis_is_due = Mock(return_value=True)
    worker._run_candle_analysis = AsyncMock(return_value=(True, {
        CURRENT_HYBRID: ("ANALYSIS_BUY", "Must be ignored after live exit"),
        EMA_CROSSOVER: ("ANALYSIS_HOLD", "Candle analysis completed"),
    }))
    worker.broker.record_equity = Mock(return_value=SimpleNamespace(total_equity=900.0))
    worker._record_market_snapshot = Mock()
    worker._buy_and_hold_final_capital = Mock(return_value=1000.0)
    worker._mirror_hybrid_account = Mock()
    experiment = _experiment()

    asyncio.run(worker._run_live_cycle(session, experiment, NOW))

    assert worker._run_candle_analysis.call_args.kwargs["live_action_accounts"] == {7}
    assert stopped.last_event == "LIVE_STOP_LOSS"
    assert watched.last_event == "ANALYSIS_HOLD"
    assert worker.broker.sell.call_count == 1
    assert worker._record_market_snapshot.call_count == 2
    session.commit.assert_called_once()
