from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from coinex_paper_trader.config import Settings
from coinex_paper_trader.database import Base
from coinex_paper_trader.strategy_codes import ACTIVE_STRATEGY_CODES
from coinex_paper_trader.worker import create_experiment_record, ensure_strategy_accounts


def test_all_comparison_accounts_are_created() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings()
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        accounts = ensure_strategy_accounts(session, experiment)

        assert tuple(item.strategy_code for item in accounts) == ACTIVE_STRATEGY_CODES
        assert all(item.initial_capital == 1000 for item in accounts)
        assert all(item.cash_balance == 1000 for item in accounts)
