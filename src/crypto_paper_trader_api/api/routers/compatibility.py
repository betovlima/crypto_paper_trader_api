from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_session
from ...services import strategy_query_service
from ...strategy_codes import CURRENT_HYBRID

router = APIRouter(
    prefix="/api/v1/experiments/{experiment_id}",
    tags=["Compatibility"],
)


@router.get("/decisions")
def list_decisions_alias(
    experiment_id: str,
    limit: int = Query(default=100, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_decisions(
        session,
        experiment_id,
        CURRENT_HYBRID,
        limit,
    )


@router.get("/trades")
def list_trades_alias(
    experiment_id: str,
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_trades(
        session,
        experiment_id,
        CURRENT_HYBRID,
    )


@router.get("/market-snapshots")
def list_market_snapshots_alias(
    experiment_id: str,
    limit: int = Query(default=120, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    return strategy_query_service.list_strategy_market_snapshots(
        session,
        experiment_id,
        CURRENT_HYBRID,
        limit,
    )
