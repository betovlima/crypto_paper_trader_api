from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from ...database import get_session
from ...runtime import settings, worker
from ...schemas import ExperimentCreate, ExperimentResponse
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


@router.get("/{experiment_id}", response_model=ExperimentResponse)
def get_experiment(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> ExperimentResponse:
    return experiment_service.get_experiment(session, experiment_id)


@router.post(
    "/{experiment_id}/stop",
    response_model=ExperimentResponse,
    dependencies=[Depends(require_admin_key)],
)
def request_stop(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> ExperimentResponse:
    return experiment_service.request_stop(session, experiment_id, worker)
