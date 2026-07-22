from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.multi_broker import MultiStrategyPaperBroker
from crypto_paper_trader_api.strategy_codes import CURRENT_HYBRID
from crypto_paper_trader_api.worker import create_experiment_record


def test_broker_uses_ask_and_bid_without_adding_spread_twice() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(position_allocation=1.0)
    broker = MultiStrategyPaperBroker(settings)
    costs = ExecutionCosts(
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        spread_rate=0.001,
        slippage_rate=0.0005,
        fee_source="TEST",
    )
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        account = StrategyAccount(
            experiment_id=experiment.id,
            strategy_code=CURRENT_HYBRID,
            display_name="Current Hybrid",
            initial_capital=1000,
            cash_balance=1000,
            asset_quantity=0,
            max_equity=1000,
            total_fees=0,
            total_spread_cost=0,
            total_slippage_cost=0,
            realized_pnl=0,
            consecutive_losses=0,
            rejected_signals=0,
            setup_status="N/A",
        )
        session.add(account)
        session.flush()

        entry_candle_timestamp = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
        buy = broker.buy(
            session=session,
            experiment=experiment,
            account=account,
            mid_market_price=100,
            best_ask=100.05,
            atr=1,
            costs=costs,
            executed_at=datetime.now(timezone.utc),
            reason="test",
            decision_id=None,
            entry_candle_timestamp=entry_candle_timestamp,
        )

        assert buy.execution_price == 100.05 * 1.0005
        assert buy.entry_candle_timestamp == entry_candle_timestamp
        assert account.entry_candle_timestamp == entry_candle_timestamp
        assert account.to_public_dict()["entry_candle_timestamp"] == entry_candle_timestamp
        assert buy.spread_cost > 0
        assert buy.slippage_cost > 0

        sell = broker.sell(
            session=session,
            experiment=experiment,
            account=account,
            mid_market_price=100,
            best_bid=99.95,
            costs=costs,
            executed_at=datetime.now(timezone.utc),
            reason="test",
            decision_id=None,
        )

        assert sell.execution_price == 99.95 * 0.9995
        assert account.cash_balance < 1000


def test_fees_change_net_result_but_not_the_technical_stop() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(position_allocation=1.0)
    broker = MultiStrategyPaperBroker(settings)
    costs = ExecutionCosts(
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        spread_rate=0.001,
        slippage_rate=0.0005,
        fee_source="TEST",
    )
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        account = StrategyAccount(
            experiment_id=experiment.id,
            strategy_code=CURRENT_HYBRID,
            display_name="Current Hybrid",
            initial_capital=1000,
            cash_balance=1000,
            asset_quantity=0,
            max_equity=1000,
            setup_status="N/A",
        )
        session.add(account)
        session.flush()

        buy = broker.buy(
            session=session,
            experiment=experiment,
            account=account,
            mid_market_price=100,
            best_ask=100.05,
            atr=1,
            costs=costs,
            executed_at=datetime.now(timezone.utc),
            reason="technical signal",
            decision_id=None,
            stop_override=98.0,
        )
        assert buy.stop_loss_price == 98.0
        assert account.stop_loss_price == 98.0

        sell = broker.sell(
            session=session,
            experiment=experiment,
            account=account,
            mid_market_price=102,
            best_bid=101.95,
            costs=costs,
            executed_at=datetime.now(timezone.utc),
            reason="technical exit",
            decision_id=None,
        )

        assert sell.gross_pnl_before_exit_costs is not None
        assert sell.realized_pnl is not None
        assert sell.gross_pnl_before_exit_costs > sell.realized_pnl
        assert sell.gross_pnl_before_exit_costs > 0
