"""Regression tests for finalizing strategy accounts and terminal portfolios."""

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


FINISHED_AT = datetime(2026, 11, 7, 15, 30, tzinfo=timezone.utc)


def _costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.0,
        taker_fee_rate=0.0005,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="TEST",
    )


def _experiment() -> Experiment:
    return Experiment(
        id="finalize-accounts",
        market="BTCUSDT",
        trading_profile=DEFAULT_TRADING_PROFILE,
        execution_timeframe="30min",
        trend_timeframe="1hour",
        initial_capital=1000.0,
        first_market_price=100.0,
        last_price=99.0,
    )


def _account(identifier: int, code: str, has_open_position: bool):
    return SimpleNamespace(
        id=identifier,
        strategy_code=code,
        has_open_position=has_open_position,
        final_capital=None,
        status="RUNNING",
        last_event="PRICE_UPDATE",
        last_status_message="Old status",
    )


def _finalize_accounts(worker, session, experiment, accounts, *, status="FINISHED",
                       close_open_positions=True, market_price=103.0,
                       best_bid=102.98, best_ask=103.02, costs=None):
    return worker._finalize_strategy_accounts(
        session=session,
        experiment=experiment,
        accounts=accounts,
        finished_at=FINISHED_AT,
        final_status=status,
        close_open_positions=close_open_positions,
        market_price=market_price,
        best_bid=best_bid,
        best_ask=best_ask,
        costs=costs if costs is not None else _costs(),
        profile=get_trading_profile(DEFAULT_TRADING_PROFILE),
    )


def test_open_position_sold_before_equity_and_terminal_snapshot() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    experiment = _experiment()
    account = _account(1, CURRENT_HYBRID, True)
    order = []
    equity = SimpleNamespace(total_equity=1125.75)
    worker.broker.sell = Mock(side_effect=lambda **_: order.append("sell"))
    worker.broker.record_equity = Mock(
        side_effect=lambda **_: order.append("equity") or equity
    )
    worker._record_market_snapshot = Mock(
        side_effect=lambda **_: order.append("snapshot")
    )

    _finalize_accounts(worker, session, experiment, [account])

    assert order == ["sell", "equity", "snapshot"]
    sell_args = worker.broker.sell.call_args.kwargs
    assert sell_args["reason"] == "FORCED_CLOSE_AT_EXPERIMENT_END"
    assert sell_args["decision_id"] is None
    assert sell_args["executed_at"] == FINISHED_AT
    assert sell_args["best_bid"] == 102.98
    assert sell_args["account"] is account
    assert account.final_capital == 1125.75
    assert account.status == "FINISHED"
    assert account.last_event == "FINISHED"
    assert account.last_status_message == "The experiment was finalized."
    snapshot_args = worker._record_market_snapshot.call_args.kwargs
    assert snapshot_args["equity"] is equity
    assert snapshot_args["event_type"] == "FINISHED"
    assert snapshot_args["status_message"] == "The experiment was finalized and consolidated."


def test_stop_without_closing_position_preserves_holdings_and_records_equity() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    account = _account(1, CURRENT_HYBRID, True)
    worker.broker.sell = Mock()
    worker.broker.record_equity = Mock(
        return_value=SimpleNamespace(total_equity=1041.25)
    )
    worker._record_market_snapshot = Mock()

    _finalize_accounts(
        worker, session, _experiment(), [account],
        status="STOPPED", close_open_positions=False,
    )

    worker.broker.sell.assert_not_called()
    worker.broker.record_equity.assert_called_once()
    worker._record_market_snapshot.assert_called_once()
    assert account.final_capital == 1041.25
    assert account.status == "STOPPED"
    assert account.last_event == "STOPPED"
    assert account.last_status_message == "The experiment was stopped and its data was preserved."
    assert worker._record_market_snapshot.call_args.kwargs["status_message"] == (
        "The experiment was stopped and consolidated without deleting data."
    )


def test_flat_account_is_never_sold_when_forced_closure_is_enabled() -> None:
    worker = TraderWorker(Settings())
    account = _account(2, EMA_CROSSOVER, False)
    worker.broker.sell = Mock()
    worker.broker.record_equity = Mock(
        return_value=SimpleNamespace(total_equity=1004.0)
    )
    worker._record_market_snapshot = Mock()

    _finalize_accounts(worker, Mock(), _experiment(), [account])

    worker.broker.sell.assert_not_called()
    assert account.final_capital == 1004.0
    assert account.status == "FINISHED"
    worker._record_market_snapshot.assert_called_once()


