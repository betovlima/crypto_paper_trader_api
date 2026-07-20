from datetime import datetime, timezone

from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.worker import TraderWorker


def _experiment(*, started_at: datetime, last_processed: datetime | None = None) -> Experiment:
    return Experiment(
        id="test-experiment",
        market="BTCUSDT",
        trading_profile="BALANCED_INTRADAY",
        execution_timeframe="1hour",
        trend_timeframe="4hour",
        duration_hours=24.0,
        status="RUNNING",
        started_at=started_at,
        scheduled_end_at=started_at,
        next_analysis_at=started_at,
        last_processed_candle_at=last_processed,
        initial_capital=1000.0,
        cash_balance=1000.0,
        asset_quantity=0.0,
        entry_fee_paid=0.0,
        break_even_activated=False,
        vip_level=0,
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        fee_source="TEST",
        last_spread_rate=0.0,
        average_spread_rate=0.0,
        spread_observations=0,
        total_fees=0.0,
        total_spread_cost=0.0,
        total_slippage_cost=0.0,
        realized_pnl=0.0,
        max_equity=1000.0,
        max_drawdown_pct=0.0,
        consecutive_losses=0,
        model_name="test",
        model_version="test",
        recovery_status="IDLE",
        recovered_candle_count=0,
        recovered_trade_count=0,
    )


def test_first_candle_is_eligible_when_it_closes_after_experiment_start():
    worker = object.__new__(TraderWorker)
    experiment = _experiment(
        started_at=datetime(2026, 7, 20, 16, 12, tzinfo=timezone.utc)
    )

    assert worker._is_pending_candle(
        datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc), experiment
    )
    assert not worker._is_pending_candle(
        datetime(2026, 7, 20, 15, 0, tzinfo=timezone.utc), experiment
    )


def test_recovery_uses_candle_start_to_avoid_duplicate_decisions():
    worker = object.__new__(TraderWorker)
    experiment = _experiment(
        started_at=datetime(2026, 7, 20, 15, 30, tzinfo=timezone.utc),
        last_processed=datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc),
    )

    assert not worker._is_pending_candle(
        datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc), experiment
    )
    assert worker._is_pending_candle(
        datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc), experiment
    )


def test_initial_dashboard_analysis_ignores_future_next_analysis_time():
    worker = object.__new__(TraderWorker)
    now = datetime(2026, 7, 20, 20, 55, tzinfo=timezone.utc)
    experiment = _experiment(
        started_at=datetime(2026, 7, 20, 20, 20, tzinfo=timezone.utc)
    )
    experiment.next_analysis_at = datetime(2026, 7, 20, 21, 0, tzinfo=timezone.utc)
    experiment.last_processed_candle_at = None

    assert worker._analysis_is_due(experiment=experiment, now=now)


def test_processed_experiment_respects_future_next_analysis_time():
    worker = object.__new__(TraderWorker)
    now = datetime(2026, 7, 20, 20, 55, tzinfo=timezone.utc)
    experiment = _experiment(
        started_at=datetime(2026, 7, 20, 20, 20, tzinfo=timezone.utc),
        last_processed=datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc),
    )
    experiment.next_analysis_at = datetime(2026, 7, 20, 21, 0, tzinfo=timezone.utc)

    assert not worker._analysis_is_due(experiment=experiment, now=now)


def test_processed_experiment_runs_when_next_analysis_is_due():
    worker = object.__new__(TraderWorker)
    now = datetime(2026, 7, 20, 21, 0, tzinfo=timezone.utc)
    experiment = _experiment(
        started_at=datetime(2026, 7, 20, 20, 20, tzinfo=timezone.utc),
        last_processed=datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc),
    )
    experiment.next_analysis_at = datetime(2026, 7, 20, 21, 0, tzinfo=timezone.utc)

    assert worker._analysis_is_due(experiment=experiment, now=now)
