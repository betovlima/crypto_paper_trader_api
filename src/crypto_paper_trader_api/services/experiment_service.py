from __future__ import annotations

from datetime import datetime
import math

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Experiment
from ..schemas import ExperimentCreate, ExperimentHistoryResponse, ExperimentResponse
from ..trading_profiles import get_trading_profile
from ..worker import TraderWorker, create_experiment_record, ensure_strategy_accounts
from .common import get_experiment_or_404


def create_experiment(
    session: Session,
    body: ExperimentCreate,
    settings: Settings,
    worker: TraderWorker,
) -> ExperimentResponse:
    active_count = session.scalar(
        select(func.count(Experiment.id)).where(
            Experiment.status.in_(("RUNNING", "STOP_REQUESTED"))
        )
    )
    if active_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only one PAPER_ONLY experiment can run at a time with SQLite.",
        )

    profile = get_trading_profile(body.trading_profile)
    experiment = create_experiment_record(
        market=body.market,
        trading_profile=profile.code,
        execution_timeframe=profile.decision_timeframe,
        trend_timeframe=profile.trend_timeframe,
        duration_hours=body.duration_hours,
        initial_capital=body.initial_capital,
        settings=settings,
    )
    session.add(experiment)
    session.flush()
    ensure_strategy_accounts(session, experiment)
    session.commit()
    session.refresh(experiment)
    worker.wake()
    return ExperimentResponse.model_validate(experiment.to_public_dict())


def list_experiments(session: Session, limit: int) -> list[ExperimentResponse]:
    experiments = list(
        session.scalars(select(Experiment).order_by(Experiment.started_at.desc()).limit(limit))
    )
    return [ExperimentResponse.model_validate(item.to_public_dict()) for item in experiments]


def get_experiment(session: Session, experiment_id: str) -> ExperimentResponse:
    experiment = get_experiment_or_404(session, experiment_id)
    return ExperimentResponse.model_validate(experiment.to_public_dict())


async def stop_latest_running_experiment(
    worker: TraderWorker,
    close_open_positions: bool,
) -> dict[str, object]:
    try:
        return await worker.stop_latest_running_experiment(close_open_positions)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No running experiment was found.",
        ) from exc


def list_experiment_history(
    session: Session,
    page: int,
    page_size: int,
    market: str | None = None,
    experiment_status: str | None = None,
    trading_profile: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    sort_direction: str = "desc",
) -> ExperimentHistoryResponse:
    filters = []
    if market:
        filters.append(Experiment.market == market.strip().upper())
    if experiment_status:
        filters.append(Experiment.status == experiment_status.strip().upper())
    if trading_profile:
        filters.append(Experiment.trading_profile == trading_profile.strip().upper())
    if start_date:
        filters.append(Experiment.started_at >= start_date)
    if end_date:
        filters.append(Experiment.started_at <= end_date)

    total_items = int(
        session.scalar(select(func.count(Experiment.id)).where(*filters)) or 0
    )
    order_column = (
        Experiment.started_at.asc()
        if sort_direction.strip().lower() == "asc"
        else Experiment.started_at.desc()
    )
    rows = list(
        session.scalars(
            select(Experiment)
            .where(*filters)
            .order_by(order_column)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    total_pages = math.ceil(total_items / page_size) if total_items else 0
    return ExperimentHistoryResponse(
        items=[ExperimentResponse.model_validate(row.to_public_dict()) for row in rows],
        pagination={
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
        },
    )