def test_multiple_accounts_are_finalized_in_original_iteration_order() -> None:
    worker = TraderWorker(Settings())
    accounts = [
        _account(1, CURRENT_HYBRID, True),
        _account(2, EMA_CROSSOVER, False),
    ]
    calls = []
    worker.broker.sell = Mock(
        side_effect=lambda **kwargs: calls.append(("sell", kwargs["account"].id))
    )
    worker.broker.record_equity = Mock(
        side_effect=lambda **kwargs: (
            calls.append(("equity", kwargs["account"].id))
            or SimpleNamespace(total_equity=1000.0 + kwargs["account"].id)
        )
    )
    worker._record_market_snapshot = Mock(
        side_effect=lambda **kwargs: calls.append(("snapshot", kwargs["account"].id))
    )

    _finalize_accounts(worker, Mock(), _experiment(), accounts)

    assert calls == [
        ("sell", 1), ("equity", 1), ("snapshot", 1),
        ("equity", 2), ("snapshot", 2),
    ]
    assert [account.final_capital for account in accounts] == [1001.0, 1002.0]


def test_full_finalize_updates_experiment_only_after_account_snapshots() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    experiment = _experiment()
    account = _account(1, CURRENT_HYBRID, True)
    events = []
    worker._resolve_execution_costs = AsyncMock(return_value=_costs())
    worker.client.get_latest_price = AsyncMock(return_value=103.0)
    worker._strategy_accounts = Mock(return_value=[account])
    worker.broker.sell = Mock(side_effect=lambda **_: events.append("sell"))
    worker.broker.record_equity = Mock(
        side_effect=lambda **_: (
            events.append("equity") or SimpleNamespace(total_equity=1021.0)
        )
    )
    worker._record_market_snapshot = Mock(side_effect=lambda **_: events.append("snapshot"))
    worker._buy_and_hold_final_capital = Mock(return_value=1029.0)
    worker._mirror_hybrid_account = Mock(
        side_effect=lambda *_: events.append("mirror")
    )
    session.commit.side_effect = lambda: events.append("commit")

    asyncio.run(worker._finalize(session, experiment, FINISHED_AT, "FINISHED"))

    assert events == ["sell", "equity", "snapshot", "mirror", "commit"]
    assert experiment.last_price == 103.0
    assert experiment.status == "FINISHED"
    assert experiment.finished_at == FINISHED_AT
    assert experiment.last_market_event == "FINISHED"
    assert experiment.buy_and_hold_current_capital == 1029.0
    assert experiment.buy_and_hold_final_capital == 1029.0
    assert account.final_capital == 1021.0
    assert worker._buy_and_hold_final_capital.call_count == 2
    session.commit.assert_called_once()


def test_finalization_uses_last_saved_price_if_ticker_fails() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    experiment = _experiment()
    experiment.last_price = 97.0
    worker._resolve_execution_costs = AsyncMock(return_value=_costs())
    worker.client.get_latest_price = AsyncMock(side_effect=RuntimeError("ticker unavailable"))
    worker._strategy_accounts = Mock(return_value=[])
    worker._record_market_snapshot = Mock()
    worker._buy_and_hold_final_capital = Mock(return_value=970.0)
    worker._mirror_hybrid_account = Mock()

    asyncio.run(worker._finalize(session, experiment, FINISHED_AT, "STOPPED"))

    assert experiment.last_price == 97.0
    assert experiment.status == "STOPPED"
    assert experiment.buy_and_hold_final_capital == 970.0
    worker._record_market_snapshot.assert_not_called()
    session.commit.assert_called_once()


def test_without_any_valid_price_fails_without_closing_or_recording_accounts() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    experiment = _experiment()
    experiment.last_price = 0.0
    experiment.first_market_price = 0.0
    worker._resolve_execution_costs = AsyncMock(return_value=_costs())
    worker.client.get_latest_price = AsyncMock(side_effect=RuntimeError("no ticker"))
    worker._finalize_strategy_accounts = Mock()
    worker._strategy_accounts = Mock()

    asyncio.run(worker._finalize(session, experiment, FINISHED_AT, "FINISHED"))

    assert experiment.status == "FAILED"
    assert experiment.finished_at == FINISHED_AT
    assert experiment.error_message == "No market price was available to finalize the experiment."
    worker._finalize_strategy_accounts.assert_not_called()
    worker._strategy_accounts.assert_not_called()
    session.commit.assert_called_once()
