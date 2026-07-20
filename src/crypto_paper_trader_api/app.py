from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session, init_database
from .export_builder import ExportBuilder
from .models import (
    Experiment,
    StrategyAccount,
    StrategyDecisionSnapshot,
    StrategyMarketSnapshot,
    StrategySimulatedTrade,
)
from .schemas import (
    ExperimentCreate,
    ExperimentResponse,
    HealthResponse,
    PublicConfiguration,
    StrategyComparisonHistoryResponse,
    StrategyComparisonResponse,
)
from .security import require_admin_key
from .strategy_codes import (
    ACTIVE_STRATEGY_CODES,
    CURRENT_HYBRID,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_DISPLAY_NAMES,
)
from .trading_profiles import get_trading_profile, list_trading_profiles
from .worker import (
    TraderWorker,
    create_experiment_record,
    ensure_strategy_accounts,
)

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
worker = TraderWorker(settings)
export_builder = ExportBuilder()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_persistent_storage()
    init_database()
    if settings.storage_warning:
        logging.getLogger(__name__).warning(settings.storage_warning)
    logging.getLogger(__name__).info(
        "SQLite database path: %s; Railway persistent volume attached: %s",
        settings.resolved_database_url,
        settings.persistent_storage_configured,
    )
    worker.start()
    worker.wake()
    yield
    await worker.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.9.6",
    description=(
        "PAPER_ONLY crypto strategy comparison using public CoinEx Spot data. "
        "Technical setups decide entries and exits; fees are applied only to execution "
        "accounting and result reporting. The application contains no authenticated order "
        "or withdrawal endpoints."
    ),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health() -> HealthResponse:
    database_url = settings.resolved_database_url
    database_path = settings.resolved_data_dir / "crypto_paper_trader_api.db"
    return HealthResponse(
        database=database_url,
        data_dir=str(settings.resolved_data_dir),
        database_exists=database_path.exists(),
        worker_running=worker.is_running,
        persistent_storage_configured=settings.persistent_storage_configured,
        storage_warning=settings.storage_warning,
    )


@app.get("/api/v1/config", response_model=PublicConfiguration, tags=["System"])
def public_configuration() -> PublicConfiguration:
    return PublicConfiguration(
        fees_affect_signals=False,
        downtime_recovery_enabled=True,
        active_strategy_codes=list(ACTIVE_STRATEGY_CODES),
        trading_profiles=list_trading_profiles(),
        strategy_catalog=[
            {
                "code": code,
                "display_name": STRATEGY_DISPLAY_NAMES[code],
                "description": STRATEGY_DESCRIPTIONS[code],
            }
            for code in ACTIVE_STRATEGY_CODES
        ],
        default_market=settings.default_market,
        default_execution_timeframe=settings.default_execution_timeframe,
        default_trend_timeframe=settings.default_trend_timeframe,
        default_duration_hours=settings.default_duration_hours,
        default_initial_capital=settings.default_initial_capital,
        vip_level=settings.vip_level,
        maker_fee_rate=settings.effective_default_maker_fee_rate,
        taker_fee_rate=settings.effective_default_taker_fee_rate,
        cet_fee_discount_enabled=settings.cet_fee_discount_enabled,
        fallback_spread_rate=settings.fallback_spread_rate,
        slippage_rate=settings.slippage_rate,
        estimated_round_trip_cost_rate=settings.round_trip_cost_rate,
        position_allocation=settings.position_allocation,
        buy_probability_threshold=settings.buy_probability_threshold,
        sell_probability_threshold=settings.sell_probability_threshold,
        min_technical_confirmations=settings.min_technical_confirmations,
        stop_atr_multiplier=settings.stop_atr_multiplier,
        stop_loss_min_pct=settings.stop_loss_min_pct,
        stop_loss_max_pct=settings.stop_loss_max_pct,
        reward_risk_ratio=settings.reward_risk_ratio,
        take_profit_atr_multiplier=settings.take_profit_atr_multiplier,
        trailing_atr_multiplier=settings.trailing_atr_multiplier,
        trailing_activation_r=settings.trailing_activation_r,
        break_even_activation_r=settings.break_even_activation_r,
        max_holding_hours=settings.max_holding_hours,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        ema9_period=settings.ema9_period,
    )


