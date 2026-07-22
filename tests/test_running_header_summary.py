from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.services.experiment_service import (
    get_running_experiment_header_summary,
)


def _experiment(now: datetime, status: str = "RUNNING") -> Experiment:
    return Experiment(
        id=str(uuid4()),
        market="SOLBTC",
        trading_profile="BALANCED_INTRADAY",
        execution_timeframe="30min",
        trend_timeframe="1hour",
        duration_hours=24,
        status=status,
        started_at=now - timedelta(hours=2),
        scheduled_end_at=now + timedelta(hours=22),
        next_analysis_at=now + timedelta(minutes=19, seconds=14),
        last_market_update_at=now - timedelta(seconds=23),
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
    )


def _account(experiment_id: str, code: str, quantity: float = 0.0, setup: str = "IDLE") -> StrategyAccount:
    return StrategyAccount(
        experiment_id=experiment_id,
        strategy_code=code,
        display_name=code,
        initial_capital=1000,
        cash_balance=1000,
        asset_quantity=quantity,
        max_equity=1000,
        setup_status=setup,
    )


def test_header_summary_is_hidden_without_running_experiment() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        summary = get_running_experiment_header_summary(
            session,
            now=datetime(2026, 7, 22, 20, 10, 37, tzinfo=timezone.utc),
        )

    assert summary.visible is False
    assert summary.experiment_id is None
    assert summary.strategy_summary is None


def test_header_summary_returns_only_server_calculated_values() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 7, 22, 20, 10, 37, tzinfo=timezone.utc)

    with Session(engine) as session:
        experiment = _experiment(now)
        session.add(experiment)
        session.flush()
        session.add_all(
            [
                _account(experiment.id, "ADAPTIVE_STRATEGY_SELECTOR", quantity=0.25),
                _account(experiment.id, "CURRENT_HYBRID", setup="ARMED"),
                _account(experiment.id, "EMA_CROSSOVER_COST_AWARE"),
            ]
        )
        session.commit()

        summary = get_running_experiment_header_summary(session, now=now)

    assert summary.visible is True
    assert summary.market_label == "SOL/BTC"
    assert summary.decision_timeframe_label == "30 min"
    assert summary.trend_timeframe_label == "1 h (60 min)"
    assert summary.next_analysis_countdown_seconds == 1154
    assert summary.next_analysis_countdown_label == "19:14"
    assert summary.last_market_update_label == "20:10:14 UTC"
    assert summary.strategy_summary is not None
    assert summary.strategy_summary.total == 3
    assert summary.strategy_summary.active_positions == 1
    assert summary.strategy_summary.armed_entries == 1
    assert summary.strategy_summary.waiting == 1
