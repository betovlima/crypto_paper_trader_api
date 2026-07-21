from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import MethodType
from uuid import uuid4

from sqlalchemy import delete, func, select

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import SessionLocal, init_database
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.worker import TraderWorker


def _experiment(status: str, started_at: datetime) -> Experiment:
    return Experiment(
        id=str(uuid4()),
        market="BTCUSDT",
        trading_profile="BALANCED_INTRADAY",
        execution_timeframe="30min",
        trend_timeframe="1hour",
        duration_hours=24,
        status=status,
        started_at=started_at,
        scheduled_end_at=started_at + timedelta(hours=24),
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
    )


def test_stop_targets_latest_running_experiment_and_preserves_data() -> None:
    init_database()
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.execute(delete(Experiment))
        older = _experiment("RUNNING", now - timedelta(hours=2))
        latest = _experiment("RUNNING", now - timedelta(hours=1))
        finished = _experiment("FINISHED", now)
        session.add_all([older, latest, finished])
        session.flush()
        session.add(
            StrategyAccount(
                experiment_id=latest.id,
                strategy_code="CURRENT_HYBRID",
                display_name="Hybrid + ML",
                initial_capital=1000,
                cash_balance=1000,
                max_equity=1000,
            )
        )
        session.commit()
        latest_id = latest.id
        older_id = older.id

    worker = TraderWorker(Settings())

    async def fake_finalize(
        self,
        session,
        experiment,
        finished_at,
        final_status,
        close_open_positions=True,
    ):
        assert close_open_positions is True
        experiment.status = final_status
        experiment.finished_at = finished_at
        session.commit()

    worker._finalize = MethodType(fake_finalize, worker)
    result = asyncio.run(worker.stop_latest_running_experiment(True))

    with SessionLocal() as session:
        latest_status = session.get(Experiment, latest_id).status
        older_status = session.get(Experiment, older_id).status
        experiment_count = int(session.scalar(select(func.count()).select_from(Experiment)) or 0)
        account_count = int(
            session.scalar(select(func.count()).select_from(StrategyAccount)) or 0
        )

    assert result["experiment_id"] == latest_id
    assert result["status"] == "STOPPED"
    assert result["data_preserved"] is True
    assert latest_status == "STOPPED"
    assert older_status == "RUNNING"
    assert experiment_count == 3
    assert account_count == 1


def test_stop_returns_no_running_experiment() -> None:
    init_database()
    with SessionLocal() as session:
        session.execute(delete(Experiment))
        session.commit()

    worker = TraderWorker(Settings())
    try:
        asyncio.run(worker.stop_latest_running_experiment(True))
    except LookupError as exc:
        assert str(exc) == "No running experiment was found."
    else:
        raise AssertionError("The worker should reject a stop without a RUNNING experiment.")
