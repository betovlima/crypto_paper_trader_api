from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Experiment
from ..schemas import ExperimentCreate, ExperimentResponse
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


def request_stop(
    session: Session,
    experiment_id: str,
    worker: TraderWorker,
) -> ExperimentResponse:
    experiment = get_experiment_or_404(session, experiment_id)
    if experiment.status != "RUNNING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Experiment cannot be stopped from status {experiment.status}.",
        )
    experiment.status = "STOP_REQUESTED"
    session.commit()
    session.refresh(experiment)
    worker.wake()
    return ExperimentResponse.model_validate(experiment.to_public_dict())
