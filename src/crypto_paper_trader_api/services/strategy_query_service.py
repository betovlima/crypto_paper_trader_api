from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from sqlalchemy import func, select
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

    # Older experiments may not have a persisted next adaptive-research schedule.
    # Expose a deterministic fallback so the UI countdown remains meaningful while
    # the worker persists the repaired schedule on its next cycle.
    if (
        account.strategy_code == "ADAPTIVE_STRATEGY_SELECTOR"
        and payload.get("selector_next_research_at") is None
    ):
        base_time = account.selector_last_completed_at
        if base_time is None:
            base_time = datetime.now(timezone.utc)
        elif base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)
        payload["selector_next_research_at"] = base_time + timedelta(hours=1)
        payload["selector_schedule_inferred"] = True

    if account.selector_candidate_scores is None:
        latest_selector_snapshot = session.scalar(
            select(StrategyDecisionSnapshot)
            .where(
                StrategyDecisionSnapshot.strategy_account_id == account.id,
                StrategyDecisionSnapshot.selector_candidate_scores.is_not(None),
            )
            .order_by(StrategyDecisionSnapshot.candle_timestamp.desc())
            .limit(1)
        )
        if latest_selector_snapshot is not None:
            payload["selector_candidate_scores"] = (
                latest_selector_snapshot.selector_candidate_scores
            )
            payload["selector_research_status"] = (
                account.selector_research_status
                or latest_selector_snapshot.selector_research_status
            )
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



def list_strategy_trade_history(
    session: Session,
    experiment_id: str,
    strategy_code: str,
    page: int,
    page_size: int,
    side: str | None = None,
    result: str | None = None,
    recovered: bool | None = None,
    selected_strategy_code: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    sort_direction: str = "desc",
) -> dict:
    get_experiment_or_404(session, experiment_id)
    filters = [
        StrategySimulatedTrade.experiment_id == experiment_id,
        StrategySimulatedTrade.strategy_code == strategy_code,
    ]
    if side:
        filters.append(StrategySimulatedTrade.side == side.strip().upper())
    normalized_result = (result or "").strip().upper()
    if normalized_result == "PROFIT":
        filters.extend(
            [
                StrategySimulatedTrade.side == "SELL",
                StrategySimulatedTrade.realized_pnl > 0,
            ]
        )
    elif normalized_result == "LOSS":
        filters.extend(
            [
                StrategySimulatedTrade.side == "SELL",
                StrategySimulatedTrade.realized_pnl < 0,
            ]
        )
    elif normalized_result in {"BREAK_EVEN", "BREAKEVEN"}:
        filters.extend(
            [
                StrategySimulatedTrade.side == "SELL",
                StrategySimulatedTrade.realized_pnl == 0,
            ]
        )
    if recovered is not None:
        filters.append(StrategySimulatedTrade.is_recovered.is_(recovered))
    if selected_strategy_code:
        filters.append(
            StrategySimulatedTrade.selected_strategy_code
            == selected_strategy_code.strip().upper()
        )
    if start_date:
        filters.append(StrategySimulatedTrade.executed_at >= start_date)
    if end_date:
        filters.append(StrategySimulatedTrade.executed_at <= end_date)

    total_items = int(
        session.scalar(select(func.count(StrategySimulatedTrade.id)).where(*filters)) or 0
    )
    order_column = (
        StrategySimulatedTrade.executed_at.asc()
        if sort_direction.strip().lower() == "asc"
        else StrategySimulatedTrade.executed_at.desc()
    )
    rows = list(
        session.scalars(
            select(StrategySimulatedTrade)
            .where(*filters)
            .order_by(order_column)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    # Summary is calculated over the complete filtered set, not only the current page.
    summary_rows = list(
        session.scalars(select(StrategySimulatedTrade).where(*filters))
    )
    exits = [row for row in summary_rows if row.side == "SELL" and row.realized_pnl is not None]
    profitable = sum(1 for row in exits if float(row.realized_pnl or 0.0) > 0)
    losing = sum(1 for row in exits if float(row.realized_pnl or 0.0) < 0)
    break_even = len(exits) - profitable - losing
    total_pages = math.ceil(total_items / page_size) if total_items else 0
    return {
        "items": [row.to_dict() for row in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
        },
        "summary": {
            "total_trades": total_items,
            "buy_count": sum(1 for row in summary_rows if row.side == "BUY"),
            "sell_count": len(exits),
            "profitable_exits": profitable,
            "losing_exits": losing,
            "break_even_exits": break_even,
            "total_transaction_cost": sum(
                float(row.total_transaction_cost or 0.0) for row in summary_rows
            ),
            "total_realized_pnl": sum(float(row.realized_pnl or 0.0) for row in exits),
            "win_rate": profitable / len(exits) if exits else None,
        },
    }
