"""Regression tests for recording decisions and executing paper orders.

The fixtures isolate the worker execution phase so no live market data is used.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.multi_strategy import StrategyDecision
from crypto_paper_trader_api.strategy_codes import CURRENT_HYBRID
from crypto_paper_trader_api.trading_profiles import DEFAULT_TRADING_PROFILE, get_trading_profile
from crypto_paper_trader_api.worker import TraderWorker, _CandleExecutionContext


def _inputs(is_recovered: bool = False):
    worker = TraderWorker(Settings())
    session = Mock()
    snapshot = SimpleNamespace(
        id=42,
        action_executed=False,
        decision_reason="Original decision",
        is_recovered=False,
        recovery_note=None,
    )
    worker._build_decision_snapshot = Mock(return_value=snapshot)
    account = SimpleNamespace(
        id=7,
        strategy_code=CURRENT_HYBRID,
        has_open_position=False,
        last_event=None,
        last_status_message=None,
    )
    now = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    costs = ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0005,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="TEST",
    )
    context = _CandleExecutionContext(
        experiment=Experiment(id="test", trading_profile=DEFAULT_TRADING_PROFILE),
        candle_timestamp=now,
        candle_end=now + timedelta(minutes=30),
        execution_row=pd.Series({"close": 100.0, "high": 101.0, "low": 99.0}),
        trend_row=pd.Series({"close": 100.0}),
        prediction=Mock(),
        costs=costs,
        profile=get_trading_profile(DEFAULT_TRADING_PROFILE),
        close_price=100.0,
        historical_bid=99.99,
        historical_ask=100.01,
        atr=2.0,
        is_recovered=is_recovered,
    )
    return worker, session, snapshot, account, context


def _decision(signal: str) -> StrategyDecision:
    return StrategyDecision(
        technical_signal=signal,
        model_signal=signal,
        final_signal=signal,
        technical_confirmations=0,
        reason="Test signal",
    )


def _execute(worker, session, account, context, decision, *, existing=None, blocked=None, recovered_count=0):
    events = existing if existing is not None else {}
    count = worker._record_and_execute_candle_decisions(
        session=session,
        accounts=[account],
        decisions={account.strategy_code: decision},
        context=context,
        live_action_accounts=blocked or set(),
        recovered_action_accounts=set(),
        events=events,
        recovered_trade_count=recovered_count,
    )
    return events, count


def test_buy_is_executed_after_snapshot_flush() -> None:
    worker, session, snapshot, account, context = _inputs()
    order = []
    session.add.side_effect = lambda _: order.append("snapshot_added")
    session.flush.side_effect = lambda: order.append("snapshot_flushed")
    worker.broker.buy = Mock(side_effect=lambda **kwargs: order.append("paper_buy"))

    events, count = _execute(worker, session, account, context, _decision("BUY"))

    assert order == ["snapshot_added", "snapshot_flushed", "paper_buy"]
    assert worker.broker.buy.call_args.kwargs["decision_id"] == 42
    assert worker.broker.buy.call_args.kwargs["best_ask"] == 100.01
    assert snapshot.action_executed is True
    assert snapshot.is_recovered is False
    assert events[CURRENT_HYBRID][0] == "ANALYSIS_BUY"
    assert account.last_event == "ANALYSIS_BUY"
    assert count == 0


def test_recovered_sale_updates_trade_count_and_reason() -> None:
    worker, session, snapshot, account, context = _inputs(is_recovered=True)
    account.has_open_position = True
    worker.broker.sell = Mock()

    events, count = _execute(worker, session, account, context, _decision("SELL"), recovered_count=2)

    worker.broker.sell.assert_called_once()
    assert worker.broker.sell.call_args.kwargs["is_recovered"] is True
    assert worker.broker.sell.call_args.kwargs["decision_id"] == 42
    assert snapshot.action_executed is True
    assert snapshot.is_recovered is True
    assert snapshot.recovery_note == "Closed candle replayed after worker downtime."
    assert count == 3
    assert events[CURRENT_HYBRID][0] == "RECOVERED_EXIT"
    assert account.last_event == "RECOVERED_EXIT"


def test_rejected_purchase_keeps_snapshot_and_hold_event() -> None:
    worker, session, snapshot, account, context = _inputs()
    worker.broker.buy = Mock(side_effect=ValueError("insufficient capital"))

    events, count = _execute(worker, session, account, context, _decision("BUY"))

    assert snapshot.action_executed is False
    assert snapshot.decision_reason == "Original decision; buy_skipped=insufficient capital"
    assert events[CURRENT_HYBRID] == ("ANALYSIS_HOLD", "Simulated purchase skipped: insufficient capital")
    assert account.last_event == "ANALYSIS_HOLD"
    assert count == 0


def test_previously_processed_account_does_not_execute_twice() -> None:
    worker, session, snapshot, account, context = _inputs()
    worker.broker.buy = Mock()
    events, count = _execute(
        worker, session, account, context, _decision("BUY"), blocked={account.id}
    )

    worker.broker.buy.assert_not_called()
    session.add.assert_called_once_with(snapshot)
    session.flush.assert_called_once()
    assert snapshot.action_executed is False
    assert events[CURRENT_HYBRID][0] == "ANALYSIS_BUY"
    assert count == 0


def test_historical_exit_takes_precedence_over_subsequent_hold() -> None:
    worker, session, snapshot, account, context = _inputs(is_recovered=True)
    worker.broker.buy = Mock()
    worker.broker.sell = Mock()
    events = {CURRENT_HYBRID: ("RECOVERED_EXIT", "Historical exit reconstructed")}
    count = worker._record_and_execute_candle_decisions(
        session=session,
        accounts=[account],
        decisions={CURRENT_HYBRID: _decision("HOLD")},
        context=context,
        live_action_accounts=set(),
        recovered_action_accounts={account.id},
        events=events,
        recovered_trade_count=1,
    )

    worker.broker.buy.assert_not_called()
    worker.broker.sell.assert_not_called()
    assert events[CURRENT_HYBRID] == ("RECOVERED_EXIT", "Historical exit reconstructed")
    assert account.last_event == "RECOVERED_EXIT"
    assert snapshot.action_executed is False
    assert count == 1
