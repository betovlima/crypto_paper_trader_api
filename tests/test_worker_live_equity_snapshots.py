"""Regression tests for live-cycle equity and market snapshot recording."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.strategy_codes import CURRENT_HYBRID, EMA_CROSSOVER
from crypto_paper_trader_api.trading_profiles import DEFAULT_TRADING_PROFILE
from crypto_paper_trader_api.worker import TraderWorker


NOW = datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc)


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
        id="live-equity-snapshots",
        market="BTCUSDT",
        trading_profile=DEFAULT_TRADING_PROFILE,
        execution_timeframe="30min",
        trend_timeframe="1hour",
        initial_capital=1000.0,
        scheduled_end_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )


def _account(identifier: int, code: str):
    return SimpleNamespace(
        id=identifier,
        strategy_code=code,
        last_event="OLD_EVENT",
        last_status_message="Previous message",
    )


def test_equity_is_recorded_before_market_snapshot_with_same_object() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    experiment = _experiment()
    account = _account(1, CURRENT_HYBRID)
    costs = _costs()
    equity = SimpleNamespace(total_equity=1082.5)
    actions = []
    worker.broker.record_equity = Mock(
        side_effect=lambda **kwargs: actions.append("equity") or equity
    )
    worker._record_market_snapshot = Mock(
        side_effect=lambda **kwargs: actions.append("snapshot")
    )

    worker._record_live_account_snapshots(
        session=session,
        experiment=experiment,
        accounts=[account],
        now=NOW,
        market_price=101.0,
        best_bid=100.98,
        best_ask=101.02,
        costs=costs,
        events={CURRENT_HYBRID: ("PRICE_UPDATE", "New price")},
    )

    assert actions == ["equity", "snapshot"]
    assert account.last_event == "PRICE_UPDATE"
    assert account.last_status_message == "New price"
    equity_kwargs = worker.broker.record_equity.call_args.kwargs
    snapshot_kwargs = worker._record_market_snapshot.call_args.kwargs
    assert equity_kwargs["account"] is account
    assert equity_kwargs["timestamp"] == NOW
    assert equity_kwargs["mid_market_price"] == 101.0
    assert equity_kwargs["best_bid"] == 100.98
    assert equity_kwargs["costs"] is costs
    assert snapshot_kwargs["equity"] is equity
    assert snapshot_kwargs["account"] is account
    assert snapshot_kwargs["best_ask"] == 101.02
    assert snapshot_kwargs["observed_at"] == NOW
    assert snapshot_kwargs["event_type"] == "PRICE_UPDATE"
    assert snapshot_kwargs["status_message"] == "New price"


def test_each_account_receives_its_own_equity_and_event_in_order() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    accounts = [_account(1, CURRENT_HYBRID), _account(2, EMA_CROSSOVER)]
    first_equity = SimpleNamespace(total_equity=950.0)
    second_equity = SimpleNamespace(total_equity=1020.0)
    worker.broker.record_equity = Mock(side_effect=[first_equity, second_equity])
    worker._record_market_snapshot = Mock()
    events = {
        CURRENT_HYBRID: ("LIVE_STOP_LOSS", "Protective stop executed"),
        EMA_CROSSOVER: ("ANALYSIS_HOLD", "Strategy held position"),
    }

    worker._record_live_account_snapshots(
        session=session, experiment=_experiment(), accounts=accounts,
        now=NOW, market_price=100.0, best_bid=99.98, best_ask=100.02,
        costs=_costs(), events=events,
    )

    assert [item.kwargs["account"] for item in worker.broker.record_equity.call_args_list] == accounts
    snapshots = worker._record_market_snapshot.call_args_list
    assert [item.kwargs["account"] for item in snapshots] == accounts
    assert [item.kwargs["equity"] for item in snapshots] == [first_equity, second_equity]
    assert [item.kwargs["event_type"] for item in snapshots] == [
        "LIVE_STOP_LOSS", "ANALYSIS_HOLD"
    ]
    assert [account.last_event for account in accounts] == [
        "LIVE_STOP_LOSS", "ANALYSIS_HOLD"
    ]
    assert [account.last_status_message for account in accounts] == [
        "Protective stop executed", "Strategy held position"
    ]


def test_missing_event_does_not_silently_create_an_incorrect_snapshot() -> None:
    worker = TraderWorker(Settings())
    account = _account(1, CURRENT_HYBRID)
    worker.broker.record_equity = Mock(return_value=SimpleNamespace(total_equity=1000.0))
    worker._record_market_snapshot = Mock()

    try:
        worker._record_live_account_snapshots(
            session=Mock(), experiment=_experiment(), accounts=[account],
            now=NOW, market_price=100.0, best_bid=99.98, best_ask=100.02,
            costs=_costs(), events={},
        )
    except KeyError as exc:
        assert exc.args == (CURRENT_HYBRID,)
    else:
        raise AssertionError("Missing strategy event must not be ignored")

    worker.broker.record_equity.assert_called_once()
    worker._record_market_snapshot.assert_not_called()
    assert account.last_event == "OLD_EVENT"


def test_live_cycle_saves_snapshots_after_candle_analysis_and_before_commit() -> None:
    worker = TraderWorker(Settings())
    session = Mock()
    experiment = _experiment()
    account = _account(1, CURRENT_HYBRID)
    events = []
    worker.client.get_latest_price = AsyncMock(return_value=101.0)
    worker._resolve_execution_costs = AsyncMock(return_value=_costs())
    worker._strategy_accounts = Mock(return_value=[account])
    worker._monitor_live_protective_exits = Mock(return_value=set())
    worker._analysis_is_due = Mock(return_value=True)
    worker._run_candle_analysis = AsyncMock(
        side_effect=lambda **kwargs: (
            events.append("analysis") or (True, {
                CURRENT_HYBRID: ("ANALYSIS_HOLD", "No trade")
            })
        )
    )
    worker.broker.record_equity = Mock(
        side_effect=lambda **kwargs: (
            events.append("equity") or SimpleNamespace(total_equity=1010.0)
        )
    )
    worker._record_market_snapshot = Mock(
        side_effect=lambda **kwargs: events.append("snapshot")
    )
    worker._buy_and_hold_final_capital = Mock(return_value=1010.0)
    worker._mirror_hybrid_account = Mock(side_effect=lambda *_: events.append("mirror"))
    session.commit.side_effect = lambda: events.append("commit")

    asyncio.run(worker._run_live_cycle(session, experiment, NOW))

    assert events == ["analysis", "equity", "snapshot", "mirror", "commit"]
    assert worker._record_market_snapshot.call_args.kwargs["event_type"] == "ANALYSIS_HOLD"
    assert account.last_event == "ANALYSIS_HOLD"
    assert experiment.last_market_event == "MULTI_STRATEGY_UPDATE"
    assert experiment.buy_and_hold_current_capital == 1010.0
    session.commit.assert_called_once()
