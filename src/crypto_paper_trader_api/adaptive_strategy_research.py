from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
import re
import time
from typing import Any, Iterable

import httpx
import numpy as np
import pandas as pd

from .adaptive_pattern_analysis import (
    BULLISH_CANDLE_PATTERNS,
    BEARISH_CANDLE_PATTERNS,
    CandlestickPatternDetector,
    TimeSeriesPatternAnalyzer,
    TimeSeriesPatternSummary,
)
from .config import Settings
from .execution_costs import ExecutionCosts
from .indicators import add_indicators

logger = logging.getLogger(__name__)

ALLOWED_FAMILIES = {
    "TREND_PULLBACK",
    "DONCHIAN_BREAKOUT",
    "VOLATILITY_BREAKOUT",
    "MEAN_REVERSION",
    "MOMENTUM_CONTINUATION",
    "EMA_CANDLE_PULLBACK",
    "CANDLE_REVERSAL",
    "BOLLINGER_MEAN_REVERSION",
    "SUPPORT_CANDLE_REVERSAL",
    "FALSE_BREAKOUT_REVERSAL",
    "STOCHASTIC_RANGE",
}

LONG_ONLY_BEARISH_REGIMES = {
    "STRONG_DOWNTREND",
    "WEAK_DOWNTREND",
    "HIGH_VOLATILITY_DOWNTREND",
}


class OpenAIServiceError(RuntimeError):
    """Safe OpenAI API error suitable for logs and the paper dashboard."""


