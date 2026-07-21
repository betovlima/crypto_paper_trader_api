from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_session
from ...runtime import settings
from ...schemas import AIPatternStatusResponse
from ...services import ai_pattern_query_service

router = APIRouter(
    prefix="/api/v1/experiments/{experiment_id}/ai-pattern-trader",
    tags=["AI Pattern Trader"],
)


@router.get("/status", response_model=AIPatternStatusResponse)
def get_ai_pattern_status(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> AIPatternStatusResponse:
    return AIPatternStatusResponse.model_validate(
        ai_pattern_query_service.get_ai_pattern_status(
            session,
            experiment_id,
            settings,
        )
    )


@router.get("/predictions")
def list_ai_pattern_predictions(
    experiment_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_session),
):
    return ai_pattern_query_service.list_ai_pattern_predictions(
        session,
        experiment_id,
        limit,
    )
