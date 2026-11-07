"""Regression tests for the closed-candle decision evaluator extraction."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.multi_strategy import StrategyDecision
from crypto_paper_trader_api.strategy_codes import (
    ADAPTIVE_STRATEGY_SELECTOR,
    CURRENT_HYBRID,
)
from crypto_paper_trader_api.trading_profiles import (
    DEFAULT_TRADING_PROFILE,
    get_trading_profile,
)
from crypto_paper_trader_api.worker import TraderWorker


def _costs() -> ExecutionCosts:
    return ExecutionCosts(
        maker_fee_rate=0.001,
        taker_fee_rate=0.001,
        spread_rate=0.0002,
        slippage_rate=0.0003,
        fee_source="TEST",
    )


def _decision(**kwargs) -> StrategyDecision:
    return StrategyDecision(
        technical_signal="HOLD",
        model_signal="HOLD",
        final_signal="HOLD",
        technical_confirmations=0,
        reason="Test fixture",
        **kwargs,
    )


def test_specialist_decisions_skip_selector_and_keep_order() -> None:
    worker = TraderWorker(Settings())
    specialist = StrategyAccount(
        strategy_code=CURRENT_HYBRID, asset_quantity=0.0
    )
    selector = StrategyAccount(
        strategy_code=ADAPTIVE_STRATEGY_SELECTOR, asset_quantity=0.0
    )
    expected_decision = _decision()
    worker.hybrid_strategy.decide = Mock(return_value=expected_decision)
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    row = pd.Series({"close": 101.0, "high": 102.0})
    frame = pd.DataFrame({"close": [99.0, 100.0, 101.0]})
    costs = _costs()
    profile = get_trading_profile(DEFAULT_TRADING_PROFILE)

    decisions = asyncio.run(
        worker._evaluate_specialist_decisions(
            accounts=[specialist, selector],
            execution_indicators=frame,
            current_index=2,
            execution_row=row,
            previous_row=row,
            previous_previous_row=row,
            trend_row=row,
            ai_model_frame=frame,
            prediction=None,
            costs=costs,
            profile=profile,
            candle_timestamp=now,
            candle_end=now + timedelta(minutes=30),
            atr=2.5,
        )
    )

    assert list(decisions) == [CURRENT_HYBRID]
    assert decisions[CURRENT_HYBRID] is expected_decision
    assert specialist.last_atr_14 == 2.5
    assert selector.last_atr_14 is None
    worker.hybrid_strategy.decide.assert_called_once()
    assert worker.hybrid_strategy.decide.call_args.kwargs["now"] == (
        now + timedelta(minutes=30)
    )


def test_selector_decision_updates_state_and_preserves_missing_diagnostics() -> None:
    worker = TraderWorker(Settings())
    selector = StrategyAccount(
        strategy_code=ADAPTIVE_STRATEGY_SELECTOR,
        asset_quantity=0.0,
        selector_selected_strategy="previous-strategy",
        selector_research_status="WAITING_FOR_HISTORY",
        selector_validation_score=0.8,
    )
    new_decision = _decision(
        selector_market_regime="TRENDING",
        selector_confidence=0.72,
        selector_expected_net_return=0.04,
        selector_research_status=None,
        selector_validation_score=None,
    )
    worker.adaptive_selector.decide = Mock(return_value=new_decision)
    worker._with_history_sync_diagnostics = Mock(
        side_effect=lambda decision, *_args: decision
    )
    now = datetime(2026, 11, 7, tzinfo=timezone.utc)
    decisions = {CURRENT_HYBRID: _decision()}
    experiment = Experiment(
        id="selector-test",
        market="BTCUSDT",
        execution_timeframe="30min",
        trend_timeframe="1hour",
    )

    asyncio.run(
        worker._evaluate_selector_decision(
            experiment=experiment,
            accounts_by_code={ADAPTIVE_STRATEGY_SELECTOR: selector},
            execution_row=pd.Series({"high": 105.0}),
            trend_row=pd.Series(dtype=float),
            ai_model_frame=pd.DataFrame({"close": [100.0]}),
            costs=_costs(),
            profile=get_trading_profile(DEFAULT_TRADING_PROFILE),
            candle_end=now,
            atr=2.0,
            decisions=decisions,
        )
    )

    assert decisions[ADAPTIVE_STRATEGY_SELECTOR] is new_decision
    assert selector.last_atr_14 == 2.0
    assert selector.selector_market_regime == "TRENDING"
    assert selector.selector_confidence == 0.72
    assert selector.selector_expected_net_return == 0.04
    assert selector.selector_selected_strategy == "previous-strategy"
    assert selector.selector_research_status == "WAITING_FOR_HISTORY"
    assert selector.selector_validation_score == 0.8
    worker.adaptive_selector.decide.assert_called_once()


def test_selector_evaluation_is_noop_if_account_is_missing() -> None:
    worker = TraderWorker(Settings())
    decisions = {CURRENT_HYBRID: _decision()}
    original = decisions.copy()
    asyncio.run(
        worker._evaluate_selector_decision(
            experiment=Experiment(
                id="no-selector",
                market="BTCUSDT",
                execution_timeframe="30min",
                trend_timeframe="1hour",
            ),
            accounts_by_code={},
            execution_row=pd.Series(dtype=float),
            trend_row=pd.Series(dtype=float),
            ai_model_frame=pd.DataFrame(),
            costs=_costs(),
            profile=get_trading_profile(DEFAULT_TRADING_PROFILE),
            candle_end=datetime(2026, 11, 7, tzinfo=timezone.utc),
            atr=1.0,
            decisions=decisions,
        )
    )
    assert decisions == original
