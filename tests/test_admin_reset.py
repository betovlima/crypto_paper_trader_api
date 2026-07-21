from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select

from crypto_paper_trader_api.database import SessionLocal, init_database
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.services.admin_service import reset_paper_trading_data


class _WorkerStub:
    def __init__(self) -> None:
        self.wake_count = 0

    @asynccontextmanager
    async def exclusive_processing(self):
        yield

    def wake(self) -> None:
        self.wake_count += 1


def _experiment() -> Experiment:
    now = datetime.now(timezone.utc)
    return Experiment(
        id=str(uuid4()),
        market="BTCUSDT",
        trading_profile="BALANCED_INTRADAY",
        execution_timeframe="30min",
        trend_timeframe="1hour",
        duration_hours=1,
        status="FINISHED",
        started_at=now,
        scheduled_end_at=now + timedelta(hours=1),
        initial_capital=1000,
        cash_balance=1000,
        max_equity=1000,
    )


def test_reset_removes_all_experiments() -> None:
    init_database()
    with SessionLocal() as session:
        session.execute(__import__("sqlalchemy").delete(Experiment))
        first = _experiment()
        second = _experiment()
        session.add_all([first, second])
        session.flush()
        session.add(
            StrategyAccount(
                experiment_id=first.id,
                strategy_code="CURRENT_HYBRID",
                display_name="Hybrid + ML",
                initial_capital=1000,
                cash_balance=1000,
                max_equity=1000,
            )
        )
        session.commit()

    worker = _WorkerStub()
    deleted = asyncio.run(reset_paper_trading_data(worker))

    with SessionLocal() as session:
        remaining = int(session.scalar(select(func.count()).select_from(Experiment)) or 0)
        remaining_accounts = int(
            session.scalar(select(func.count()).select_from(StrategyAccount)) or 0
        )

    assert deleted == 2
    assert remaining == 0
    assert remaining_accounts == 0
    assert worker.wake_count == 1
