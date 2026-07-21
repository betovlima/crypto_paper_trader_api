from __future__ import annotations

import pandas as pd

from crypto_paper_trader_api.adaptive_strategy_research import (
    MarketRegimeAnalyzer,
    StrategySpecification,
    WebStrategyResearcher,
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


def test_web_research_json_is_constrained_to_supported_strategy_schema() -> None:
    researcher = WebStrategyResearcher(Settings(_env_file=None, openai_api_key=None))
    payload = researcher._parse_json(
        """
        ```json
        {
          "summary": "Research summary",
          "strategies": [{
            "name": "Web Pullback",
            "family": "TREND_PULLBACK",
            "rationale": "Regime fit",
            "parameters": {"fast_ema": 11, "slow_ema": 27, "stop_atr": 1.7}
          }]
        }
        ```
        """
    )
    spec = researcher._build_spec(
        payload["strategies"][0],
        "STRONG_UPTREND",
        ("https://example.com/source",),
    )
    assert spec is not None
    assert spec.family == "TREND_PULLBACK"
    assert spec.fast_ema in {5, 9, 13, 20, 21, 34, 50, 200}
    assert spec.slow_ema in {5, 9, 13, 20, 21, 34, 50, 200}
    assert spec.origin == "WEB_RESEARCHED"


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
