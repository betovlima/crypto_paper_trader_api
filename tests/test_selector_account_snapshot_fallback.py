from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.models import StrategyDecisionSnapshot
from crypto_paper_trader_api.services.strategy_query_service import strategy_summary
from crypto_paper_trader_api.strategy_codes import ADAPTIVE_STRATEGY_SELECTOR
from crypto_paper_trader_api.worker import create_experiment_record, ensure_strategy_accounts


def test_strategy_summary_recovers_selector_details_from_latest_decision() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings()
    experiment = create_experiment_record("SOLBTC", "30min", "1hour", 24, 1000, settings)
    details = '{"history":{"raw_candles":512,"clean_candles":313,"required_clean_candles":800}}'

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        accounts = ensure_strategy_accounts(session, experiment)
        selector = next(
            account for account in accounts
            if account.strategy_code == ADAPTIVE_STRATEGY_SELECTOR
        )
        selector.selector_candidate_scores = None
        session.flush()

        session.add(
            StrategyDecisionSnapshot(
                experiment_id=experiment.id,
                strategy_account_id=selector.id,
                strategy_code=ADAPTIVE_STRATEGY_SELECTOR,
                candle_timestamp=datetime.now(timezone.utc),
                market_price=0.001,
                candle_high=0.0011,
                candle_low=0.0009,
                maker_fee_rate=0.0,
                taker_fee_rate=0.0005,
                spread_rate=0.0002,
                slippage_rate=0.0005,
                estimated_round_trip_cost_rate=0.0022,
                required_gross_return=0.0022,
                technical_signal="HOLD",
                model_signal="RESEARCH_SELECTOR",
                final_signal="HOLD",
                technical_confirmations=0,
                decision_reason="INSUFFICIENT_HISTORY_PENDING",
                position_before="FLAT",
                action_executed=False,
                selector_candidate_scores=details,
                selector_research_status="WAITING_FOR_HISTORY",
            )
        )
        session.commit()

        payload = strategy_summary(session, selector, experiment.last_price)

    assert payload["selector_candidate_scores"] == details
    assert payload["selector_research_status"] == "WAITING_FOR_HISTORY"
