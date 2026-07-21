from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import (
    StrategyDecisionSnapshot,
    StrategySimulatedTrade,
)
from crypto_paper_trader_api.strategy_codes import ACTIVE_STRATEGY_CODES
from crypto_paper_trader_api.worker import (
    TraderWorker,
    create_experiment_record,
    ensure_strategy_accounts,
)


def candles(freq: str) -> pd.DataFrame:
    count = 260
    timestamps = pd.date_range("2026-01-01", periods=count, freq=freq, tz="UTC")
    close = 100 + np.linspace(0, 5, count) + np.sin(np.arange(count) / 8)
    close[-6:] = [105, 104.5, 104, 103.5, 103, 106]
    volume = 1000 + np.arange(count)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": volume,
            "value": volume * close,
        }
    )


class FakeClient:
    async def get_candles(self, _market: str, period: str, **_kwargs):
        return candles("30min")


async def run_analysis(session: Session, experiment, worker: TraderWorker) -> None:
    await worker._run_candle_analysis(
        session=session,
        experiment=experiment,
        now=datetime(2026, 7, 19, tzinfo=timezone.utc),
        costs=ExecutionCosts(
            maker_fee_rate=0.002,
            taker_fee_rate=0.002,
            spread_rate=0.0001,
            slippage_rate=0.0005,
            fee_source="TEST",
        ),
        live_action_accounts=set(),
    )


def test_one_closed_candle_creates_all_strategy_decisions() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(default_execution_timeframe="30min")
    worker = TraderWorker(settings)
    worker.client = FakeClient()  # type: ignore[assignment]
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)
    execution_frame = candles("30min")
    experiment.last_processed_candle_at = execution_frame.iloc[-2]["timestamp"].to_pydatetime()
    experiment.last_price = 106
    experiment.best_bid = 105.99
    experiment.best_ask = 106.01

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        ensure_strategy_accounts(session, experiment)
        asyncio.run(run_analysis(session, experiment, worker))
        session.flush()

        decisions = list(
            session.scalars(
                select(StrategyDecisionSnapshot).order_by(StrategyDecisionSnapshot.strategy_code)
            )
        )

        assert len(decisions) == len(ACTIVE_STRATEGY_CODES)
        assert {item.strategy_code for item in decisions} == set(ACTIVE_STRATEGY_CODES)
        ema9_rows = [item for item in decisions if item.strategy_code.startswith("EMA9")]
        assert all(item.ema_9 is not None for item in ema9_rows)


def test_downtime_recovery_replays_every_missing_closed_candle() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(default_execution_timeframe="30min")
    worker = TraderWorker(settings)
    worker.client = FakeClient()  # type: ignore[assignment]
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)
    execution_frame = candles("30min")
    experiment.last_processed_candle_at = execution_frame.iloc[-4]["timestamp"].to_pydatetime()
    experiment.last_price = 106
    experiment.best_bid = 105.99
    experiment.best_ask = 106.01

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        ensure_strategy_accounts(session, experiment)
        asyncio.run(run_analysis(session, experiment, worker))
        session.flush()

        decisions = list(session.scalars(select(StrategyDecisionSnapshot)))
        assert experiment.recovery_status == "COMPLETED"
        assert experiment.recovered_candle_count == 3
        assert len(decisions) == 3 * len(ACTIVE_STRATEGY_CODES)
        assert all(item.is_recovered for item in decisions)
        assert experiment.last_processed_candle_at == execution_frame.iloc[-1][
            "timestamp"
        ].to_pydatetime()


def test_initial_dashboard_snapshot_is_created_without_historical_trade() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(default_execution_timeframe="30min")
    worker = TraderWorker(settings)
    worker.client = FakeClient()  # type: ignore[assignment]
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)
    experiment.last_price = 106
    experiment.best_bid = 105.99
    experiment.best_ask = 106.01

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        ensure_strategy_accounts(session, experiment)
        asyncio.run(run_analysis(session, experiment, worker))
        session.flush()

        decisions = list(session.scalars(select(StrategyDecisionSnapshot)))
        trades = list(session.scalars(select(StrategySimulatedTrade)))

        assert len(decisions) == len(ACTIVE_STRATEGY_CODES)
        assert trades == []
        assert all(not item.action_executed for item in decisions)
        assert experiment.last_processed_candle_at is not None
        assert experiment.recovery_message is not None
        assert "Initial dashboard state" in experiment.recovery_message
