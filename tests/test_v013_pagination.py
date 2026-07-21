from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.models import StrategySimulatedTrade
from crypto_paper_trader_api.services.experiment_service import list_experiment_history
from crypto_paper_trader_api.services.strategy_query_service import list_strategy_trade_history
from crypto_paper_trader_api.strategy_codes import ADAPTIVE_STRATEGY_SELECTOR, EMA_PULLBACK
from crypto_paper_trader_api.worker import create_experiment_record, ensure_strategy_accounts


def memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_experiment_and_trade_history_are_paginated_and_filtered() -> None:
    settings = Settings(_env_file=None)
    session = memory_session()
    try:
        experiments = []
        for index, market in enumerate(["PENDLEUSDT", "BTCUSDT", "PENDLEUSDT"]):
            experiment = create_experiment_record(
                market=market,
                execution_timeframe="30min",
                trend_timeframe="1hour",
                duration_hours=24,
                initial_capital=1000,
                settings=settings,
            )
            experiment.started_at = datetime(2026, 7, 20 + index, tzinfo=timezone.utc)
            experiment.scheduled_end_at = experiment.started_at + timedelta(hours=24)
            experiment.status = "FINISHED"
            session.add(experiment)
            session.flush()
            ensure_strategy_accounts(session, experiment)
            experiments.append(experiment)
        session.flush()

        history = list_experiment_history(
            session,
            page=1,
            page_size=1,
            market="PENDLEUSDT",
            experiment_status="FINISHED",
        )
        assert history.pagination.total_items == 2
        assert history.pagination.total_pages == 2
        assert len(history.items) == 1
        assert history.items[0].market == "PENDLEUSDT"

        target = experiments[0]
        selector = next(
            account
            for account in ensure_strategy_accounts(session, target)
            if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR
        )
        for index, pnl in enumerate([2.5, -1.0, 0.0]):
            session.add(
                StrategySimulatedTrade(
                    experiment_id=target.id,
                    strategy_account_id=selector.id,
                    strategy_code=ADAPTIVE_STRATEGY_SELECTOR,
                    selected_strategy_code=EMA_PULLBACK,
                    executed_at=datetime(2026, 7, 21, index, tzinfo=timezone.utc),
                    side="SELL",
                    order_role="TAKER",
                    market_price=1.65,
                    execution_price=1.649,
                    quantity=100,
                    gross_notional=164.9,
                    fee_rate=0.0005,
                    fee=0.08,
                    spread_rate=0.0002,
                    spread_cost=0.02,
                    slippage_rate=0.0005,
                    slippage_cost=0.08,
                    total_transaction_cost=0.18,
                    realized_pnl=pnl,
                    gross_pnl_before_exit_costs=pnl + 0.18,
                    cash_after=1000 + pnl,
                    asset_quantity_after=0,
                    equity_after=1000 + pnl,
                    reason="test",
                )
            )
        session.commit()

        trades = list_strategy_trade_history(
            session,
            target.id,
            ADAPTIVE_STRATEGY_SELECTOR,
            page=1,
            page_size=10,
            result="PROFIT",
            selected_strategy_code=EMA_PULLBACK,
        )
        assert trades["pagination"]["total_items"] == 1
        assert trades["summary"]["profitable_exits"] == 1
        assert trades["summary"]["total_realized_pnl"] == 2.5
        assert trades["items"][0]["selected_strategy_code"] == EMA_PULLBACK
    finally:
        session.close()
