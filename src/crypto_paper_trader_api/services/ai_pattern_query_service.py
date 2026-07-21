from __future__ import annotations

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import StrategyAccount, StrategyDecisionSnapshot
from ..strategy_codes import AI_PATTERN_TRADER
from .common import get_experiment_or_404
from .strategy_query_service import strategy_summary

MODEL_VERSION = "AI-PATTERN-v1"


def get_ai_pattern_status(
    session: Session,
    experiment_id: str,
    settings: Settings,
) -> dict:
    experiment = get_experiment_or_404(session, experiment_id)
    account = session.scalar(
        select(StrategyAccount).where(
            StrategyAccount.experiment_id == experiment_id,
            StrategyAccount.strategy_code == AI_PATTERN_TRADER,
        )
    )
    filters = (
        StrategyDecisionSnapshot.experiment_id == experiment_id,
        StrategyDecisionSnapshot.strategy_code == AI_PATTERN_TRADER,
    )
    latest = session.scalar(
        select(StrategyDecisionSnapshot)
        .where(*filters)
        .order_by(StrategyDecisionSnapshot.candle_timestamp.desc())
        .limit(1)
    )
    prediction_count = int(
        session.scalar(select(func.count(StrategyDecisionSnapshot.id)).where(*filters)) or 0
    )
    resolved_filters = (*filters, StrategyDecisionSnapshot.ai_outcome_resolved.is_(True))
    resolved_count = int(
        session.scalar(
            select(func.count(StrategyDecisionSnapshot.id)).where(*resolved_filters)
        )
        or 0
    )
    direction_accuracy = session.scalar(
        select(func.avg(cast(StrategyDecisionSnapshot.ai_direction_correct, Float))).where(
            *resolved_filters,
            StrategyDecisionSnapshot.ai_direction_correct.is_not(None),
        )
    )
    average_realized_net_return = session.scalar(
        select(func.avg(StrategyDecisionSnapshot.ai_realized_net_return)).where(
            *resolved_filters,
            StrategyDecisionSnapshot.ai_realized_net_return.is_not(None),
        )
    )
    average_reward = session.scalar(
        select(func.avg(StrategyDecisionSnapshot.ai_realized_reward)).where(
            *resolved_filters,
            StrategyDecisionSnapshot.ai_realized_reward.is_not(None),
        )
    )

    return {
        "experiment_id": experiment.id,
        "market": experiment.market,
        "mode": settings.ai_pattern_mode,
        "model_version": MODEL_VERSION,
        "account": (
            strategy_summary(session, account, experiment.last_price) if account is not None else None
        ),
        "latest_decision": latest.to_dict() if latest is not None else None,
        "performance": {
            "prediction_count": prediction_count,
            "resolved_count": resolved_count,
            "direction_accuracy": (
                float(direction_accuracy) if direction_accuracy is not None else None
            ),
            "average_realized_net_return": (
                float(average_realized_net_return)
                if average_realized_net_return is not None
                else None
            ),
            "average_reward": float(average_reward) if average_reward is not None else None,
        },
    }


def list_ai_pattern_predictions(
    session: Session,
    experiment_id: str,
    limit: int,
) -> list[dict]:
    get_experiment_or_404(session, experiment_id)
    rows = list(
        session.scalars(
            select(StrategyDecisionSnapshot)
            .where(
                StrategyDecisionSnapshot.experiment_id == experiment_id,
                StrategyDecisionSnapshot.strategy_code == AI_PATTERN_TRADER,
            )
            .order_by(StrategyDecisionSnapshot.candle_timestamp.desc())
            .limit(limit)
        )
    )
    return [row.to_dict() for row in rows]
