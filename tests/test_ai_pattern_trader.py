from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_paper_trader_api.ai_pattern_trader import AI_PATTERN_MODEL_VERSION, AIPatternTrader
from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.indicators import add_indicators
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.strategy_codes import AI_PATTERN_TRADER
from crypto_paper_trader_api.trading_profiles import BALANCED_INTRADAY, get_trading_profile


def _pattern_candles(rows: int = 520) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01", periods=rows, freq="1h", tz="UTC")
    rng = np.random.default_rng(91)
    phase = np.arange(rows)
    recurring_return = 0.00035 + 0.003 * np.sin(phase / 11) + rng.normal(0, 0.002, rows)
    close = 100 * np.cumprod(1 + recurring_return)
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.0006, rows))
    spread = np.maximum(0.0015, np.abs(rng.normal(0.0025, 0.0007, rows)))
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    volume = 1200 + 240 * (1 + np.sin(phase / 7)) + rng.normal(0, 60, rows)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.maximum(volume, 1),
            "value": np.maximum(volume, 1) * close,
        }
    )


def _account() -> StrategyAccount:
    return StrategyAccount(
        experiment_id="test-experiment",
        strategy_code=AI_PATTERN_TRADER,
        display_name="AI Pattern Trader",
        status="ACTIVE",
        initial_capital=1000.0,
        cash_balance=1000.0,
        asset_quantity=0.0,
        max_equity=1000.0,
        max_drawdown_pct=0.0,
        stop_management_mode="AI_DYNAMIC",
    )


def test_ai_pattern_trader_learns_from_candles_and_emits_auditable_decision() -> None:
    settings = Settings(
        ai_pattern_mode="PAPER_AUTONOMOUS",
        ai_pattern_min_training_rows=180,
        ai_pattern_training_max_rows=420,
        ai_pattern_tree_count=32,
        ai_pattern_neighbors=16,
        ai_pattern_clusters=5,
        ai_pattern_confident_rows=300,
    )
    strategy = AIPatternTrader(settings)
    indicators = add_indicators(_pattern_candles()).dropna().reset_index(drop=True)
    trend_row = indicators.iloc[-1]
    costs = ExecutionCosts(
        maker_fee_rate=0.002,
        taker_fee_rate=0.002,
        spread_rate=0.0002,
        slippage_rate=0.0002,
        fee_source="TEST",
    )

    decision = strategy.decide(
        account=_account(),
        frame=indicators,
        trend_row=trend_row,
        costs=costs,
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
        profile=get_trading_profile(BALANCED_INTRADAY),
    )

    assert decision.ai_model_version == AI_PATTERN_MODEL_VERSION
    assert decision.ai_training_samples is not None
    assert decision.ai_training_samples >= settings.ai_pattern_min_training_rows
    assert decision.ai_pattern_cluster is not None
    assert decision.ai_neighbor_count == settings.ai_pattern_neighbors
    assert decision.ai_regime in {
        "HIGH_VOLATILITY",
        "LOW_VOLATILITY",
        "TREND_UP",
        "TREND_DOWN",
        "RANGE",
        "BREAKOUT_TEST",
        "TRANSITION",
    }
    assert decision.ai_proposed_action in {"BUY", "HOLD", "SELL"}
    assert decision.final_signal in {"BUY", "HOLD", "SELL"}
    assert decision.ai_risk_status in {"MONITORING", "APPROVED", "BLOCKED"}
    assert decision.ai_confidence is not None and 0 <= decision.ai_confidence <= 1
    assert decision.ai_upward_probability is not None
    assert 0 <= decision.ai_upward_probability <= 1
    assert decision.ai_feature_summary and "return_6" in decision.ai_feature_summary


def test_observation_mode_never_executes_the_proposed_action() -> None:
    settings = Settings(
        ai_pattern_mode="OBSERVATION",
        ai_pattern_min_training_rows=180,
        ai_pattern_training_max_rows=420,
        ai_pattern_tree_count=32,
        ai_pattern_neighbors=16,
        ai_pattern_clusters=5,
        ai_pattern_confident_rows=300,
        ai_pattern_buy_probability_threshold=0.50,
        ai_pattern_min_confidence=0.0,
        ai_pattern_min_expected_net_return=0.0,
    )
    strategy = AIPatternTrader(settings)
    indicators = add_indicators(_pattern_candles()).dropna().reset_index(drop=True)
    decision = strategy.decide(
        account=_account(),
        frame=indicators,
        trend_row=indicators.iloc[-1],
        costs=ExecutionCosts(0.0, 0.0, 0.0, 0.0, "TEST"),
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
        profile=get_trading_profile(BALANCED_INTRADAY),
    )

    assert decision.ai_mode == "OBSERVATION"
    assert decision.final_signal == "HOLD"
    if decision.ai_proposed_action != "HOLD":
        assert decision.ai_risk_status == "OBSERVATION"