@app.post(
    "/api/v1/experiments",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Experiments"],
)
def create_experiment(
    body: ExperimentCreate,
    session: Session = Depends(get_session),
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


@app.get("/api/v1/experiments", response_model=list[ExperimentResponse], tags=["Experiments"])
def list_experiments(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[ExperimentResponse]:
    experiments = list(
        session.scalars(select(Experiment).order_by(Experiment.started_at.desc()).limit(limit))
    )
    return [ExperimentResponse.model_validate(item.to_public_dict()) for item in experiments]


@app.get(
    "/api/v1/experiments/{experiment_id}",
    response_model=ExperimentResponse,
    tags=["Experiments"],
)
def get_experiment(
    experiment_id: str, session: Session = Depends(get_session)
) -> ExperimentResponse:
    experiment = _get_experiment_or_404(session, experiment_id)
    return ExperimentResponse.model_validate(experiment.to_public_dict())


@app.post(
    "/api/v1/experiments/{experiment_id}/stop",
    response_model=ExperimentResponse,
    tags=["Experiments"],
    dependencies=[Depends(require_admin_key)],
)
def request_stop(experiment_id: str, session: Session = Depends(get_session)) -> ExperimentResponse:
    experiment = _get_experiment_or_404(session, experiment_id)
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


@app.get("/api/v1/experiments/{experiment_id}/strategies", tags=["Strategy Comparison"])
def list_strategy_accounts(
    experiment_id: str,
    session: Session = Depends(get_session),
):
    experiment = _get_experiment_or_404(session, experiment_id)
    ensure_strategy_accounts(session, experiment)
    session.commit()
    accounts = list(
        session.scalars(
            select(StrategyAccount)
            .where(
                StrategyAccount.experiment_id == experiment_id,
                StrategyAccount.strategy_code.in_(ACTIVE_STRATEGY_CODES),
            )
            .order_by(StrategyAccount.id)
        )
    )
    return [_strategy_summary(session, account, experiment.last_price) for account in accounts]


@app.get(
    "/api/v1/experiments/{experiment_id}/strategy-comparison",
    response_model=StrategyComparisonResponse,
    tags=["Strategy Comparison"],
)
def get_strategy_comparison(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> StrategyComparisonResponse:
    """Return only the latest persisted decision for each active strategy.

    This query endpoint never runs indicators, trains models, executes trades, or
    changes experiment state. The worker remains solely responsible for analysis.
    """
    experiment = _get_experiment_or_404(session, experiment_id)
    strategies = []
    latest_timestamps = []
    for strategy_code in ACTIVE_STRATEGY_CODES:
        latest = session.scalar(
            select(StrategyDecisionSnapshot)
            .where(
                StrategyDecisionSnapshot.experiment_id == experiment_id,
                StrategyDecisionSnapshot.strategy_code == strategy_code,
            )
            .order_by(StrategyDecisionSnapshot.candle_timestamp.desc())
            .limit(1)
        )
        if latest is not None:
            latest_timestamps.append(latest.candle_timestamp)
        strategies.append(
            {
                "strategy_code": strategy_code,
                "display_name": STRATEGY_DISPLAY_NAMES[strategy_code],
                "description": STRATEGY_DESCRIPTIONS[strategy_code],
                "latest_decision": latest.to_dict() if latest is not None else None,
            }
        )
    return StrategyComparisonResponse(
        experiment_id=experiment.id,
        market=experiment.market,
        updated_at=max(latest_timestamps) if latest_timestamps else None,
        strategies=strategies,
    )


@app.get(
    "/api/v1/experiments/{experiment_id}/strategy-comparison/history",
    response_model=StrategyComparisonHistoryResponse,
    tags=["Strategy Comparison"],
)
def get_strategy_comparison_history(
    experiment_id: str,
    limit: int = Query(default=4, ge=1, le=50),
    session: Session = Depends(get_session),
) -> StrategyComparisonHistoryResponse:
    """Return recent persisted decisions grouped by strategy.

    History is intentionally separate from the current-state endpoint so each
    route has one read-only responsibility and response sizes stay predictable.
    """
    experiment = _get_experiment_or_404(session, experiment_id)
    strategies = []
    for strategy_code in ACTIVE_STRATEGY_CODES:
        rows = list(
            session.scalars(
                select(StrategyDecisionSnapshot)
                .where(
                    StrategyDecisionSnapshot.experiment_id == experiment_id,
                    StrategyDecisionSnapshot.strategy_code == strategy_code,
                )
                .order_by(StrategyDecisionSnapshot.candle_timestamp.desc())
                .limit(limit)
            )
        )
        strategies.append(
            {
                "strategy_code": strategy_code,
                "display_name": STRATEGY_DISPLAY_NAMES[strategy_code],
                "decisions": [row.to_dict() for row in rows],
            }
        )
    return StrategyComparisonHistoryResponse(
        experiment_id=experiment.id,
        market=experiment.market,
        limit_per_strategy=limit,
        strategies=strategies,
    )


@app.get("/api/v1/experiments/{experiment_id}/strategy-decisions", tags=["Strategy Comparison"])
def list_strategy_decisions(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    limit: int = Query(default=100, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    _get_experiment_or_404(session, experiment_id)
    rows = list(
        session.scalars(
            select(StrategyDecisionSnapshot)
            .where(
                StrategyDecisionSnapshot.experiment_id == experiment_id,
                StrategyDecisionSnapshot.strategy_code == strategy_code,
            )
            .order_by(StrategyDecisionSnapshot.candle_timestamp.desc())
            .limit(limit)
        )
    )
    return [row.to_dict() for row in rows]


@app.get("/api/v1/experiments/{experiment_id}/strategy-trades", tags=["Strategy Comparison"])
def list_strategy_trades(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    session: Session = Depends(get_session),
):
    _get_experiment_or_404(session, experiment_id)
    rows = list(
        session.scalars(
            select(StrategySimulatedTrade)
            .where(
                StrategySimulatedTrade.experiment_id == experiment_id,
                StrategySimulatedTrade.strategy_code == strategy_code,
            )
            .order_by(StrategySimulatedTrade.executed_at.desc())
        )
    )
    return [row.to_dict() for row in rows]


@app.get(
    "/api/v1/experiments/{experiment_id}/strategy-market-snapshots",
    tags=["Strategy Comparison"],
)
def list_strategy_market_snapshots(
    experiment_id: str,
    strategy_code: str = Query(default=CURRENT_HYBRID),
    limit: int = Query(default=120, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    _get_experiment_or_404(session, experiment_id)
    rows = list(
        session.scalars(
            select(StrategyMarketSnapshot)
            .where(
                StrategyMarketSnapshot.experiment_id == experiment_id,
                StrategyMarketSnapshot.strategy_code == strategy_code,
            )
            .order_by(StrategyMarketSnapshot.observed_at.desc())
            .limit(limit)
        )
    )
    return [row.to_dict() for row in rows]


# Backward-compatible aliases that now return the Current Hybrid strategy.
@app.get("/api/v1/experiments/{experiment_id}/decisions", tags=["Compatibility"])
def list_decisions_alias(
    experiment_id: str,
    limit: int = Query(default=100, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    return list_strategy_decisions(experiment_id, CURRENT_HYBRID, limit, session)


@app.get("/api/v1/experiments/{experiment_id}/trades", tags=["Compatibility"])
def list_trades_alias(
    experiment_id: str,
    session: Session = Depends(get_session),
):
    return list_strategy_trades(experiment_id, CURRENT_HYBRID, session)


@app.get("/api/v1/experiments/{experiment_id}/market-snapshots", tags=["Compatibility"])
def list_market_snapshots_alias(
    experiment_id: str,
    limit: int = Query(default=120, ge=1, le=2000),
    session: Session = Depends(get_session),
):
    return list_strategy_market_snapshots(experiment_id, CURRENT_HYBRID, limit, session)


@app.get("/api/v1/experiments/{experiment_id}/export-bundle", tags=["Exports"])
def download_export_bundle(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    experiment = _get_experiment_or_404(session, experiment_id)
    buffer = export_builder.build_bundle(session, experiment)
    filename = f"{experiment.market}-{experiment.id}-strategy-comparison.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Storage": "memory-only",
            "Cache-Control": "no-store",
        },
    )


@app.get("/api/v1/experiments/{experiment_id}/report-bundle", tags=["Compatibility"])
def download_legacy_bundle(
    experiment_id: str,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    return download_export_bundle(experiment_id, session)


def _strategy_summary(
    session: Session, account: StrategyAccount, market_price: float | None
) -> dict:
    trades = list(
        session.scalars(
            select(StrategySimulatedTrade).where(
                StrategySimulatedTrade.strategy_account_id == account.id
            )
        )
    )
    sells = [row for row in trades if row.side == "SELL" and row.realized_pnl is not None]
    wins = [row for row in sells if float(row.realized_pnl or 0) > 0]
    losses = [row for row in sells if float(row.realized_pnl or 0) < 0]
    net_profit = sum(float(row.realized_pnl or 0) for row in wins)
    net_loss = abs(sum(float(row.realized_pnl or 0) for row in losses))

    closed_gross_pnl = sum(
        float(row.gross_pnl_before_exit_costs or 0.0) for row in sells
    )
    open_gross_pnl = 0.0
    if account.has_open_position and market_price is not None:
        entry = float(
            account.entry_market_price
            or account.entry_execution_price
            or account.average_entry_price
            or 0.0
        )
        open_gross_pnl = float(account.asset_quantity or 0.0) * (float(market_price) - entry)
    gross_pnl = closed_gross_pnl + open_gross_pnl
    gross_equity = account.initial_capital + gross_pnl

    payload = account.to_public_dict(market_price)
    latest_snapshot = session.scalar(
        select(StrategyMarketSnapshot)
        .where(StrategyMarketSnapshot.strategy_account_id == account.id)
        .order_by(StrategyMarketSnapshot.observed_at.desc())
        .limit(1)
    )
    if latest_snapshot is not None:
        payload["current_equity"] = latest_snapshot.total_equity
        payload["net_return"] = (
            latest_snapshot.total_equity / account.initial_capital - 1
            if account.initial_capital > 0
            else 0.0
        )

    current_equity = float(payload.get("current_equity") or account.initial_capital)
    net_pnl = current_equity - account.initial_capital
    payload.update(
        {
            "gross_pnl": gross_pnl,
            "gross_equity": gross_equity,
            "gross_return": (
                gross_equity / account.initial_capital - 1
                if account.initial_capital > 0
                else 0.0
            ),
            "net_pnl": net_pnl,
            "estimated_cost_impact": gross_pnl - net_pnl,
            "trade_execution_count": len(trades),
            "completed_trade_count": len(sells),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / len(sells) if sells else None,
            "profit_factor": net_profit / net_loss if net_loss > 0 else None,
            "recovered_trade_count": sum(1 for row in trades if row.is_recovered),
        }
    )
    return payload


def _get_experiment_or_404(session: Session, experiment_id: str) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found.")
    return experiment
