from __future__ import annotations

import pandas as pd

from crypto_paper_trader_api.adaptive_strategy_research import (
    MarketRegimeAnalyzer,
    StrategySpecification,
    StrategyTemplateLibrary,
)
from crypto_paper_trader_api.config import Settings


def test_strategy_specification_round_trip() -> None:
    spec = StrategySpecification(
        code="GEN_TREND_PULLBACK_TEST",
        name="Adaptive EMA ATR Pullback",
        family="TREND_PULLBACK",
        origin="SYSTEM_GENERATED",
        rationale="test",
        allowed_regimes=("STRONG_UPTREND",),
        source_urls=("https://example.com/research",),
    )
    restored = StrategySpecification.from_json(spec.to_json())
    assert restored == spec


def test_local_template_library_generates_supported_strategy_schema() -> None:
    candidates = StrategyTemplateLibrary().candidates("STRONG_UPTREND")
    assert candidates
    assert all(candidate.origin != "WEB_RESEARCHED" for candidate in candidates)
    assert all(candidate.family in {
        "TREND_PULLBACK", "DONCHIAN_BREAKOUT", "VOLATILITY_BREAKOUT",
        "MEAN_REVERSION", "MOMENTUM_CONTINUATION",
    } for candidate in candidates)

def test_market_regime_analyzer_detects_strong_uptrend() -> None:
    current = pd.Series(
        {
            "close": 110.0,
            "ema_20": 106.0,
            "ema_50": 102.0,
            "ema_200": 90.0,
            "adx_14": 30.0,
            "volatility_20": 0.01,
            "atr_pct": 0.01,
            "return_6": 0.02,
            "relative_volume": 1.3,
        }
    )
    trend = pd.Series({"close": 108.0, "ema_50": 100.0, "ema_200": 92.0})
    assert MarketRegimeAnalyzer.detect(current, trend) == "STRONG_UPTREND"
