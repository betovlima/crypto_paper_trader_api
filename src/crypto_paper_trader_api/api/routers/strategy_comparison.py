from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_session
from ...schemas import StrategyComparisonHistoryResponse, StrategyComparisonResponse
from ...services import strategy_query_service

router = APIRouter(
    prefix="/api/v1/experiments/{experiment_id}",
    tags=["Strategy Comparison"],
)


@router.get("/strategies")
def list_strategy_accounts(
    experiment_id: str,
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_accounts(session, experiment_id)


@router.get("/strategy-comparison", response_model=StrategyComparisonResponse)
def get_strategy_comparison(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> StrategyComparisonResponse:
    return strategy_query_service.get_strategy_comparison(session, experiment_id)


@router.get(
    "/strategy-comparison/history",
    response_model=StrategyComparisonHistoryResponse,
)
def get_strategy_comparison_history(
    experiment_id: str,
    limit: int = Query(default=4, ge=1, le=50),
    session: Session = Depends(get_session),
) -> StrategyComparisonHistoryResponse:
    return strategy_query_service.get_strategy_comparison_history(
        session,
        experiment_id,
        limit,
    )
