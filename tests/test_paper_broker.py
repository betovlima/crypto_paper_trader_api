from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import Experiment
from crypto_paper_trader_api.paper_broker import PaperBroker


def make_experiment() -> Experiment:
    now = datetime.now(timezone.utc)
    return Experiment(
        id="test-experiment",
        market="BTCUSDT",
        execution_timeframe="15min",
        trend_timeframe="1hour",
        duration_hours=24,
        status="RUNNING",
        started_at=now,
        scheduled_end_at=now,
        initial_capital=1000,
        cash_balance=1000,
        asset_quantity=0,
        vip_level="API_SPOT",
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        fee_source="TEST",
        last_spread_rate=0.0002,
        average_spread_rate=0.0002,
        spread_observations=1,
        total_fees=0,
        total_spread_cost=0,
        total_slippage_cost=0,
        realized_pnl=0,
        max_equity=1000,
        max_drawdown_pct=0,
        consecutive_losses=0,
    )


def test_buy_and_sell_include_vip0_costs_and_stops() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(data_dir="./test-data")
    broker = PaperBroker(settings)
    costs = ExecutionCosts(
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        spread_rate=0.0002,
        slippage_rate=0.0005,
        fee_source="TEST",
    )
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        experiment = make_experiment()
        session.add(experiment)
        session.flush()

        buy = broker.buy(
            session,
            experiment,
            market_price=100,
            atr=2,
            costs=costs,
            executed_at=now,
            reason="test",
            decision_id=None,
        )
        assert buy.side == "BUY"
        assert buy.fee_rate == 0.002
        assert buy.spread_cost > 0
        assert buy.slippage_cost > 0
        assert experiment.asset_quantity > 0
        assert experiment.stop_loss_price is not None
        assert experiment.take_profit_price is not None
        stop_distance_pct = 1 - experiment.stop_loss_price / experiment.average_entry_price
        assert (
            settings.stop_loss_min_pct - 1e-12
            <= stop_distance_pct
            <= settings.stop_loss_max_pct + 1e-12
        )

        sell = broker.sell(
            session,
            experiment,
            market_price=110,
            costs=costs,
            executed_at=now,
            reason="test",
            decision_id=None,
        )
        assert sell.side == "SELL"
        assert sell.total_transaction_cost > 0
        assert sell.realized_pnl is not None and sell.realized_pnl > 0
        assert experiment.asset_quantity == 0
        assert experiment.total_fees > 0
        assert experiment.total_spread_cost > 0
        assert experiment.total_slippage_cost > 0


def test_mexc_api_round_trip_cost_uses_conservative_taker_baseline() -> None:
    settings = Settings(data_dir="./test-data")
    # 0.05% + 0.05% fees, 0.02% spread and 0.05% slippage on each side.
    assert abs(settings.round_trip_cost_rate - 0.0022) < 1e-12
