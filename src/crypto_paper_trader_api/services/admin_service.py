from __future__ import annotations

from sqlalchemy import delete, func, select

from ..database import SessionLocal
from ..models import Experiment
from ..worker import TraderWorker


async def reset_paper_trading_data(worker: TraderWorker) -> int:
    """Delete every paper-trading experiment while preserving the AI candle cache.

    The worker processing lock prevents an active live cycle from writing into an
    experiment while its relational graph is being removed.
    """

    async with worker.exclusive_processing():
        with SessionLocal() as session:
            deleted_experiments = int(
                session.scalar(select(func.count()).select_from(Experiment)) or 0
            )
            session.execute(delete(Experiment))
            session.commit()

    worker.wake()
    return deleted_experiments
