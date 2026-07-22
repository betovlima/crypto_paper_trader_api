from __future__ import annotations

from datetime import datetime, timezone
import math

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Experiment, StrategyAccount
from ..schemas import (
    ExperimentCreate,
    ExperimentHistoryResponse,
    ExperimentResponse,
    RunningExperimentHeaderSummary,
)
from ..strategy_codes import ACTIVE_STRATEGY_CODES
from ..trading_profiles import get_trading_profile
from ..worker import TraderWorker, create_experiment_record, ensure_strategy_accounts
from .common import get_experiment_or_404


_MARKET_QUOTE_ASSETS = (
    "USDT",
    "USDC",
    "FDUSD",
    "BUSD",
    "TUSD",
    "DAI",
    "BTC",
    "ETH",
    "BNB",
)

_TIMEFRAME_LABELS = {
    "1min": "1 min",
    "5min": "5 min",
    "15min": "15 min",
    "30min": "30 min",
    "1hour": "1 h (60 min)",
    "4hour": "4 h",
    "1day": "1 day",
    "1week": "1 week",
}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_market_pair(market: str) -> str:
    normalized = market.strip().upper()
    for quote_asset in _MARKET_QUOTE_ASSETS:
        if normalized.endswith(quote_asset) and len(normalized) > len(quote_asset):
            return f"{normalized[:-len(quote_asset)]}/{quote_asset}"
    return normalized


def _format_timeframe(timeframe: str) -> str:
    return _TIMEFRAME_LABELS.get(timeframe, timeframe)


def _format_utc_time(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.strftime("%H:%M:%S UTC") if normalized else None


def _format_countdown(target: datetime | None, now: datetime) -> tuple[int | None, str | None]:
    normalized_target = _as_utc(target)
    normalized_now = _as_utc(now)
    if normalized_target is None or normalized_now is None:
        return None, None

    remaining_seconds = max(0, math.ceil((normalized_target - normalized_now).total_seconds()))
    days, remainder = divmod(remaining_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        label = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    elif hours > 0:
        label = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        label = f"{minutes:02d}:{seconds:02d}"
    return remaining_seconds, label


def get_running_experiment_header_summary(
    session: Session,
    now: datetime | None = None,
) -> RunningExperimentHeaderSummary:
    experiment = session.scalar(
        select(Experiment)
        .where(Experiment.status.in_(("RUNNING", "STOP_REQUESTED")))
        .order_by(Experiment.started_at.desc())
        .limit(1)
    )
    if experiment is None:
        return RunningExperimentHeaderSummary(visible=False)

    accounts = list(
        session.scalars(
            select(StrategyAccount).where(
                StrategyAccount.experiment_id == experiment.id,
                StrategyAccount.strategy_code.in_(ACTIVE_STRATEGY_CODES),
            )
        )
    )
    total = len(accounts)
    active_positions = sum(1 for account in accounts if account.has_open_position)
    armed_entries = sum(
        1
        for account in accounts
        if not account.has_open_position and account.setup_status == "ARMED"
    )
    waiting = max(0, total - active_positions - armed_entries)

    reference_time = now or datetime.now(timezone.utc)
    countdown_seconds, countdown_label = _format_countdown(
        experiment.next_analysis_at,
        reference_time,
    )

    return RunningExperimentHeaderSummary(
        visible=True,
        experiment_id=experiment.id,
        status=experiment.status,
        status_tone=("stopping" if experiment.status == "STOP_REQUESTED" else "running"),
        market=experiment.market,
        market_label=_format_market_pair(experiment.market),
        decision_timeframe=experiment.execution_timeframe,
        decision_timeframe_label=_format_timeframe(experiment.execution_timeframe),
        trend_timeframe=experiment.trend_timeframe,
        trend_timeframe_label=_format_timeframe(experiment.trend_timeframe),
        next_analysis_at=experiment.next_analysis_at,
        next_analysis_countdown_seconds=countdown_seconds,
        next_analysis_countdown_label=countdown_label,
        last_market_update_at=experiment.last_market_update_at,
        last_market_update_label=_format_utc_time(experiment.last_market_update_at),
        strategy_summary={
            "total": total,
            "active_positions": active_positions,
            "armed_entries": armed_entries,
            "waiting": waiting,
        },
    )


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
