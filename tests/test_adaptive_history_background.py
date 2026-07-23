from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import crypto_paper_trader_api.worker as worker_module
from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.multi_strategy import StrategyDecision
from crypto_paper_trader_api.strategy_codes import ADAPTIVE_STRATEGY_SELECTOR
from crypto_paper_trader_api.worker import TraderWorker


def _experiment(now: datetime) -> Experiment:
    return Experiment(
        id="background-history-test",
        market="SOLBTC",
        trading_profile="BALANCED_INTRADAY",
        execution_timeframe="30min",
        trend_timeframe="1hour",
        duration_hours=24.0,
        status="RUNNING",
        started_at=now - timedelta(hours=1),
        scheduled_end_at=now + timedelta(hours=23),
        initial_capital=1000.0,
        cash_balance=1000.0,
        asset_quantity=0.0,
        max_equity=1000.0,
    )


def _selector_account(experiment_id: str, now: datetime) -> StrategyAccount:
    return StrategyAccount(
        experiment_id=experiment_id,
        strategy_code=ADAPTIVE_STRATEGY_SELECTOR,
        display_name="Adaptive Strategy Selector",
        status="ACTIVE",
        initial_capital=1000.0,
        cash_balance=1000.0,
        asset_quantity=0.0,
        max_equity=1000.0,
        selector_research_status="WAITING_FOR_HISTORY",
        selector_research_summary="INSUFFICIENT_HISTORY_PENDING",
        selector_next_research_at=now - timedelta(minutes=1),
    )


def test_due_history_refresh_runs_without_a_new_candle(monkeypatch) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(worker_module, "SessionLocal", testing_session)

    now = datetime.now(timezone.utc)
    with testing_session() as session:
        experiment = _experiment(now)
        session.add(experiment)
        session.flush()
        session.add(_selector_account(experiment.id, now))
        session.commit()

    worker = TraderWorker(Settings())
    calls: list[str] = []

    async def fake_refresh(*, session, experiment, selector_account, now):
        calls.append(experiment.id)
        return {
            "experiment_id": experiment.id,
            "selector_status": selector_account.selector_research_status,
            "history": {"status": "PARTIAL"},
        }

    monkeypatch.setattr(worker, "_refresh_selector_account_from_history", fake_refresh)

    try:
        result = asyncio.run(worker._refresh_waiting_selector_history())
    finally:
        asyncio.run(worker.client.close())

    assert calls == ["background-history-test"]
    assert result["experiment_id"] == "background-history-test"


def test_history_sync_diagnostics_are_merged_into_selector_payload(monkeypatch) -> None:
    worker = TraderWorker(Settings())
    monkeypatch.setattr(
        worker.ai_history_service,
        "diagnostics",
        lambda market, timeframe: {
            "status": "PARTIAL",
            "stored_candles": 314,
            "target_candles": 1100,
            "pages_attempted": 4,
            "pages_succeeded": 2,
            "candles_added_last_attempt": 0,
            "empty_windows_last_attempt": 2,
            "last_error": "No older page returned data.",
            "last_attempt_at": datetime(2026, 7, 23, 2, 5, tzinfo=timezone.utc),
            "next_retry_at": datetime(2026, 7, 23, 2, 6, tzinfo=timezone.utc),
        },
    )
    decision = StrategyDecision(
        technical_signal="HOLD",
        model_signal="WAITING_FOR_HISTORY",
        final_signal="HOLD",
        technical_confirmations=0,
        reason="history pending",
        selector_candidate_scores=json.dumps(
            {"history": {"clean_candles": 314, "required_clean_candles": 800}}
        ),
    )

    try:
        updated = worker._with_history_sync_diagnostics(decision, "SOLBTC", "30min")
    finally:
        asyncio.run(worker.client.close())

    payload = json.loads(updated.selector_candidate_scores or "{}")
    assert payload["history_sync"]["status"] == "PARTIAL"
    assert payload["history_sync"]["pages_attempted"] == 4
    assert payload["history"]["stored_candles"] == 314
    assert payload["history"]["backfill_status"] == "PARTIAL"
    assert payload["history"]["backfill_last_attempt_at"] == "2026-07-23T02:05:00+00:00"
