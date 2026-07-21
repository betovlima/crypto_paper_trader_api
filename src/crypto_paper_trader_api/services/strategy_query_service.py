from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    StrategyAccount,
    StrategyDecisionSnapshot,
    StrategyMarketSnapshot,
    StrategySimulatedTrade,
)
from ..schemas import StrategyComparisonHistoryResponse, StrategyComparisonResponse
from ..strategy_codes import (
    ACTIVE_STRATEGY_CODES,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_DISPLAY_NAMES,
)
from .common import get_experiment_or_404


def strategy_summary(
    session: Session,
    account: StrategyAccount,
    market_price: float | None,
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


def list_strategy_accounts(session: Session, experiment_id: str) -> list[dict]:
    experiment = get_experiment_or_404(session, experiment_id)
    accounts_by_code = {
        account.strategy_code: account
        for account in session.scalars(
            select(StrategyAccount).where(
                StrategyAccount.experiment_id == experiment_id,
                StrategyAccount.strategy_code.in_(ACTIVE_STRATEGY_CODES),
            )
        )
    }
    return [
        strategy_summary(session, accounts_by_code[code], experiment.last_price)
        for code in ACTIVE_STRATEGY_CODES
        if code in accounts_by_code
    ]


def get_strategy_comparison(
    session: Session,
    experiment_id: str,
) -> StrategyComparisonResponse:
    experiment = get_experiment_or_404(session, experiment_id)
    strategies: list[dict] = []
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


def get_strategy_comparison_history(
    session: Session,
    experiment_id: str,
    limit: int,
) -> StrategyComparisonHistoryResponse:
    experiment = get_experiment_or_404(session, experiment_id)
    strategies: list[dict] = []
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


def list_strategy_decisions(
    session: Session,
    experiment_id: str,
    strategy_code: str,
    limit: int,
) -> list[dict]:
    get_experiment_or_404(session, experiment_id)
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


def list_strategy_trades(
    session: Session,
    experiment_id: str,
    strategy_code: str,
) -> list[dict]:
    get_experiment_or_404(session, experiment_id)
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


def list_strategy_market_snapshots(
    session: Session,
    experiment_id: str,
    strategy_code: str,
    limit: int,
) -> list[dict]:
    get_experiment_or_404(session, experiment_id)
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
