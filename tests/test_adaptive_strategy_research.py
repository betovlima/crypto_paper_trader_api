from __future__ import annotations

import pandas as pd
import httpx

from crypto_paper_trader_api.adaptive_strategy_research import (
    MarketRegimeAnalyzer,
    OpenAIServiceError,
    StrategySpecification,
    WebStrategyResearcher,
    _raise_for_openai_status,
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
    assert spec.origin == "AI_GENERATED"


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


def test_market_regime_analyzer_prioritizes_confirmed_range_over_weak_trend() -> None:
    current = pd.Series(
        {
            "close": 100.4,
            "ema_20": 100.2,
            "ema_50": 100.0,
            "ema_200": 98.0,
            "adx_14": 14.0,
            "volatility_20": 0.008,
            "atr_pct": 0.009,
            "return_6": 0.001,
            "relative_volume": 0.9,
            "range_bound_score": 74.0,
        }
    )
    trend = pd.Series({"close": 100.3, "ema_50": 100.0, "ema_200": 97.5})
    assert MarketRegimeAnalyzer.detect(current, trend) == "SIDEWAYS"

import json
from datetime import datetime, timezone

from crypto_paper_trader_api.adaptive_strategy_research import (
    AdaptiveStrategyResearchEngine,
    GeneratedStrategyExecutor,
    StrategyTemplateLibrary,
    StrategyValidationMetrics,
)
from crypto_paper_trader_api.execution_costs import ExecutionCosts
from crypto_paper_trader_api.multi_strategy import AdaptiveStrategySelector


def test_transition_regime_generates_pattern_aware_controlled_candidates() -> None:
    candidates = StrategyTemplateLibrary().candidates("TRANSITION")
    assert len(candidates) == 24
    assert {candidate.family for candidate in candidates} == {
        "TREND_PULLBACK",
        "MOMENTUM_CONTINUATION",
        "DONCHIAN_BREAKOUT",
        "VOLATILITY_BREAKOUT",
        "MEAN_REVERSION",
        "EMA_CANDLE_PULLBACK",
        "CANDLE_REVERSAL",
        "BOLLINGER_MEAN_REVERSION",
        "SUPPORT_CANDLE_REVERSAL",
        "FALSE_BREAKOUT_REVERSAL",
        "STOCHASTIC_RANGE",
    }


def test_sideways_regime_includes_dedicated_range_bound_families() -> None:
    candidates = StrategyTemplateLibrary().candidates("SIDEWAYS")
    families = {candidate.family for candidate in candidates}
    assert {
        "BOLLINGER_MEAN_REVERSION",
        "SUPPORT_CANDLE_REVERSAL",
        "FALSE_BREAKOUT_REVERSAL",
        "STOCHASTIC_RANGE",
    }.issubset(families)


def test_bollinger_range_reversion_requires_range_context() -> None:
    settings = Settings(_env_file=None)
    executor = GeneratedStrategyExecutor(settings)
    spec = next(
        candidate
        for candidate in StrategyTemplateLibrary().candidates("SIDEWAYS")
        if candidate.family == "BOLLINGER_MEAN_REVERSION"
    )
    frame = pd.DataFrame(
        [
            {
                "open": 99.0,
                "high": 100.0,
                "low": 98.0,
                "close": 98.8,
                "atr_14": 1.0,
                "rsi_14": 30.0,
                "adx_14": 14.0,
                "relative_volume": 0.9,
                "ema_20": 100.0,
                "ema_50": 100.1,
                "ema_200": 98.0,
                "bollinger_lower_20": 98.7,
                "bollinger_zscore_20": -1.7,
                "range_support_24": 98.0,
                "range_resistance_24": 103.0,
                "range_position_24": 0.16,
                "range_bound_score": 72.0,
                "stochastic_k_14": 18.0,
                "stochastic_d_3": 20.0,
            },
            {
                "open": 98.6,
                "high": 99.4,
                "low": 98.3,
                "close": 99.2,
                "atr_14": 1.0,
                "rsi_14": 34.0,
                "adx_14": 15.0,
                "relative_volume": 0.95,
                "ema_20": 100.0,
                "ema_50": 100.1,
                "ema_200": 98.0,
                "bollinger_lower_20": 99.0,
                "bollinger_zscore_20": -1.8,
                "range_support_24": 98.0,
                "range_resistance_24": 103.0,
                "range_position_24": 0.24,
                "range_bound_score": 74.0,
                "stochastic_k_14": 25.0,
                "stochastic_d_3": 22.0,
            },
        ]
    )

    approved, reason = executor.entry_signal(spec, frame, 1, "SIDEWAYS")
    assert approved is True
    assert reason == "bollinger_range_reversion_confirmed"

    frame.loc[1, "range_bound_score"] = 30.0
    approved, reason = executor.entry_signal(spec, frame, 1, "SIDEWAYS")
    assert approved is False
    assert reason == "bollinger_range_reversion_not_ready"


def test_research_payload_preserves_best_rejected_candidate(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        adaptive_research_web_enabled=False,
        adaptive_research_ai_review_enabled=False,
        adaptive_research_max_candidates=15,
    )
    engine = AdaptiveStrategyResearchEngine(settings)
    monkeypatch.setattr(
        engine.backtest,
        "history_diagnostics",
        lambda _frame: {
            "raw_candles": 1200,
            "clean_candles": 1001,
            "required_clean_candles": 800,
            "indicator_warmup_rows": 199,
            "sufficient": True,
        },
    )

    def fake_validate(spec, frame, costs):
        score = 57.8 if "Balanced" in spec.name else 41.0
        return StrategyValidationMetrics(
            score=score,
            net_return=0.014,
            max_drawdown_pct=0.062,
            profit_factor=1.16,
            trade_count=7,
            win_rate=0.42,
            expectancy_r=0.08,
            average_win_r=1.4,
            average_loss_r=-0.7,
            stability=2 / 3,
            fold_returns=(0.01, -0.002, 0.008),
            positive_fold_count=2,
            required_positive_folds=2,
            hard_failures=("INSUFFICIENT_VALIDATED_TRADES",),
            soft_warnings=("BELOW_IDEAL_TRADE_COUNT",),
            eligible=False,
        )

    monkeypatch.setattr(engine.backtest, "validate", fake_validate)
    outcome = engine.research(
        market="SOLBTC",
        regime="TRANSITION",
        execution_timeframe="1hour",
        trend_timeframe="4hour",
        frame=pd.DataFrame(),
        costs=ExecutionCosts(0.0, 0.0005, 0.0002, 0.0005, "TEST"),
        now=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    payload = json.loads(outcome.candidate_scores_json)
    assert outcome.specification is None
    assert outcome.research_summary == "NO_CANDIDATE_PASSED_HARD_GATES"
    assert payload["tested_count"] == 15
    assert payload["approved_count"] == 0
    assert payload["best_candidate"]["score"] == 57.8
    assert payload["best_candidate"]["hard_failures"] == [
        "INSUFFICIENT_VALIDATED_TRADES"
    ]
    assert payload["rejection_summary"] == [
        {"code": "INSUFFICIENT_VALIDATED_TRADES", "count": 15}
    ]


def test_insufficient_history_skips_openai_and_exposes_no_fake_metrics(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="server-only-test-key",
        adaptive_research_web_enabled=True,
        adaptive_research_ai_review_enabled=True,
    )
    engine = AdaptiveStrategyResearchEngine(settings)

    def unexpected_web_call(*_args, **_kwargs):
        raise AssertionError("OpenAI must not be called before local history is ready.")

    monkeypatch.setattr(engine.web, "research", unexpected_web_call)
    monkeypatch.setattr(
        engine.backtest,
        "history_diagnostics",
        lambda _frame: {
            "raw_candles": 999,
            "clean_candles": 799,
            "required_clean_candles": 800,
            "indicator_warmup_rows": 200,
            "sufficient": False,
        },
    )

    outcome = engine.research(
        market="BTCUSDT",
        regime="WEAK_UPTREND",
        execution_timeframe="1hour",
        trend_timeframe="4hour",
        frame=pd.DataFrame(),
        costs=ExecutionCosts(0.0, 0.0005, 0.0002, 0.0005, "TEST"),
        now=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    payload = json.loads(outcome.candidate_scores_json)
    assert outcome.research_status == "WAITING_FOR_HISTORY"
    assert outcome.research_summary == "INSUFFICIENT_HISTORY_PENDING"
    assert payload["best_candidate"] is None
    assert payload["tested_count"] == 0
    assert payload["web_research_status"] == "SKIPPED_INSUFFICIENT_HISTORY"
    assert payload["history"]["clean_candles"] == 799
    assert payload["history"]["required_clean_candles"] == 800


def test_bearish_spot_regime_waits_without_inventing_a_long_candidate(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key="server-only-test-key",
        adaptive_research_web_enabled=True,
    )
    engine = AdaptiveStrategyResearchEngine(settings)
    monkeypatch.setattr(
        engine.backtest,
        "history_diagnostics",
        lambda _frame: {
            "raw_candles": 1200,
            "clean_candles": 1001,
            "required_clean_candles": 800,
            "indicator_warmup_rows": 199,
            "sufficient": True,
        },
    )

    def unexpected_web_call(*_args, **_kwargs):
        raise AssertionError("A long-only Spot selector must not research entries in a downtrend.")

    monkeypatch.setattr(engine.web, "research", unexpected_web_call)
    outcome = engine.research(
        market="BTCUSDT",
        regime="WEAK_DOWNTREND",
        execution_timeframe="1hour",
        trend_timeframe="4hour",
        frame=pd.DataFrame(),
        costs=ExecutionCosts(0.0, 0.0005, 0.0002, 0.0005, "TEST"),
        now=datetime(2026, 7, 22, tzinfo=timezone.utc),
    )

    payload = json.loads(outcome.candidate_scores_json)
    assert StrategyTemplateLibrary().candidates("WEAK_DOWNTREND") == []
    assert outcome.research_status == "WAITING_FOR_MARKET_RECOVERY"
    assert outcome.research_summary == "NO_LONG_STRATEGY_FOR_BEARISH_REGIME"
    assert payload["generated_count"] == 0
    assert payload["tested_count"] == 0
    assert payload["best_candidate"] is None
    assert payload["market_action"] == "WAIT_FOR_RECOVERY"
    assert payload["web_research_status"] == "SKIPPED_BEARISH_REGIME"


def test_insufficient_history_metrics_do_not_encode_a_fake_total_drawdown() -> None:
    settings = Settings(
        _env_file=None,
        adaptive_research_web_enabled=False,
        adaptive_research_ai_review_enabled=False,
    )
    engine = AdaptiveStrategyResearchEngine(settings)
    spec = StrategyTemplateLibrary().candidates("WEAK_UPTREND")[0]
    timestamps = pd.date_range("2026-01-01", periods=500, freq="1h", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "atr_14": 1.0,
            "rsi_14": 50.0,
            "adx_14": 22.0,
            "relative_volume": 1.1,
            "ema_13": 100.0,
            "ema_20": 99.8,
            "ema_34": 99.5,
            "ema_50": 99.0,
            "ema_200": 95.0,
        }
    )

    metrics = engine.backtest.validate(
        spec,
        frame,
        ExecutionCosts(0.0, 0.0005, 0.0002, 0.0005, "TEST"),
    )

    assert metrics.metrics_available is False
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.hard_failures == ("INSUFFICIENT_HISTORY",)
    assert metrics.clean_candle_count == 500


def test_public_openai_error_includes_response_body_and_redacts_keys() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        400,
        request=request,
        text='{"error":{"message":"invalid key sk-secret-example"}}',
    )
    error = httpx.HTTPStatusError("Bad request", request=request, response=response)

    public = AdaptiveStrategyResearchEngine._public_error(error)

    assert "invalid key" in public
    assert "sk-secret-example" not in public
    assert "Incorrect API key provided" not in public
    assert len(public) < 400



def test_openai_401_exposes_invalid_key_code_and_configuration_source() -> None:
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        json={
            "error": {
                "message": "Incorrect API key provided: sk-secret-example",
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        },
    )

    try:
        _raise_for_openai_status(response, "PROJECT_ENV_FILE")
    except OpenAIServiceError as exc:
        public = str(exc)
    else:
        raise AssertionError("A 401 response must raise OpenAIServiceError")

    assert "code=invalid_api_key" in public
    assert "source=PROJECT_ENV_FILE" in public
    assert "sk-secret-example" not in public
    assert "Incorrect API key provided" not in public
    assert len(public) < 400


def test_openai_401_distinguishes_ip_allowlist_rejection() -> None:
    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
        json={
            "error": {
                "message": "Your IP is not authorized to access this organization.",
                "type": "ip_not_authorized",
                "code": "ip_not_authorized",
            }
        },
    )

    try:
        _raise_for_openai_status(response, "PROJECT_ENV_FILE")
    except OpenAIServiceError as exc:
        public = str(exc)
    else:
        raise AssertionError("A 401 response must raise OpenAIServiceError")

    assert "code=ip_not_authorized" in public
    assert "public IP is not authorized" in public

def test_champion_is_suspended_during_transition() -> None:
    specification = StrategySpecification(
        code="GEN_TREND_PULLBACK_TEST",
        name="Champion",
        family="TREND_PULLBACK",
        origin="SYSTEM_GENERATED",
        rationale="test",
        allowed_regimes=("STRONG_UPTREND", "TRANSITION"),
    )
    assert not AdaptiveStrategySelector._champion_is_compatible(
        specification,
        "TRANSITION",
    )
    assert AdaptiveStrategySelector._champion_is_compatible(
        specification,
        "STRONG_UPTREND",
    )
