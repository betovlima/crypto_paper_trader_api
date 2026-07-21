from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_session
from ...services import strategy_query_service
from ...strategy_codes import CURRENT_HYBRID

router = APIRouter(
    prefix="/api/v1/experiments/{experiment_id}",
    tags=["Strategy Data"],
)


@router.get("/strategy-decisions")
def list_strategy_decisions(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    limit: int = Query(default=100, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_decisions(
        session,
        experiment_id,
        strategy_code,
        limit,
    )




@router.get("/strategy-trades/history")
def list_strategy_trade_history(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    side: str | None = Query(default=None),
    result: str | None = Query(default=None),
    recovered: bool | None = Query(default=None),
    selected_strategy_code: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    sort_direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_trade_history(
        session=session,
        experiment_id=experiment_id,
        strategy_code=strategy_code,
        page=page,
        page_size=page_size,
        side=side,
        result=result,
        recovered=recovered,
        selected_strategy_code=selected_strategy_code,
        start_date=start_date,
        end_date=end_date,
        sort_direction=sort_direction,
    )


@router.get("/strategy-trades")
def list_strategy_trades(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_trades(
        session,
        experiment_id,
        strategy_code,
    )


@router.get("/strategy-market-snapshots")
def list_strategy_market_snapshots(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    limit: int = Query(default=120, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_market_snapshots(
        session,
        experiment_id,
        strategy_code,
        limit,
    )