def _redact_openai_error_text(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", text)
    return text[:600]


def _raise_for_openai_status(response: httpx.Response, key_source: str) -> None:
    """Raise a precise, redacted error instead of httpx's generic 401 message."""

    if response.is_success:
        return

    error_code = "unknown"
    error_type = "unknown"
    error_message = "No error details were returned by OpenAI."
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            error_code = str(error.get("code") or error.get("type") or "unknown")
            error_type = str(error.get("type") or "unknown")
            error_message = _redact_openai_error_text(error.get("message")) or error_message
    except (ValueError, TypeError):
        body = _redact_openai_error_text(response.text)
        if body:
            error_message = body

    if response.status_code == 401:
        if error_code == "ip_not_authorized" or error_type == "ip_not_authorized":
            guidance = (
                "The current public IP is not authorized for the OpenAI organization. "
                "Update the OpenAI IP allowlist or use an authorized network."
            )
        else:
            guidance = (
                "The configured OPENAI_API_KEY was rejected. Update the project .env or "
                "deployment variable and retry the adaptive research."
            )
        raise OpenAIServiceError(
            "OpenAI authentication failed "
            f"(HTTP 401, code={error_code}, source={key_source}). "
            f"{guidance}"
        )

    if response.status_code == 429:
        raise OpenAIServiceError(
            "OpenAI rate limit or quota check failed "
            f"(HTTP 429, code={error_code}, source={key_source}). "
            f"Detail: {error_message}"
        )

    raise OpenAIServiceError(
        "OpenAI request failed "
        f"(HTTP {response.status_code}, code={error_code}, source={key_source}). "
        f"Detail: {error_message}"
    )


def _post_openai_response(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    """Call the Responses API with a bounded retry for transient timeouts."""

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    timeout = httpx.Timeout(
        connect=min(15.0, settings.adaptive_research_openai_timeout_seconds),
        read=settings.adaptive_research_openai_timeout_seconds,
        write=30.0,
        pool=15.0,
    )
    attempts = max(1, settings.adaptive_research_openai_attempts)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    headers=headers,
                    json=payload,
                )
            _raise_for_openai_status(response, settings.openai_api_key_source)
            return response.json()
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(min(2.0, 0.5 * (attempt + 1)))
                continue
            break
    raise OpenAIServiceError(
        "OpenAI pattern research timed out after "
        f"{attempts} attempt(s) and {settings.adaptive_research_openai_timeout_seconds:.0f}s "
        "per attempt. Local time-series analysis and backtests remain available."
    ) from last_error


@dataclass(frozen=True, slots=True)
class StrategySpecification:
    code: str
    name: str
    family: str
    origin: str
    rationale: str
    allowed_regimes: tuple[str, ...]
    fast_ema: int = 9
    slow_ema: int = 20
    regime_ema: int = 200
    rsi_min: float = 35.0
    rsi_max: float = 70.0
    adx_min: float = 18.0
    relative_volume_min: float = 1.0
    pullback_atr: float = 0.35
    breakout_lookback: int = 20
    breakout_atr: float = 0.35
    stop_atr: float = 1.8
    target_atr: float = 2.8
    trailing_atr: float = 1.4
    exit_rsi: float = 76.0
    max_holding_candles: int = 24
    required_patterns: tuple[str, ...] = field(default_factory=tuple)
    pattern_lookback: int = 3
    bollinger_zscore_entry: float = -1.8
    bollinger_zscore_exit: float = 0.0
    stochastic_entry: float = 25.0
    stochastic_exit: float = 75.0
    range_lookback: int = 24
    range_edge_atr: float = 0.45
    false_breakout_atr: float = 0.20
    max_range_adx: float = 21.0
    min_range_score: float = 55.0
    source_urls: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        payload = asdict(self)
        payload["allowed_regimes"] = list(self.allowed_regimes)
        payload["required_patterns"] = list(self.required_patterns)
        payload["source_urls"] = list(self.source_urls)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | None) -> StrategySpecification | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
            payload["allowed_regimes"] = tuple(payload.get("allowed_regimes") or ())
            payload["required_patterns"] = tuple(payload.get("required_patterns") or ())
            payload["source_urls"] = tuple(payload.get("source_urls") or ())
            return cls(**payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None


@dataclass(frozen=True, slots=True)
class StrategyValidationMetrics:
    score: float
    net_return: float
    max_drawdown_pct: float
    profit_factor: float | None
    trade_count: int
    win_rate: float | None
    expectancy_r: float
    average_win_r: float | None
    average_loss_r: float | None
    stability: float
    fold_returns: tuple[float, ...]
    positive_fold_count: int
    required_positive_folds: int
    hard_failures: tuple[str, ...]
    soft_warnings: tuple[str, ...]
    eligible: bool
    metrics_available: bool = True
    raw_candle_count: int = 0
    clean_candle_count: int = 0
    required_candle_count: int = 0


@dataclass(frozen=True, slots=True)
class StrategyResearchOutcome:
    specification: StrategySpecification | None
    regime: str
    metrics: StrategyValidationMetrics | None
    research_status: str
    research_summary: str
    candidate_scores_json: str
    source_urls_json: str
    next_research_at: datetime
    error_message: str | None = None
    ai_provider: str = "LOCAL"
    ai_model: str | None = None
    ai_review_status: str = "NOT_USED"
    ai_review_score: float | None = None
    ai_review_summary: str | None = None


@dataclass(frozen=True, slots=True)
class AIStrategyReview:
    selected_code: str | None
    suitability_score: float | None
    summary: str
    status: str


class MarketRegimeAnalyzer:
    @staticmethod
    def detect(current_row: pd.Series, trend_row: pd.Series) -> str:
        close = float(current_row["close"])
        ema20 = float(current_row["ema_20"])
        ema50 = float(current_row["ema_50"])
        ema200 = float(current_row["ema_200"])
        adx = float(current_row["adx_14"])
        volatility = float(current_row.get("volatility_20", 0.0) or 0.0)
        atr_pct = float(current_row.get("atr_pct", 0.0) or 0.0)
        return_6 = float(current_row.get("return_6", 0.0) or 0.0)
        relative_volume = float(current_row.get("relative_volume", 0.0) or 0.0)
        trend_close = float(trend_row["close"])
        trend_ema50 = float(trend_row["ema_50"])
        trend_ema200 = float(trend_row["ema_200"])

        bullish_structure = close > ema20 > ema50 > ema200 and trend_close > trend_ema50
        bearish_structure = close < ema20 < ema50 and trend_close < trend_ema50
        range_score = float(current_row.get("range_bound_score", 0.0) or 0.0)

        if volatility >= 0.025 or atr_pct >= 0.035:
            if bullish_structure and adx >= 22:
                return "HIGH_VOLATILITY_UPTREND"
            if bearish_structure and adx >= 22:
                return "HIGH_VOLATILITY_DOWNTREND"
            return "HIGH_VOLATILITY"
        if bullish_structure and adx >= 25:
            return "STRONG_UPTREND"
        if bearish_structure and adx >= 25:
            return "STRONG_DOWNTREND"
        if range_score >= 60 and adx < 23:
            return "SIDEWAYS"
        if bullish_structure or (close > ema50 and trend_close > trend_ema200):
            return "WEAK_UPTREND"
        if bearish_structure or (close < ema50 and trend_close < trend_ema200):
            return "WEAK_DOWNTREND"
        if adx < 16 and abs(close - ema50) / max(close, 1e-12) < 0.012:
            return "SIDEWAYS"
        if adx >= 20 and relative_volume >= 1.25 and abs(return_6) >= 0.012:
            return "BREAKOUT_EXPANSION"
        if adx < 20 and abs(close - ema20) / max(close, 1e-12) >= 0.015:
            return "MEAN_REVERSION"
        return "TRANSITION"


class StrategyTemplateLibrary:
    """Creates executable research hypotheses that are not limited to dashboard strategies."""

    @staticmethod
    def _code(name: str, family: str, parameters: dict[str, Any]) -> str:
        raw = json.dumps([name, family, parameters], sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10].upper()
        return f"GEN_{family[:16]}_{digest}"[:64]

    def candidates(
        self,
        regime: str,
        pattern_summary: TimeSeriesPatternSummary | None = None,
    ) -> list[StrategySpecification]:
        """Return a controlled candidate matrix instead of one hypothesis per family.

        TRANSITION deliberately evaluates all five families with three calibrated variants
        each. Other regimes receive only the families that can reasonably operate there.
        The periods are intentionally bounded to avoid an unconstrained parameter search.
        """
        common_up = (
            "STRONG_UPTREND",
            "WEAK_UPTREND",
            "HIGH_VOLATILITY_UPTREND",
            "BREAKOUT_EXPANSION",
        )
        breakout_regimes = (
            "BREAKOUT_EXPANSION",
            "HIGH_VOLATILITY",
            "HIGH_VOLATILITY_UPTREND",
        )
        mean_reversion_regimes = ("SIDEWAYS", "MEAN_REVERSION")
        specs: list[StrategySpecification] = []

        def add(
            name: str,
            family: str,
            rationale: str,
            regimes: Iterable[str],
            **params: Any,
        ) -> None:
            base = {
                "fast_ema": 9,
                "slow_ema": 20,
                "regime_ema": 200,
                "rsi_min": 35.0,
                "rsi_max": 70.0,
                "adx_min": 18.0,
                "relative_volume_min": 1.0,
                "pullback_atr": 0.35,
                "breakout_lookback": 20,
                "breakout_atr": 0.35,
                "stop_atr": 1.8,
                "target_atr": 2.8,
                "trailing_atr": 1.4,
                "exit_rsi": 76.0,
                "max_holding_candles": 24,
                "required_patterns": (),
                "pattern_lookback": 3,
                "bollinger_zscore_entry": -1.8,
                "bollinger_zscore_exit": 0.0,
                "stochastic_entry": 25.0,
                "stochastic_exit": 75.0,
                "range_lookback": 24,
                "range_edge_atr": 0.45,
                "false_breakout_atr": 0.20,
                "max_range_adx": 21.0,
                "min_range_score": 55.0,
            }
            base.update(params)
            allowed = tuple(dict.fromkeys((*regimes, "TRANSITION")))
            specs.append(
                StrategySpecification(
                    code=self._code(name, family, base),
                    name=name,
                    family=family,
                    origin="SYSTEM_GENERATED",
                    rationale=rationale,
                    allowed_regimes=allowed,
                    **base,
                )
            )

        include_trend = "UPTREND" in regime or regime in {"BREAKOUT_EXPANSION", "TRANSITION"}
        include_breakout = regime in {*breakout_regimes, "TRANSITION"}
        include_mean_reversion = regime in {*mean_reversion_regimes, "TRANSITION"}

        if include_trend:
            add(
                "EMA ATR Pullback - Conservative",
                "TREND_PULLBACK",
                "A selective volatility-adjusted pullback inside a confirmed bullish structure.",
                common_up,
                fast_ema=13, slow_ema=34, rsi_min=45, rsi_max=64, adx_min=22,
                relative_volume_min=1.00, pullback_atr=0.35, stop_atr=1.6,
                target_atr=3.0, trailing_atr=1.2,
            )
            add(
                "EMA ATR Pullback - Balanced",
                "TREND_PULLBACK",
                "Balances pullback depth, trend strength and execution frequency.",
                common_up,
                fast_ema=9, slow_ema=21, rsi_min=42, rsi_max=67, adx_min=19,
                relative_volume_min=0.95, pullback_atr=0.45, stop_atr=1.7,
                target_atr=3.0, trailing_atr=1.3,
            )
            add(
                "EMA ATR Pullback - Responsive",
                "TREND_PULLBACK",
                "Accepts earlier trend resumptions while retaining ATR and exhaustion controls.",
                common_up,
                fast_ema=5, slow_ema=20, rsi_min=40, rsi_max=69, adx_min=17,
                relative_volume_min=0.90, pullback_atr=0.55, stop_atr=1.8,
                target_atr=2.8, trailing_atr=1.4,
            )

            add(
                "Momentum Continuation - Conservative",
                "MOMENTUM_CONTINUATION",
                "Requires strong EMA alignment, ADX and above-normal volume.",
                common_up,
                fast_ema=13, slow_ema=34, rsi_min=52, rsi_max=68, adx_min=25,
                relative_volume_min=1.20, stop_atr=1.8, target_atr=3.4,
            )
            add(
                "Momentum Continuation - Balanced",
                "MOMENTUM_CONTINUATION",
                "Combines directional momentum with moderate volume confirmation.",
                common_up,
                fast_ema=9, slow_ema=21, rsi_min=50, rsi_max=72, adx_min=22,
                relative_volume_min=1.10, stop_atr=1.9, target_atr=3.2,
            )
            add(
                "Momentum Continuation - Early",
                "MOMENTUM_CONTINUATION",
                "Tests earlier momentum continuation without removing cost and risk gates.",
                common_up,
                fast_ema=5, slow_ema=20, rsi_min=48, rsi_max=74, adx_min=19,
                relative_volume_min=1.00, stop_atr=1.9, target_atr=3.0,
            )
            add(
                "EMA Pullback with Bullish Candle Confirmation",
                "EMA_CANDLE_PULLBACK",
                "Combines a bullish EMA structure with a statistically meaningful reversal candle near the fast average.",
                common_up,
                fast_ema=9, slow_ema=21, rsi_min=42, rsi_max=68, adx_min=18,
                relative_volume_min=0.90, pullback_atr=0.55, stop_atr=1.7,
                target_atr=3.0, trailing_atr=1.3,
                required_patterns=("HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "BULLISH_OUTSIDE_BAR"),
                pattern_lookback=3,
            )
            add(
                "EMA 20 Retest with Candle Rejection",
                "EMA_CANDLE_PULLBACK",
                "Waits for a pullback to the trend average and requires bullish price-action rejection before entering the next candle.",
                common_up,
                fast_ema=20, slow_ema=50, rsi_min=45, rsi_max=66, adx_min=19,
                relative_volume_min=0.85, pullback_atr=0.45, stop_atr=1.6,
                target_atr=2.8, trailing_atr=1.2,
                required_patterns=("HAMMER", "BULLISH_ENGULFING", "BULLISH_OUTSIDE_BAR"),
                pattern_lookback=2,
            )

        if include_breakout:
            add(
                "Donchian Volume Breakout - Short Range",
                "DONCHIAN_BREAKOUT",
                "Tests a shorter confirmed range breakout with strict relative volume.",
                breakout_regimes,
                fast_ema=20, slow_ema=50, breakout_lookback=18, adx_min=22,
                relative_volume_min=1.25, stop_atr=1.8, target_atr=3.2, trailing_atr=1.5,
            )
            add(
                "Donchian Volume Breakout - Balanced",
                "DONCHIAN_BREAKOUT",
                "Uses a medium prior range with trend, close and volume confirmation.",
                breakout_regimes,
                fast_ema=20, slow_ema=50, breakout_lookback=24, adx_min=20,
                relative_volume_min=1.20, stop_atr=2.0, target_atr=3.6, trailing_atr=1.6,
            )
            add(
                "Donchian Volume Breakout - Long Range",
                "DONCHIAN_BREAKOUT",
                "Tests rarer long-range breakouts with wider protection and targets.",
                breakout_regimes,
                fast_ema=21, slow_ema=50, breakout_lookback=36, adx_min=21,
                relative_volume_min=1.15, stop_atr=2.2, target_atr=4.0, trailing_atr=1.7,
            )

            add(
                "ATR Expansion Breakout - Fast",
                "VOLATILITY_BREAKOUT",
                "Uses a fast ATR-normalized expansion trigger after recent compression.",
                breakout_regimes,
                breakout_lookback=8, breakout_atr=0.35, adx_min=18,
                relative_volume_min=1.20, stop_atr=1.7, target_atr=3.0,
            )
            add(
                "ATR Expansion Breakout - Balanced",
                "VOLATILITY_BREAKOUT",
                "Balances breakout confirmation, volatility expansion and trade frequency.",
                breakout_regimes,
                breakout_lookback=12, breakout_atr=0.45, adx_min=18,
                relative_volume_min=1.15, stop_atr=1.8, target_atr=3.2,
            )
            add(
                "ATR Expansion Breakout - Confirmed",
                "VOLATILITY_BREAKOUT",
                "Requires a stronger expansion threshold and longer reference window.",
                breakout_regimes,
                breakout_lookback=20, breakout_atr=0.60, adx_min=20,
                relative_volume_min=1.10, stop_atr=2.0, target_atr=3.6,
            )

        if include_mean_reversion:
            add(
                "Volatility Mean Reversion - Shallow",
                "MEAN_REVERSION",
                "Tests moderate extensions in non-trending conditions.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=25, rsi_max=40, adx_min=0,
                relative_volume_min=0.75, pullback_atr=0.65, stop_atr=1.3,
                target_atr=1.8, max_holding_candles=12,
            )
            add(
                "Volatility Mean Reversion - Balanced",
                "MEAN_REVERSION",
                "Buys statistically extended declines while avoiding strong bearish structure.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=20, rsi_max=38, adx_min=0,
                relative_volume_min=0.70, pullback_atr=0.85, stop_atr=1.4,
                target_atr=2.0, max_holding_candles=16,
            )
            add(
                "Volatility Mean Reversion - Deep",
                "MEAN_REVERSION",
                "Requires a deeper ATR extension and lower RSI before considering entry.",
                mean_reversion_regimes,
                fast_ema=21, slow_ema=50, rsi_min=16, rsi_max=34, adx_min=0,
                relative_volume_min=0.65, pullback_atr=1.05, stop_atr=1.6,
                target_atr=2.3, max_holding_candles=20,
            )
            add(
                "Support Reversal with Hammer or Bullish Engulfing",
                "CANDLE_REVERSAL",
                "Requires a bullish reversal candle after an ATR-normalized extension in a non-trending market.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=18, rsi_max=44, adx_min=0,
                relative_volume_min=0.65, pullback_atr=0.70, stop_atr=1.4,
                target_atr=2.2, max_holding_candles=12,
                required_patterns=("HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "BULLISH_OUTSIDE_BAR"),
                pattern_lookback=3,
            )
            add(
                "Inside-Bar Reversal after Volatility Extension",
                "CANDLE_REVERSAL",
                "Tests a compact reversal sequence after the price becomes extended from its mean.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=20, rsi_max=46, adx_min=0,
                relative_volume_min=0.60, pullback_atr=0.85, stop_atr=1.5,
                target_atr=2.4, max_holding_candles=16,
                required_patterns=("INSIDE_BAR", "HAMMER", "BULLISH_ENGULFING"),
                pattern_lookback=3,
            )
            add(
                "Bollinger Range Reversion - Balanced",
                "BOLLINGER_MEAN_REVERSION",
                "Buys a statistically stretched move near the lower Bollinger band only when the selected asset is classified as range-bound.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=18, rsi_max=42, adx_min=0,
                relative_volume_min=0.60, stop_atr=1.35, target_atr=1.9,
                max_holding_candles=12, bollinger_zscore_entry=-1.55,
                bollinger_zscore_exit=-0.05, max_range_adx=21,
                min_range_score=55, range_edge_atr=0.50,
            )
            add(
                "Bollinger Range Reversion - Deep",
                "BOLLINGER_MEAN_REVERSION",
                "Requires a deeper lower-band extension and stronger evidence of a stable range before entering.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=12, rsi_max=36, adx_min=0,
                relative_volume_min=0.55, stop_atr=1.50, target_atr=2.2,
                max_holding_candles=16, bollinger_zscore_entry=-1.95,
                bollinger_zscore_exit=0.0, max_range_adx=20,
                min_range_score=62, range_edge_atr=0.40,
            )
            add(
                "Support Candle Reversal in Range",
                "SUPPORT_CANDLE_REVERSAL",
                "Requires price to be near the lower edge of a validated range and a bullish rejection candle before entering the next candle.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=18, rsi_max=46, adx_min=0,
                relative_volume_min=0.60, stop_atr=1.35, target_atr=2.1,
                max_holding_candles=14, range_lookback=24, range_edge_atr=0.45,
                max_range_adx=21, min_range_score=55,
                required_patterns=("HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "BULLISH_OUTSIDE_BAR"),
                pattern_lookback=3,
            )
            add(
                "False Support Breakout Reversal",
                "FALSE_BREAKOUT_REVERSAL",
                "Looks for a brief break below historical support followed by a close back inside the same range.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=14, rsi_max=48, adx_min=0,
                relative_volume_min=0.70, stop_atr=1.30, target_atr=2.3,
                max_holding_candles=12, range_lookback=30, range_edge_atr=0.35,
                false_breakout_atr=0.25, max_range_adx=22, min_range_score=52,
                required_patterns=("HAMMER", "BULLISH_ENGULFING", "BULLISH_OUTSIDE_BAR"),
                pattern_lookback=2,
            )
            add(
                "Stochastic Range Rotation",
                "STOCHASTIC_RANGE",
                "Uses an oversold stochastic crossover near the lower half of a confirmed price range.",
                mean_reversion_regimes,
                fast_ema=20, slow_ema=50, rsi_min=18, rsi_max=50, adx_min=0,
                relative_volume_min=0.55, stop_atr=1.35, target_atr=1.9,
                max_holding_candles=10, stochastic_entry=28,
                stochastic_exit=76, max_range_adx=21, min_range_score=55,
                range_lookback=24, range_edge_atr=0.55,
            )

        if pattern_summary is not None and pattern_summary.recommended_families:
            priority = {family: index for index, family in enumerate(pattern_summary.recommended_families)}
            specs.sort(key=lambda item: (priority.get(item.family, 999), item.name))

        # The simulator is Spot and long-only. A bearish regime must not be represented
        # by a synthetic bullish candidate because that makes the dashboard look as if a
        # meaningful strategy comparison occurred. Returning an empty collection lets the
        # research engine report that it is deliberately waiting for market recovery.
        return specs


class WebStrategyResearcher:
    """Optional OpenAI hypothesis generation for the selected asset only."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.adaptive_research_web_enabled
            and self.settings.openai_api_key
        )

    def research(
        self,
        market: str,
        regime: str,
        execution_timeframe: str,
        trend_timeframe: str,
        pattern_summary: TimeSeriesPatternSummary | None = None,
    ) -> tuple[list[StrategySpecification], str, tuple[str, ...]]:
        if not self.enabled:
            reason = (
                "OpenAI hypothesis generation is disabled or OPENAI_API_KEY is not configured; "
                "the selector used local time-series pattern analysis and its internal strategy library."
            )
            return [], reason, ()

        pattern_payload = json.dumps(
            pattern_summary.to_dict() if pattern_summary is not None else {
                "status": "NOT_PROVIDED",
                "market": market,
                "execution_timeframe": execution_timeframe,
                "trend_timeframe": trend_timeframe,
            },
            separators=(",", ":"),
        )
        prompt = f"""
You are a quantitative strategy hypothesis assistant for PAPER-ONLY Spot crypto trading.
Analyze ONLY the selected market below. Never inspect, rank, mention or suggest another market.
Do not browse the web. The local backend has already compared the current movement with
historical windows from this same asset. Use that statistical summary plus technical analysis
knowledge (moving averages, trend, momentum, volatility, volume, support/resistance and
candlestick patterns such as hammer, shooting star, engulfing, doji, morning/evening star,
inside/outside bars) to propose executable long-only hypotheses for the next configured candle.

market={market}
execution_timeframe={execution_timeframe}
trend_timeframe={trend_timeframe}
current_regime={regime}
selected_asset_pattern_summary={pattern_payload}

Return ONLY valid JSON with this exact shape:
{{
  "summary": "short explanation tied only to the selected asset",
  "strategies": [
    {{
      "name": "strategy name",
      "family": "TREND_PULLBACK|DONCHIAN_BREAKOUT|VOLATILITY_BREAKOUT|MEAN_REVERSION|MOMENTUM_CONTINUATION|EMA_CANDLE_PULLBACK|CANDLE_REVERSAL|BOLLINGER_MEAN_REVERSION|SUPPORT_CANDLE_REVERSAL|FALSE_BREAKOUT_REVERSAL|STOCHASTIC_RANGE",
      "rationale": "why this hypothesis matches the current and historical pattern",
      "parameters": {{
        "fast_ema": 9,
        "slow_ema": 20,
        "regime_ema": 200,
        "rsi_min": 40,
        "rsi_max": 70,
        "adx_min": 18,
        "relative_volume_min": 1.0,
        "pullback_atr": 0.4,
        "breakout_lookback": 20,
        "breakout_atr": 0.4,
        "stop_atr": 1.8,
        "target_atr": 2.8,
        "trailing_atr": 1.4,
        "exit_rsi": 76,
        "max_holding_candles": 24,
        "bollinger_zscore_entry": -1.8,
        "bollinger_zscore_exit": 0.0,
        "stochastic_entry": 25,
        "stochastic_exit": 75,
        "range_lookback": 24,
        "range_edge_atr": 0.45,
        "false_breakout_atr": 0.2,
        "max_range_adx": 21,
        "min_range_score": 55
      }}
    }}
  ]
}}

Provide at most three distinct hypotheses. Do not provide investment advice or a direct buy
instruction. Every hypothesis will be backtested chronologically with costs and risk gates.
""".strip()

        payload = {
            "model": self.settings.adaptive_research_openai_model,
            "input": prompt,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "adaptive_strategy_research",
                    "strict": True,
                    "schema": self._research_schema(),
                }
            },
        }
        data = _post_openai_response(self.settings, payload)

        text = self._extract_output_text(data)
        urls: tuple[str, ...] = ()
        parsed = self._parse_json(text)
        summary = str(parsed.get("summary") or "Selected-asset AI hypothesis generation completed.")
        rows = parsed.get("strategies") or []
        specs: list[StrategySpecification] = []
        for row in rows[:3]:
            spec = self._build_spec(row, regime, urls)
            if spec is not None:
                specs.append(spec)
        return specs, summary, urls

    @staticmethod
    def _research_schema() -> dict[str, Any]:
        parameter_properties = {
            "fast_ema": {"type": "integer"},
            "slow_ema": {"type": "integer"},
            "regime_ema": {"type": "integer"},
            "rsi_min": {"type": "number"},
            "rsi_max": {"type": "number"},
            "adx_min": {"type": "number"},
            "relative_volume_min": {"type": "number"},
            "pullback_atr": {"type": "number"},
            "breakout_lookback": {"type": "integer"},
            "breakout_atr": {"type": "number"},
            "stop_atr": {"type": "number"},
            "target_atr": {"type": "number"},
            "trailing_atr": {"type": "number"},
            "exit_rsi": {"type": "number"},
            "max_holding_candles": {"type": "integer"},
            "bollinger_zscore_entry": {"type": "number"},
            "bollinger_zscore_exit": {"type": "number"},
            "stochastic_entry": {"type": "number"},
            "stochastic_exit": {"type": "number"},
            "range_lookback": {"type": "integer"},
            "range_edge_atr": {"type": "number"},
            "false_breakout_atr": {"type": "number"},
            "max_range_adx": {"type": "number"},
            "min_range_score": {"type": "number"},
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary", "strategies"],
            "properties": {
                "summary": {"type": "string"},
                "strategies": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "family", "rationale", "parameters"],
                        "properties": {
                            "name": {"type": "string"},
                            "family": {"type": "string", "enum": sorted(ALLOWED_FAMILIES)},
                            "rationale": {"type": "string"},
                            "parameters": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": list(parameter_properties),
                                "properties": parameter_properties,
                            },
                        },
                    },
                },
            },
        }

    @staticmethod
    def _extract_output_text(data: dict[str, Any]) -> str:
        direct = data.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        parts: list[str] = []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for content in item.get("content") or []:
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_source_urls(data: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for item in data.get("output") or []:
            for content in item.get("content") or []:
                for annotation in content.get("annotations") or []:
                    url = annotation.get("url")
                    if isinstance(url, str) and url.startswith(("http://", "https://")):
                        urls.append(url)
            if item.get("type") == "web_search_call":
                for source in (item.get("action") or {}).get("sources") or []:
                    url = source.get("url")
                    if isinstance(url, str):
                        urls.append(url)
        return urls

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("The OpenAI hypothesis response did not contain a JSON object.")
        return json.loads(cleaned[start : end + 1])

    def _build_spec(
        self,
        row: dict[str, Any],
        regime: str,
        urls: tuple[str, ...],
    ) -> StrategySpecification | None:
        family = str(row.get("family") or "").strip().upper()
        if family not in ALLOWED_FAMILIES:
            return None
        name = str(row.get("name") or family.replace("_", " ").title()).strip()[:100]
        rationale = str(row.get("rationale") or "AI-generated strategy hypothesis for the selected asset.").strip()[:600]
        p = row.get("parameters") if isinstance(row.get("parameters"), dict) else {}

        def number(key: str, default: float, low: float, high: float) -> float:
            try:
                return min(max(float(p.get(key, default)), low), high)
            except (TypeError, ValueError):
                return default

        def integer(key: str, default: int, low: int, high: int) -> int:
            return int(round(number(key, default, low, high)))

        supported_emas = (5, 9, 13, 20, 21, 34, 50, 200)

        def supported_ema(key: str, default: int) -> int:
            requested = integer(key, default, 5, 200)
            return min(supported_emas, key=lambda value: abs(value - requested))

        parameters = {
            "fast_ema": supported_ema("fast_ema", 9),
            "slow_ema": supported_ema("slow_ema", 20),
            "regime_ema": supported_ema("regime_ema", 200),
            "rsi_min": number("rsi_min", 40, 10, 70),
            "rsi_max": number("rsi_max", 70, 30, 90),
            "adx_min": number("adx_min", 18, 0, 50),
            "relative_volume_min": number("relative_volume_min", 1.0, 0.5, 3.0),
            "pullback_atr": number("pullback_atr", 0.4, 0.1, 2.0),
            "breakout_lookback": integer("breakout_lookback", 20, 5, 100),
            "breakout_atr": number("breakout_atr", 0.4, 0.05, 2.0),
            "stop_atr": number("stop_atr", 1.8, 0.5, 5.0),
            "target_atr": number("target_atr", 2.8, 0.8, 10.0),
            "trailing_atr": number("trailing_atr", 1.4, 0.5, 5.0),
            "exit_rsi": number("exit_rsi", 76, 50, 95),
            "max_holding_candles": integer("max_holding_candles", 24, 4, 96),
            "bollinger_zscore_entry": number("bollinger_zscore_entry", -1.8, -3.5, -0.5),
            "bollinger_zscore_exit": number("bollinger_zscore_exit", 0.0, -0.5, 1.5),
            "stochastic_entry": number("stochastic_entry", 25, 5, 45),
            "stochastic_exit": number("stochastic_exit", 75, 55, 95),
            "range_lookback": integer("range_lookback", 24, 12, 96),
            "range_edge_atr": number("range_edge_atr", 0.45, 0.1, 1.5),
            "false_breakout_atr": number("false_breakout_atr", 0.2, 0.05, 1.0),
            "max_range_adx": number("max_range_adx", 21, 10, 30),
            "min_range_score": number("min_range_score", 55, 35, 85),
        }
        if parameters["fast_ema"] >= parameters["slow_ema"]:
            parameters["slow_ema"] = min(100, parameters["fast_ema"] + 10)
        code = StrategyTemplateLibrary._code(name, family, parameters)
        pattern_defaults: tuple[str, ...] = ()
        if family == "EMA_CANDLE_PULLBACK":
            pattern_defaults = ("HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "BULLISH_OUTSIDE_BAR")
        elif family in {"CANDLE_REVERSAL", "SUPPORT_CANDLE_REVERSAL"}:
            pattern_defaults = ("HAMMER", "BULLISH_ENGULFING", "MORNING_STAR", "INSIDE_BAR")
        elif family == "FALSE_BREAKOUT_REVERSAL":
            pattern_defaults = ("HAMMER", "BULLISH_ENGULFING", "BULLISH_OUTSIDE_BAR")
        return StrategySpecification(
            code=code,
            name=name,
            family=family,
            origin="AI_GENERATED",
            rationale=rationale,
            allowed_regimes=(regime, "TRANSITION"),
            required_patterns=pattern_defaults,
            pattern_lookback=3,
            source_urls=urls,
            **parameters,
        )


class OpenAIStrategyReviewer:
    """Uses OpenAI only to compare locally eligible strategies; it cannot bypass risk gates."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.adaptive_research_ai_review_enabled
            and self.settings.openai_api_key
        )

    def review(
        self,
        market: str,
        regime: str,
        eligible: list[tuple[StrategySpecification, StrategyValidationMetrics]],
    ) -> AIStrategyReview:
        if not self.enabled or not eligible:
            return AIStrategyReview(None, None, "OpenAI review was not used.", "NOT_USED")

        rows = [
            {
                "code": spec.code,
                "name": spec.name,
                "family": spec.family,
                "origin": spec.origin,
                "rationale": spec.rationale,
                "validation_score": round(metrics.score, 4),
                "net_return": round(metrics.net_return, 8),
                "max_drawdown_pct": round(metrics.max_drawdown_pct, 8),
                "profit_factor": metrics.profit_factor,
                "trade_count": metrics.trade_count,
                "stability": round(metrics.stability, 6),
                "expectancy_r": round(metrics.expectancy_r, 6),
                "average_win_r": (
                    round(metrics.average_win_r, 6)
                    if metrics.average_win_r is not None
                    else None
                ),
                "average_loss_r": (
                    round(metrics.average_loss_r, 6)
                    if metrics.average_loss_r is not None
                    else None
                ),
            }
            for spec, metrics in eligible
        ]
        codes = [row["code"] for row in rows]
        prompt = (
            "You are a quantitative research reviewer. The backend has already applied "
            "walk-forward, cost, drawdown, stability and minimum-trade gates. Review only "
            "the eligible candidates below for PAPER-ONLY trading. Select one candidate "
            "that best fits the current regime. Never select a code outside this list and "
            "do not provide a buy/sell instruction.\n"
            f"market={market}\nregime={regime}\ncandidates={json.dumps(rows, separators=(',', ':'))}"
        )
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["selected_code", "suitability_score", "summary"],
            "properties": {
                "selected_code": {"type": "string", "enum": codes},
                "suitability_score": {"type": "number", "minimum": 0, "maximum": 100},
                "summary": {"type": "string"},
            },
        }
        payload = {
            "model": self.settings.adaptive_research_openai_review_model,
            "input": prompt,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "adaptive_strategy_review",
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        data = _post_openai_response(self.settings, payload)
        parsed = WebStrategyResearcher._parse_json(
            WebStrategyResearcher._extract_output_text(data)
        )
        selected_code = str(parsed.get("selected_code") or "")
        if selected_code not in codes:
            raise ValueError("OpenAI review selected an unknown or ineligible strategy code.")
        score = min(max(float(parsed.get("suitability_score", 0.0)), 0.0), 100.0)
        summary = str(parsed.get("summary") or "OpenAI reviewed locally eligible candidates.")[:1000]
        return AIStrategyReview(selected_code, score, summary, "COMPLETED")


class GeneratedStrategyExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _ema(row: pd.Series, period: int) -> float:
        key = f"ema_{period}"
        if key in row and pd.notna(row[key]):
            return float(row[key])
        return float("nan")

    @staticmethod
    def _number(row: pd.Series, key: str, default: float = float("nan")) -> float:
        try:
            value = float(row.get(key, default))
        except (TypeError, ValueError):
            return default
        return value

    def _range_context(
        self,
        spec: StrategySpecification,
        frame: pd.DataFrame,
        index: int,
    ) -> dict[str, float | bool]:
        row = frame.iloc[index]
        close = float(row["close"])
        atr = max(float(row["atr_14"]), 1e-12)
        lookback = max(12, min(spec.range_lookback, index))
        historical = frame.iloc[max(0, index - lookback) : index]
        if historical.empty:
            support = self._number(row, "range_support_24", close)
            resistance = self._number(row, "range_resistance_24", close)
        else:
            support = float(historical["low"].astype(float).min())
            resistance = float(historical["high"].astype(float).max())
        width = max(resistance - support, atr)
        position = self._number(row, "range_position_24")
        if not np.isfinite(position):
            position = (close - support) / width
        score = self._number(row, "range_bound_score", 0.0)
        adx = float(row["adx_14"])
        return {
            "support": support,
            "resistance": resistance,
            "midpoint": support + width / 2.0,
            "position": position,
            "score": score,
            "range_ready": bool(score >= spec.min_range_score and adx <= spec.max_range_adx),
            "near_support": bool(close - support <= atr * spec.range_edge_atr),
        }

    def entry_signal(
        self,
        spec: StrategySpecification,
        frame: pd.DataFrame,
        index: int,
        regime: str,
    ) -> tuple[bool, str]:
        if index <= 0:
            return False, "insufficient_history"
        row = frame.iloc[index]
        previous = frame.iloc[index - 1]
        close = float(row["close"])
        atr = float(row["atr_14"])
        fast = self._ema(row, spec.fast_ema)
        slow = self._ema(row, spec.slow_ema)
        regime_ema = self._ema(row, spec.regime_ema)
        rsi = float(row["rsi_14"])
        adx = float(row["adx_14"])
        relative_volume = float(row["relative_volume"])
        if not all(np.isfinite([close, atr, fast, slow, regime_ema, rsi, adx, relative_volume])):
            return False, "incomplete_indicators"
        if regime not in spec.allowed_regimes and "TRANSITION" not in spec.allowed_regimes:
            return False, "regime_not_allowed"
        if not (spec.rsi_min <= rsi <= spec.rsi_max):
            return False, "rsi_filter"
        if adx < spec.adx_min or relative_volume < spec.relative_volume_min:
            return False, "strength_or_volume_filter"

        body_atr = abs(close - float(row["open"])) / max(atr, 1e-12)
        bullish_close = close > float(row["open"]) and body_atr >= self.settings.entry_min_body_atr
        family = spec.family
        if family == "TREND_PULLBACK":
            touch_low = slow - atr * spec.pullback_atr
            touch_high = fast + atr * spec.pullback_atr
            touched = float(row["low"]) <= touch_high and float(row["high"]) >= touch_low
            recovered = close > fast and float(previous["close"]) <= close and bullish_close
            not_extended = close - fast <= atr * min(self.settings.entry_max_extension_atr, 0.90)
            approved = close > regime_ema and fast > slow and touched and recovered and not_extended
            return approved, "trend_pullback" if approved else "trend_pullback_not_ready"

        if family == "DONCHIAN_BREAKOUT":
            start = max(0, index - spec.breakout_lookback)
            previous_high = float(frame.iloc[start:index]["high"].max())
            approved = (
                close > previous_high + atr * self.settings.breakout_close_buffer_atr
                and close > regime_ema
                and fast >= slow
                and bullish_close
                and close - previous_high <= atr * self.settings.entry_max_extension_atr
            )
            return approved, "donchian_breakout" if approved else "donchian_breakout_not_ready"

        if family == "VOLATILITY_BREAKOUT":
            start = max(0, index - spec.breakout_lookback)
            reference_open = float(frame.iloc[start:index]["open"].iloc[-1])
            recent_range = float(
                (frame.iloc[start:index]["high"] - frame.iloc[start:index]["low"]).mean()
            )
            trigger = reference_open + max(recent_range * 0.5, atr * spec.breakout_atr)
            approved = (
                close > trigger + atr * self.settings.breakout_close_buffer_atr
                and close > regime_ema
                and fast >= slow
                and bullish_close
                and close - trigger <= atr * self.settings.entry_max_extension_atr
            )
            return approved, "atr_expansion_breakout" if approved else "breakout_trigger_not_reached"

        if family == "MEAN_REVERSION":
            extension = (fast - close) / max(atr, 1e-12)
            not_structurally_bearish = close > regime_ema * 0.97 or slow > regime_ema
            approved = (
                extension >= spec.pullback_atr
                and not_structurally_bearish
                and close > float(previous["close"])
                and bullish_close
            )
            return approved, "mean_reversion_extension" if approved else "mean_reversion_not_extended"

        if family == "BOLLINGER_MEAN_REVERSION":
            context = self._range_context(spec, frame, index)
            lower = self._number(row, "bollinger_lower_20")
            zscore = self._number(row, "bollinger_zscore_20")
            oversold = (
                (np.isfinite(lower) and close <= lower + atr * 0.15)
                or (np.isfinite(zscore) and zscore <= spec.bollinger_zscore_entry)
            )
            recent_patterns = set(
                CandlestickPatternDetector.patterns_in_window(
                    frame.iloc[max(0, index - 2) : index + 1]
                )
            )
            reversal_confirmation = bullish_close or bool(recent_patterns & BULLISH_CANDLE_PATTERNS)
            approved = (
                bool(context["range_ready"])
                and oversold
                and float(context["position"]) <= 0.40
                and reversal_confirmation
                and close >= float(previous["close"])
                and regime not in LONG_ONLY_BEARISH_REGIMES
            )
            return approved, (
                "bollinger_range_reversion_confirmed"
                if approved
                else "bollinger_range_reversion_not_ready"
            )

        if family == "SUPPORT_CANDLE_REVERSAL":
            context = self._range_context(spec, frame, index)
            recent_start = max(0, index - max(spec.pattern_lookback, 1) + 1)
            recent_patterns = set(
                CandlestickPatternDetector.patterns_in_window(
                    frame.iloc[recent_start : index + 1]
                )
            )
            required_patterns = set(spec.required_patterns)
            pattern_confirmed = bool(recent_patterns & required_patterns)
            approved = (
                bool(context["range_ready"])
                and bool(context["near_support"])
                and float(context["position"]) <= 0.35
                and pattern_confirmed
                and close >= float(previous["close"])
                and regime not in LONG_ONLY_BEARISH_REGIMES
            )
            return approved, (
                "range_support_candle_reversal_confirmed"
                if approved
                else "range_support_reversal_not_confirmed"
            )

        if family == "FALSE_BREAKOUT_REVERSAL":
            context = self._range_context(spec, frame, index)
            support = float(context["support"])
            broke_support = float(row["low"]) < support - atr * spec.false_breakout_atr
            reclaimed_support = close > support
            penetration = (support - float(row["low"])) / atr
            not_uncontrolled_break = penetration <= max(1.2, spec.false_breakout_atr * 4.0)
            recent_start = max(0, index - max(spec.pattern_lookback, 1) + 1)
            recent_patterns = set(
                CandlestickPatternDetector.patterns_in_window(
                    frame.iloc[recent_start : index + 1]
                )
            )
            pattern_confirmed = bool(recent_patterns & set(spec.required_patterns)) or bullish_close
            approved = (
                bool(context["range_ready"])
                and broke_support
                and reclaimed_support
                and not_uncontrolled_break
                and pattern_confirmed
                and regime not in LONG_ONLY_BEARISH_REGIMES
            )
            return approved, (
                "false_support_breakout_reclaimed"
                if approved
                else "false_breakout_reversal_not_confirmed"
            )

        if family == "STOCHASTIC_RANGE":
            context = self._range_context(spec, frame, index)
            stochastic_k = self._number(row, "stochastic_k_14")
            stochastic_d = self._number(row, "stochastic_d_3")
            previous_k = self._number(previous, "stochastic_k_14")
            previous_d = self._number(previous, "stochastic_d_3")
            crossed_up = (
                np.isfinite(stochastic_k)
                and np.isfinite(stochastic_d)
                and np.isfinite(previous_k)
                and np.isfinite(previous_d)
                and previous_k <= previous_d
                and stochastic_k > stochastic_d
            )
            oversold = min(stochastic_k, previous_k) <= spec.stochastic_entry
            approved = (
                bool(context["range_ready"])
                and float(context["position"]) <= 0.45
                and crossed_up
                and oversold
                and bullish_close
                and regime not in LONG_ONLY_BEARISH_REGIMES
            )
            return approved, (
                "stochastic_range_rotation_confirmed"
                if approved
                else "stochastic_range_rotation_not_ready"
            )

        if family == "MOMENTUM_CONTINUATION":
            momentum = float(row.get("return_3", 0.0) or 0.0)
            approved = (
                close > regime_ema
                and fast > slow
                and momentum > 0.002
                and bullish_close
                and close - fast <= atr * self.settings.entry_max_extension_atr
            )
            return approved, "momentum_continuation" if approved else "momentum_not_confirmed"

        recent_start = max(0, index - max(spec.pattern_lookback, 1) + 1)
        recent_patterns = set(
            CandlestickPatternDetector.patterns_in_window(
                frame.iloc[recent_start : index + 1]
            )
        )
        required_patterns = set(spec.required_patterns)
        pattern_confirmed = bool(recent_patterns & required_patterns) if required_patterns else bool(
            recent_patterns & BULLISH_CANDLE_PATTERNS
        )

        if family == "EMA_CANDLE_PULLBACK":
            touched_fast = float(row["low"]) <= fast + atr * spec.pullback_atr
            trend_ready = close > regime_ema and fast > slow
            not_extended = close - fast <= atr * min(self.settings.entry_max_extension_atr, 0.90)
            approved = trend_ready and touched_fast and pattern_confirmed and not_extended
            return approved, (
                "ema_pullback_bullish_candle_confirmed"
                if approved
                else "ema_pullback_candle_confirmation_missing"
            )

        if family == "CANDLE_REVERSAL":
            extension = (fast - close) / max(atr, 1e-12)
            support_start = max(0, index - max(spec.breakout_lookback, 12))
            previous_support_window = frame.iloc[support_start:index]
            previous_support = (
                float(previous_support_window["low"].astype(float).min())
                if not previous_support_window.empty
                else close
            )
            near_support = close - previous_support <= atr * max(1.2, spec.pullback_atr * 2.0)
            statistically_extended = extension >= spec.pullback_atr * 0.50
            not_strong_downtrend = regime not in LONG_ONLY_BEARISH_REGIMES
            approved = (
                not_strong_downtrend
                and (near_support or statistically_extended)
                and pattern_confirmed
                and close >= float(previous["close"])
            )
            return approved, (
                "support_or_mean_reversal_candle_confirmed"
                if approved
                else "candle_reversal_not_confirmed"
            )

        return False, "unsupported_family"

    def exit_signal(
        self,
        spec: StrategySpecification,
        frame: pd.DataFrame,
        index: int,
        regime: str,
    ) -> tuple[bool, str]:
        row = frame.iloc[index]
        close = float(row["close"])
        fast = self._ema(row, spec.fast_ema)
        slow = self._ema(row, spec.slow_ema)
        rsi = float(row["rsi_14"])
        if rsi >= spec.exit_rsi:
            return True, "exit_rsi_reached"
        if spec.family in {"TREND_PULLBACK", "MOMENTUM_CONTINUATION"} and close < slow:
            return True, "trend_structure_lost"
        if spec.family in {"DONCHIAN_BREAKOUT", "VOLATILITY_BREAKOUT"} and close < fast:
            return True, "breakout_momentum_lost"
        if spec.family == "MEAN_REVERSION" and close >= fast:
            return True, "mean_reversion_target_reached"
        if spec.family in {
            "BOLLINGER_MEAN_REVERSION",
            "SUPPORT_CANDLE_REVERSAL",
            "FALSE_BREAKOUT_REVERSAL",
            "STOCHASTIC_RANGE",
        }:
            context = self._range_context(spec, frame, index)
            zscore = self._number(row, "bollinger_zscore_20")
            stochastic_k = self._number(row, "stochastic_k_14")
            if spec.family == "BOLLINGER_MEAN_REVERSION" and (
                close >= float(context["midpoint"])
                or (np.isfinite(zscore) and zscore >= spec.bollinger_zscore_exit)
            ):
                return True, "bollinger_midline_reached"
            if spec.family == "STOCHASTIC_RANGE" and (
                close >= float(context["midpoint"])
                or (np.isfinite(stochastic_k) and stochastic_k >= spec.stochastic_exit)
            ):
                return True, "stochastic_range_target_reached"
            if spec.family in {"SUPPORT_CANDLE_REVERSAL", "FALSE_BREAKOUT_REVERSAL"}:
                recent = set(
                    CandlestickPatternDetector.patterns_in_window(
                        frame.iloc[max(0, index - 2) : index + 1]
                    )
                )
                if close >= float(context["midpoint"]):
                    return True, "range_midpoint_reached"
                if float(context["position"]) >= 0.78 and recent & BEARISH_CANDLE_PATTERNS:
                    return True, "range_resistance_rejection_detected"
            if not bool(context["range_ready"]) and close < float(context["midpoint"]):
                return True, "range_regime_lost"
        if spec.family in {"EMA_CANDLE_PULLBACK", "CANDLE_REVERSAL"}:
            recent = set(
                CandlestickPatternDetector.patterns_in_window(
                    frame.iloc[max(0, index - 2) : index + 1]
                )
            )
            if recent & BEARISH_CANDLE_PATTERNS:
                return True, "bearish_candle_reversal_detected"
            if spec.family == "EMA_CANDLE_PULLBACK" and close < slow:
                return True, "ema_candle_trend_structure_lost"
            if spec.family == "CANDLE_REVERSAL" and close >= fast:
                return True, "candle_reversal_mean_reached"
        if regime in {"STRONG_DOWNTREND", "HIGH_VOLATILITY_DOWNTREND"}:
            return True, "bearish_regime_detected"
        return False, "position_maintained"

    def live_decision(
        self,
        spec: StrategySpecification,
        account: Any,
        frame: pd.DataFrame,
        current_index: int,
        regime: str,
    ) -> dict[str, Any]:
        row = frame.iloc[current_index]
        close = float(row["close"])
        atr = float(row["atr_14"])
        if account.has_open_position:
            should_exit, reason = self.exit_signal(spec, frame, current_index, regime)
            return {"signal": "SELL" if should_exit else "HOLD", "reason": reason}
        should_enter, reason = self.entry_signal(spec, frame, current_index, regime)
        stop = close - atr * spec.stop_atr
        target = close + atr * spec.target_atr
        risk = max(close - stop, 1e-12)
        return {
            "signal": "BUY" if should_enter else "HOLD",
            "reason": reason,
            "execution_reference_price": close,
            "stop_loss": stop,
            "take_profit": target,
            "reward_risk_ratio": (target - close) / risk,
            "potential_gross_return": (target / close - 1) if close > 0 else 0.0,
        }


class StrategyBacktestEngine:
    BASE_REQUIRED_COLUMNS = (
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "atr_14",
        "rsi_14",
        "adx_14",
        "relative_volume",
        "ema_20",
        "ema_50",
        "ema_200",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.executor = GeneratedStrategyExecutor(settings)

    def history_diagnostics(self, frame: pd.DataFrame) -> dict[str, int | bool]:
        """Describe the usable history before any candidate or OpenAI call runs.

        Indicator warm-up rows are intentionally excluded from ``clean_candles``. This
        prevents a raw 800-candle request from being mistaken for 800 usable candles.
        """

        raw_candles = int(len(frame))
        if frame.empty or any(column not in frame.columns for column in self.BASE_REQUIRED_COLUMNS):
            clean_candles = 0
        else:
            clean_candles = int(
                len(
                    frame.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"], keep="last")
                    .dropna(subset=list(self.BASE_REQUIRED_COLUMNS))
                    .tail(self.settings.adaptive_research_max_history_candles)
                )
            )
        required = int(self.settings.adaptive_research_min_candles)
        return {
            "raw_candles": raw_candles,
            "clean_candles": clean_candles,
            "required_clean_candles": required,
            "indicator_warmup_rows": max(raw_candles - clean_candles, 0),
            "sufficient": clean_candles >= required,
        }

    def _prepare_frame(self, frame: pd.DataFrame, spec: StrategySpecification) -> pd.DataFrame:
        range_columns = {
            "bollinger_mid_20",
            "bollinger_upper_20",
            "bollinger_lower_20",
            "bollinger_zscore_20",
            "stochastic_k_14",
            "stochastic_d_3",
            "range_support_24",
            "range_resistance_24",
            "range_position_24",
            "range_bound_score",
        }
        if range_columns.difference(frame.columns) and {
            "timestamp", "open", "high", "low", "close", "volume"
        }.issubset(frame.columns):
            frame = add_indicators(frame)
        required = list(StrategyBacktestEngine.BASE_REQUIRED_COLUMNS)
        for period in {spec.fast_ema, spec.slow_ema, spec.regime_ema}:
            key = f"ema_{period}"
            if key not in frame.columns:
                frame = frame.copy()
                frame[key] = frame["close"].astype(float).ewm(
                    span=period, adjust=False, min_periods=period
                ).mean()
            required.append(key)
        if spec.family in {
            "BOLLINGER_MEAN_REVERSION",
            "SUPPORT_CANDLE_REVERSAL",
            "FALSE_BREAKOUT_REVERSAL",
            "STOCHASTIC_RANGE",
        }:
            required.extend(sorted(range_columns))
        return (
            frame.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .dropna(subset=list(dict.fromkeys(required)))
            .tail(self.settings.adaptive_research_max_history_candles)
            .reset_index(drop=True)
        )

    def _run(
        self,
        frame: pd.DataFrame,
        costs: ExecutionCosts,
        trade_start_index: int,
    ) -> dict[str, Any]:
        cash = 1.0
        quantity = 0.0
        entry_price = 0.0
        stop = 0.0
        target = 0.0
        trailing = 0.0
        entry_index = 0
        peak = 1.0
        max_drawdown = 0.0
        trade_returns: list[float] = []
        trade_r_multiples: list[float] = []
        entry_risk_rate = 0.0
        entry_cost = costs.taker_fee_rate + costs.half_spread_rate + costs.slippage_rate
        exit_cost = entry_cost

        for index in range(max(1, trade_start_index), len(frame)):
            row = frame.iloc[index]
            current_regime = self._row_regime(row)
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            atr = float(row["atr_14"])

            if quantity > 0:
                trailing = max(trailing, high - atr * 1.4)
                exit_price: float | None = None
                if low <= max(stop, trailing):
                    exit_price = max(stop, trailing)
                elif high >= target:
                    exit_price = target
                else:
                    should_exit, _ = self.executor.exit_signal(
                        self._active_spec, frame, index, current_regime
                    )
                    if should_exit or index - entry_index >= self._active_spec.max_holding_candles:
                        exit_price = close
                if exit_price is not None:
                    proceeds = quantity * exit_price * (1 - exit_cost)
                    trade_return = proceeds / max(entry_price * quantity, 1e-12) - 1
                    trade_returns.append(trade_return)
                    trade_r_multiples.append(
                        trade_return / max(entry_risk_rate, 1e-12)
                    )
                    cash = proceeds
                    quantity = 0.0

            if quantity == 0:
                should_enter, _ = self.executor.entry_signal(
                    self._active_spec, frame, index, current_regime
                )
                if should_enter:
                    execution = close * (1 + costs.half_spread_rate + costs.slippage_rate)
                    spendable = cash * (1 - costs.taker_fee_rate)
                    quantity = spendable / max(execution, 1e-12)
                    entry_price = execution
                    entry_index = index
                    stop = close - atr * self._active_spec.stop_atr
                    entry_risk_rate = max(close - stop, 1e-12) / max(close, 1e-12)
                    target = close + atr * self._active_spec.target_atr
                    trailing = close - atr * self._active_spec.trailing_atr
                    cash = 0.0

            equity = cash if quantity == 0 else quantity * close
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1 - equity / max(peak, 1e-12))

        if quantity > 0:
            final_close = float(frame.iloc[-1]["close"])
            proceeds = quantity * final_close * (1 - exit_cost)
            trade_return = proceeds / max(entry_price * quantity, 1e-12) - 1
            trade_returns.append(trade_return)
            trade_r_multiples.append(trade_return / max(entry_risk_rate, 1e-12))
            cash = proceeds

        gains = sum(value for value in trade_returns if value > 0)
        losses = abs(sum(value for value in trade_returns if value < 0))
        winning_r = [value for value in trade_r_multiples if value > 0]
        losing_r = [value for value in trade_r_multiples if value < 0]
        return {
            "net_return": cash - 1,
            "max_drawdown_pct": max_drawdown,
            "trade_count": len(trade_returns),
            "wins": sum(1 for value in trade_returns if value > 0),
            "gross_profit": gains,
            "gross_loss": losses,
            "r_sum": sum(trade_r_multiples),
            "r_count": len(trade_r_multiples),
            "winning_r_sum": sum(winning_r),
            "winning_r_count": len(winning_r),
            "losing_r_sum": sum(losing_r),
            "losing_r_count": len(losing_r),
        }

    def run_with_spec(
        self,
        spec: StrategySpecification,
        frame: pd.DataFrame,
        costs: ExecutionCosts,
        trade_start_index: int = 0,
    ) -> dict[str, Any]:
        self._active_spec = spec
        prepared = self._prepare_frame(frame, spec)
        return self._run(prepared, costs, trade_start_index)

    def _score(
        self,
        expectancy_r: float,
        max_drawdown: float,
        profit_factor: float | None,
        trade_count: int,
        stability: float,
        regime_fit: float = 1.0,
    ) -> float:
        expectancy_score = min(max((expectancy_r + 0.20) / 1.20, 0.0), 1.0)
        stability_score = min(max(stability, 0.0), 1.0)
        profit_factor_score = min(max((profit_factor or 0.0) / 3.0, 0.0), 1.0)
        drawdown_score = 1.0 - min(
            max(max_drawdown / max(self.settings.adaptive_research_max_drawdown_pct, 1e-12), 0.0),
            1.0,
        )
        sample_size_score = min(
            trade_count / max(self.settings.adaptive_research_min_trades, 1),
            1.0,
        )
        regime_fit_score = min(max(regime_fit, 0.0), 1.0)

        weighted = (
            self.settings.selector_expectancy_weight * expectancy_score
            + self.settings.selector_stability_weight * stability_score
            + self.settings.selector_profit_factor_weight * profit_factor_score
            + self.settings.selector_drawdown_weight * drawdown_score
            + self.settings.selector_sample_size_weight * sample_size_score
            + self.settings.selector_regime_fit_weight * regime_fit_score
        )
        return round(min(max(weighted * 100.0, 0.0), 100.0), 2)

    @staticmethod
    def _row_regime(row: pd.Series) -> str:
        close = float(row["close"])
        ema20 = float(row["ema_20"])
        ema50 = float(row["ema_50"])
        ema200 = float(row["ema_200"])
        adx = float(row["adx_14"])
        volatility = float(row.get("volatility_20", 0.0) or 0.0)
        range_score = float(row.get("range_bound_score", 0.0) or 0.0)
        if volatility >= 0.025:
            return "HIGH_VOLATILITY_UPTREND" if close > ema50 else "HIGH_VOLATILITY"
        if range_score >= 60 and adx < 23:
            return "SIDEWAYS"
        if close > ema20 > ema50 > ema200 and adx >= 25:
            return "STRONG_UPTREND"
        if close > ema50 and close > ema200:
            return "WEAK_UPTREND"
        if close < ema20 < ema50 and adx >= 25:
            return "STRONG_DOWNTREND"
        if close < ema50:
            return "WEAK_DOWNTREND"
        if adx < 16:
            return "SIDEWAYS"
        return "TRANSITION"

    def validate(
        self,
        spec: StrategySpecification,
        frame: pd.DataFrame,
        costs: ExecutionCosts,
    ) -> StrategyValidationMetrics:
        self._active_spec = spec
        return self._validate_active(frame, costs)

    def _validate_active(self, frame: pd.DataFrame, costs: ExecutionCosts) -> StrategyValidationMetrics:
        spec = self._active_spec
        raw_candle_count = int(len(frame))
        clean = self._prepare_frame(frame, spec)
        if len(clean) < self.settings.adaptive_research_min_candles:
            return StrategyValidationMetrics(
                score=0.0,
                net_return=0.0,
                max_drawdown_pct=0.0,
                profit_factor=None,
                trade_count=0,
                win_rate=None,
                expectancy_r=0.0,
                average_win_r=None,
                average_loss_r=None,
                stability=0.0,
                fold_returns=(),
                positive_fold_count=0,
                required_positive_folds=1,
                hard_failures=("INSUFFICIENT_HISTORY",),
                soft_warnings=(),
                eligible=False,
                metrics_available=False,
                raw_candle_count=raw_candle_count,
                clean_candle_count=len(clean),
                required_candle_count=self.settings.adaptive_research_min_candles,
            )

        validation_rows = min(
            self.settings.adaptive_research_validation_rows,
            max(120, len(clean) // 4),
        )
        fold_count = min(
            self.settings.adaptive_research_walk_forward_folds,
            max(1, len(clean) // validation_rows),
        )
        fold_returns: list[float] = []
        fold_metrics: list[dict[str, Any]] = []
        for fold in range(fold_count):
            end = len(clean) - (fold_count - fold - 1) * validation_rows
            start = max(0, end - validation_rows)
            prefix_start = max(0, start - max(spec.breakout_lookback, 200))
            window = clean.iloc[prefix_start:end].reset_index(drop=True)
            metrics = self._run(window, costs, trade_start_index=start - prefix_start)
            fold_returns.append(float(metrics["net_return"]))
            fold_metrics.append(metrics)

        full = self._run(
            clean,
            costs,
            trade_start_index=max(0, len(clean) - 3 * validation_rows),
        )
        positive_folds = sum(1 for value in fold_returns if value > 0)
        required_positive_folds = max(1, math.ceil(len(fold_returns) * 2 / 3))
        stability = positive_folds / max(len(fold_returns), 1)
        net_return = float(np.mean(fold_returns)) if fold_returns else float(full["net_return"])
        max_drawdown = max(
            [float(item["max_drawdown_pct"]) for item in fold_metrics]
            or [float(full["max_drawdown_pct"])]
        )
        total_profit = sum(float(item["gross_profit"]) for item in fold_metrics)
        total_loss = sum(float(item["gross_loss"]) for item in fold_metrics)
        profit_factor = total_profit / total_loss if total_loss > 1e-12 else None
        trade_count = sum(int(item["trade_count"]) for item in fold_metrics)
        wins = sum(int(item["wins"]) for item in fold_metrics)
        win_rate = wins / trade_count if trade_count else None
        total_r = sum(float(item["r_sum"]) for item in fold_metrics)
        total_r_count = sum(int(item["r_count"]) for item in fold_metrics)
        expectancy_r = total_r / total_r_count if total_r_count else 0.0
        winning_r_sum = sum(float(item["winning_r_sum"]) for item in fold_metrics)
        winning_r_count = sum(int(item["winning_r_count"]) for item in fold_metrics)
        losing_r_sum = sum(float(item["losing_r_sum"]) for item in fold_metrics)
        losing_r_count = sum(int(item["losing_r_count"]) for item in fold_metrics)
        average_win_r = winning_r_sum / winning_r_count if winning_r_count else None
        average_loss_r = losing_r_sum / losing_r_count if losing_r_count else None
        score = self._score(
            expectancy_r, max_drawdown, profit_factor, trade_count, stability
        )

        hard_min_trades = min(
            self.settings.adaptive_research_min_trades,
            self.settings.adaptive_research_hard_min_trades,
        )
        hard_failures: list[str] = []
        if trade_count < hard_min_trades:
            hard_failures.append("INSUFFICIENT_VALIDATED_TRADES")
        if expectancy_r <= 0:
            hard_failures.append("NON_POSITIVE_EXPECTANCY")
        if net_return <= 0:
            hard_failures.append("NON_POSITIVE_NET_RETURN")
        if max_drawdown > self.settings.adaptive_research_max_drawdown_pct:
            hard_failures.append("MAX_DRAWDOWN_EXCEEDED")
        if positive_folds < required_positive_folds:
            hard_failures.append("INSUFFICIENT_POSITIVE_FOLDS")

        soft_warnings: list[str] = []
        if trade_count < self.settings.adaptive_research_min_trades:
            soft_warnings.append("BELOW_IDEAL_TRADE_COUNT")
        if (profit_factor or 0.0) < self.settings.adaptive_research_min_profit_factor:
            soft_warnings.append("BELOW_IDEAL_PROFIT_FACTOR")
        if stability < self.settings.adaptive_research_min_stability:
            soft_warnings.append("BELOW_IDEAL_STABILITY")
        if score < self.settings.adaptive_research_min_validation_score:
            soft_warnings.append("BELOW_IDEAL_VALIDATION_SCORE")

        return StrategyValidationMetrics(
            score=score,
            net_return=net_return,
            max_drawdown_pct=max_drawdown,
            profit_factor=profit_factor,
            trade_count=trade_count,
            win_rate=win_rate,
            expectancy_r=expectancy_r,
            average_win_r=average_win_r,
            average_loss_r=average_loss_r,
            stability=stability,
            fold_returns=tuple(fold_returns),
            positive_fold_count=positive_folds,
            required_positive_folds=required_positive_folds,
            hard_failures=tuple(hard_failures),
            soft_warnings=tuple(soft_warnings),
            eligible=not hard_failures,
            metrics_available=True,
            raw_candle_count=raw_candle_count,
            clean_candle_count=len(clean),
            required_candle_count=self.settings.adaptive_research_min_candles,
        )



class AdaptiveStrategyResearchEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.templates = StrategyTemplateLibrary()
        self.web = WebStrategyResearcher(settings)
        self.reviewer = OpenAIStrategyReviewer(settings)
        self.backtest = StrategyBacktestEngine(settings)
        self.pattern_analyzer = TimeSeriesPatternAnalyzer()
        self.executor = GeneratedStrategyExecutor(settings)

    @staticmethod
    def _public_error(exc: Exception) -> str:
        """Return a concise error that is safe to expose in the paper dashboard."""

        message = str(exc).strip() or "No additional error details were returned."
        if isinstance(exc, httpx.HTTPStatusError):
            response_text = exc.response.text.strip()
            if response_text:
                message = f"{message} | response={response_text[:400]}"
        message = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", message, flags=re.IGNORECASE)
        message = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", message)
        if isinstance(exc, OpenAIServiceError):
            return message[:600]
        return f"{type(exc).__name__}: {message}"[:600]

    @staticmethod
    def _base_research_details(
        regime: str,
        history: dict[str, int | bool],
        *,
        web_status: str,
    ) -> dict[str, Any]:
        return {
            "schema_version": 5,
            "regime": regime,
            "regime_display_key": (
                "MARKET_IN_DEFINITION" if regime == "TRANSITION" else regime
            ),
            "history": history,
            "long_only": True,
            "analyzed_market_count": 1,
            "pattern_analysis": None,
            "generated_count": 0,
            "tested_count": 0,
            "approved_count": 0,
            "web_research_status": web_status,
            "web_research_error": None,
            "best_candidate": None,
            "rejection_summary": [],
            "candidates": [],
        }

    def research(
        self,
        market: str,
        regime: str,
        execution_timeframe: str,
        trend_timeframe: str,
        frame: pd.DataFrame,
        costs: ExecutionCosts,
        now: datetime,
    ) -> StrategyResearchOutcome:
        next_research_at = now + timedelta(hours=self.settings.adaptive_research_interval_hours)
        retry_minutes = (
            self.settings.adaptive_research_transition_retry_minutes
            if regime == "TRANSITION"
            else self.settings.adaptive_research_retry_minutes
        )
        retry_at = now + timedelta(minutes=retry_minutes)

        # Do not spend an OpenAI request or display fake backtest metrics before the
        # minimum number of indicator-complete candles exists.
        history = self.backtest.history_diagnostics(frame)
        history["target_history_candles"] = int(self.settings.adaptive_research_target_candles)
        history["max_history_candles"] = int(self.settings.adaptive_research_max_history_candles)
        history["target_progress_pct"] = round(
            min(100.0, float(history["clean_candles"]) * 100.0 / max(self.settings.adaptive_research_target_candles, 1)),
            2,
        )
        research_attempted_at = now.astimezone(timezone.utc).isoformat()
        if not bool(history["sufficient"]):
            details = self._base_research_details(
                regime,
                history,
                web_status="SKIPPED_INSUFFICIENT_HISTORY",
            )
            details["research_attempted_at"] = research_attempted_at
            details["rejection_summary"] = [
                {"code": "INSUFFICIENT_HISTORY", "count": 1}
            ]
            return StrategyResearchOutcome(
                specification=None,
                regime=regime,
                metrics=None,
                research_status="WAITING_FOR_HISTORY",
                research_summary="INSUFFICIENT_HISTORY_PENDING",
                candidate_scores_json=json.dumps(details, separators=(",", ":")),
                source_urls_json="[]",
                next_research_at=now + timedelta(minutes=min(5, retry_minutes)),
                error_message=None,
                ai_provider="LOCAL",
                ai_review_status="NOT_USED",
            )

        pattern_summary = self.pattern_analyzer.analyze(
            market=market,
            execution_timeframe=execution_timeframe,
            trend_timeframe=trend_timeframe,
            frame=frame,
            pattern_window_candles=self.settings.adaptive_pattern_window_candles,
            horizon_candles=self.settings.adaptive_pattern_horizon_candles,
            neighbor_count=self.settings.adaptive_pattern_neighbors,
            max_history_candles=self.settings.adaptive_research_max_history_candles,
            estimated_round_trip_cost=costs.estimated_round_trip_rate,
        )

        if regime in LONG_ONLY_BEARISH_REGIMES:
            details = self._base_research_details(
                regime,
                history,
                web_status="SKIPPED_BEARISH_REGIME",
            )
            details.update(
                {
                    "research_attempted_at": research_attempted_at,
                    "market": market,
                    "execution_timeframe": execution_timeframe,
                    "trend_timeframe": trend_timeframe,
                    "pattern_analysis": pattern_summary.to_dict(),
                    "market_action": "WAIT_FOR_RECOVERY",
                }
            )
            return StrategyResearchOutcome(
                specification=None,
                regime=regime,
                metrics=None,
                research_status="WAITING_FOR_MARKET_RECOVERY",
                research_summary="NO_LONG_STRATEGY_FOR_BEARISH_REGIME",
                candidate_scores_json=json.dumps(details, separators=(",", ":")),
                source_urls_json="[]",
                next_research_at=retry_at,
                error_message=None,
                ai_provider="LOCAL",
                ai_review_status="NOT_USED",
            )

        internal = self.templates.candidates(regime, pattern_summary)
        web_candidates: list[StrategySpecification] = []
        source_urls: tuple[str, ...] = ()
        web_error: str | None = None
        review_error: str | None = None
        web_status = "DISABLED"
        try:
            web_candidates, _web_summary, source_urls = self.web.research(
                market,
                regime,
                execution_timeframe,
                trend_timeframe,
                pattern_summary,
            )
            web_status = "COMPLETED" if self.web.enabled else "DISABLED"
        except Exception as exc:  # research failure must not stop paper trading
            web_error = self._public_error(exc)
            web_status = "ERROR"
            logger.warning("Adaptive web research failed for %s: %s", market, web_error)

        candidates = [*web_candidates, *internal]
        candidates_to_test = candidates[: self.settings.adaptive_research_max_candidates]
        scored_rows: list[dict[str, Any]] = []
        validated: list[tuple[StrategySpecification, StrategyValidationMetrics]] = []
        rejection_counts: dict[str, int] = {}

        for spec in candidates_to_test:
            metrics = self.backtest.validate(spec, frame, costs)
            for failure in metrics.hard_failures:
                rejection_counts[failure] = rejection_counts.get(failure, 0) + 1

            if metrics.metrics_available:
                display = {
                    "score": f"{metrics.score:.1f}/100",
                    "net_return": f"{metrics.net_return * 100:+.2f}%",
                    "max_drawdown": f"-{abs(metrics.max_drawdown_pct) * 100:.2f}%",
                    "profit_factor": (
                        f"{metrics.profit_factor:.2f}"
                        if metrics.profit_factor is not None
                        else "—"
                    ),
                    "trade_count": str(metrics.trade_count),
                    "expectancy_r": f"{metrics.expectancy_r:+.3f}R",
                    "stability": f"{metrics.stability * 100:.0f}%",
                    "positive_folds": (
                        f"{metrics.positive_fold_count}/{metrics.required_positive_folds}"
                    ),
                }
            else:
                display = {
                    "score": "—",
                    "net_return": "—",
                    "max_drawdown": "—",
                    "profit_factor": "—",
                    "trade_count": "—",
                    "expectancy_r": "—",
                    "stability": "—",
                    "positive_folds": "—",
                }

            row = {
                "code": spec.code,
                "name": spec.name,
                "family": spec.family,
                "origin": spec.origin,
                "rationale": spec.rationale,
                "required_patterns": list(spec.required_patterns),
                "pattern_lookback": spec.pattern_lookback,
                "metrics_available": metrics.metrics_available,
                "score": metrics.score if metrics.metrics_available else None,
                "net_return": (
                    round(metrics.net_return, 8) if metrics.metrics_available else None
                ),
                "max_drawdown_pct": (
                    round(metrics.max_drawdown_pct, 8)
                    if metrics.metrics_available
                    else None
                ),
                "profit_factor": (
                    round(metrics.profit_factor, 6)
                    if metrics.metrics_available and metrics.profit_factor is not None
                    else None
                ),
                "trade_count": metrics.trade_count if metrics.metrics_available else None,
                "win_rate": (
                    round(metrics.win_rate, 6)
                    if metrics.metrics_available and metrics.win_rate is not None
                    else None
                ),
                "stability": (
                    round(metrics.stability, 6) if metrics.metrics_available else None
                ),
                "expectancy_r": (
                    round(metrics.expectancy_r, 6) if metrics.metrics_available else None
                ),
                "positive_fold_count": (
                    metrics.positive_fold_count if metrics.metrics_available else None
                ),
                "required_positive_folds": (
                    metrics.required_positive_folds if metrics.metrics_available else None
                ),
                "raw_candle_count": metrics.raw_candle_count,
                "clean_candle_count": metrics.clean_candle_count,
                "required_candle_count": metrics.required_candle_count,
                "hard_failures": list(metrics.hard_failures),
                "soft_warnings": list(metrics.soft_warnings),
                "eligible": metrics.eligible,
                "display": display,
            }
            scored_rows.append(row)
            if metrics.eligible:
                validated.append((spec, metrics))

        scored_rows.sort(
            key=lambda item: float(item["score"] if item["score"] is not None else -1.0),
            reverse=True,
        )
        best_candidate = scored_rows[0] if scored_rows else None
        research_details = self._base_research_details(
            regime,
            history,
            web_status=web_status,
        )
        research_details.update(
            {
                "research_attempted_at": research_attempted_at,
                "market": market,
                "execution_timeframe": execution_timeframe,
                "trend_timeframe": trend_timeframe,
                "pattern_analysis": pattern_summary.to_dict(),
                "ai_hypothesis_status": web_status,
                "ai_hypothesis_error": web_error,
                "generated_count": len(candidates),
                "tested_count": len(scored_rows),
                "approved_count": len(validated),
                "web_research_error": web_error,
                "best_candidate": best_candidate,
                "rejection_summary": [
                    {"code": code, "count": count}
                    for code, count in sorted(
                        rejection_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ],
                "candidates": scored_rows,
            }
        )

        if not validated:
            return StrategyResearchOutcome(
                specification=None,
                regime=regime,
                metrics=None,
                research_status="WAITING_FOR_VALID_STRATEGY",
                research_summary="NO_CANDIDATE_PASSED_HARD_GATES",
                candidate_scores_json=json.dumps(
                    research_details, separators=(",", ":")
                ),
                source_urls_json=json.dumps(source_urls, separators=(",", ":")),
                next_research_at=retry_at,
                error_message=web_error,
                ai_provider="OPENAI" if self.web.enabled else "LOCAL",
                ai_model=(
                    self.settings.adaptive_research_openai_model
                    if self.web.enabled
                    else None
                ),
                ai_review_status="NOT_USED",
            )

        validated.sort(key=lambda item: item[1].score, reverse=True)
        winner, metrics = validated[0]
        review = AIStrategyReview(
            None, None, "LOCAL_VALIDATION_SELECTED_WINNER", "NOT_USED"
        )
        try:
            review = self.reviewer.review(market, regime, validated)
            if review.selected_code:
                winner, metrics = next(
                    item for item in validated if item[0].code == review.selected_code
                )
        except Exception as exc:  # AI review is advisory and cannot stop local selection
            review_error = self._public_error(exc)
            review = AIStrategyReview(
                None,
                None,
                "OPENAI_REVIEW_FAILED_LOCAL_SCORE_USED",
                "ERROR",
            )
            logger.warning("OpenAI strategy review failed for %s: %s", market, review_error)

        combined_errors = "; ".join(
            value for value in (web_error, review_error) if value
        ) or None
        research_details["ai_review_status"] = review.status
        research_details["ai_review_error"] = review_error

        return StrategyResearchOutcome(
            specification=winner,
            regime=regime,
            metrics=metrics,
            research_status="CHALLENGER_SELECTED",
            research_summary="VALIDATED_CANDIDATE_SELECTED",
            candidate_scores_json=json.dumps(
                research_details, separators=(",", ":")
            ),
            source_urls_json=json.dumps(
                winner.source_urls or source_urls, separators=(",", ":")
            ),
            next_research_at=next_research_at,
            error_message=combined_errors,
            ai_provider="OPENAI" if (self.web.enabled or self.reviewer.enabled) else "LOCAL",
            ai_model=(
                self.settings.adaptive_research_openai_review_model
                if review.status == "COMPLETED"
                else (
                    self.settings.adaptive_research_openai_model
                    if self.web.enabled
                    else None
                )
            ),
            ai_review_status=review.status,
            ai_review_score=review.suitability_score,
            ai_review_summary=review.summary,
        )

