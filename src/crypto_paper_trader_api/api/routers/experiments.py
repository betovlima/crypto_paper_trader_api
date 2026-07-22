from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ...database import get_session
from ...runtime import ai_scanner, settings, worker
from ...schemas import (
    ExperimentCreate,
    ExperimentHistoryResponse,
    ExperimentResponse,
    RunningExperimentHeaderSummary,
    StopRunningExperimentRequest,
    StopRunningExperimentResponse,
)
from ...security import require_admin_key
from ...services import experiment_service

router = APIRouter(prefix="/api/v1/experiments", tags=["Experiments"])


@router.post("", response_model=ExperimentResponse, status_code=status.HTTP_201_CREATED)
def create_experiment(
    body: ExperimentCreate,
    session: Session = Depends(get_session),
) -> ExperimentResponse:
    return experiment_service.create_experiment(session, body, settings, worker)


@router.get("", response_model=list[ExperimentResponse])
def list_experiments(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[ExperimentResponse]:
    return experiment_service.list_experiments(session, limit)


@router.get("/history", response_model=ExperimentHistoryResponse)
def list_experiment_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    market: str | None = Query(default=None),
    experiment_status: str | None = Query(default=None, alias="status"),
    trading_profile: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    sort_direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_session),
) -> ExperimentHistoryResponse:
    return experiment_service.list_experiment_history(
        session=session,
        page=page,
        page_size=page_size,
        market=market,
        experiment_status=experiment_status,
        trading_profile=trading_profile,
        start_date=start_date,
        end_date=end_date,
        sort_direction=sort_direction,
    )


@router.get("/running/header-summary", response_model=RunningExperimentHeaderSummary)
def get_running_experiment_header_summary(
    session: Session = Depends(get_session),
) -> RunningExperimentHeaderSummary:
    return experiment_service.get_running_experiment_header_summary(session)


@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> ExperimentResponse:
    return experiment_service.get_experiment(session, experiment_id)


@router.post(
    "/stop-running",
    response_model=StopRunningExperimentResponse,
    dependencies=[Depends(require_admin_key)],
)
async def stop_latest_running_experiment(
    body: StopRunningExperimentRequest,
) -> StopRunningExperimentResponse:
    result = await experiment_service.stop_latest_running_experiment(
        worker=worker,
        close_open_positions=body.close_open_positions,
    )
    return StopRunningExperimentResponse(
        **result,
        ai_scanner_running=ai_scanner.is_running,
    )
