from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import re
from typing import Any, Iterable

import httpx
import numpy as np
import pandas as pd

from .config import Settings
from .execution_costs import ExecutionCosts

logger = logging.getLogger(__name__)

ALLOWED_FAMILIES = {
    "TREND_PULLBACK",
    "DONCHIAN_BREAKOUT",
    "VOLATILITY_BREAKOUT",
    "MEAN_REVERSION",
    "MOMENTUM_CONTINUATION",
}


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
    source_urls: tuple[str, ...] = field(default_factory=tuple)

    def to_json(self) -> str:
        payload = asdict(self)
        payload["allowed_regimes"] = list(self.allowed_regimes)
        payload["source_urls"] = list(self.source_urls)
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | None) -> StrategySpecification | None:
        if not value:
            return None
        try:
            payload = json.loads(value)
            payload["allowed_regimes"] = tuple(payload.get("allowed_regimes") or ())
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
    stability: float
    fold_returns: tuple[float, ...]
    eligible: bool


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

        if volatility >= 0.025 or atr_pct >= 0.035:
            if bullish_structure and adx >= 22:
                return "HIGH_VOLATILITY_UPTREND"
            if bearish_structure and adx >= 22:
                return "HIGH_VOLATILITY_DOWNTREND"
            return "HIGH_VOLATILITY"
        if bullish_structure and adx >= 25:
            return "STRONG_UPTREND"
        if bullish_structure or (close > ema50 and trend_close > trend_ema200):
            return "WEAK_UPTREND"
        if bearish_structure and adx >= 25:
            return "STRONG_DOWNTREND"
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

    def candidates(self, regime: str) -> list[StrategySpecification]:
        common_up = (
            "STRONG_UPTREND",
            "WEAK_UPTREND",
            "HIGH_VOLATILITY_UPTREND",
            "BREAKOUT_EXPANSION",
            "TRANSITION",
        )
        specs: list[StrategySpecification] = []

        def add(name: str, family: str, rationale: str, regimes: Iterable[str], **params: Any) -> None:
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
            }
            base.update(params)
            code = self._code(name, family, base)
            specs.append(
                StrategySpecification(
                    code=code,
                    name=name,
                    family=family,
                    origin="SYSTEM_GENERATED",
                    rationale=rationale,
                    allowed_regimes=tuple(regimes),
                    **base,
                )
            )

        if "UPTREND" in regime or regime in {"BREAKOUT_EXPANSION", "TRANSITION"}:
            add(
                "Adaptive EMA ATR Pullback",
                "TREND_PULLBACK",
                "Buys a volatility-adjusted pullback inside a confirmed bullish structure.",
                common_up,
                fast_ema=9,
                slow_ema=21,
                rsi_min=42,
                rsi_max=66,
                adx_min=19,
                relative_volume_min=0.95,
                pullback_atr=0.45,
                stop_atr=1.7,
                target_atr=3.0,
                trailing_atr=1.3,
            )
            add(
                "Trend Continuation with Volume",
                "MOMENTUM_CONTINUATION",
                "Requires aligned EMAs, directional momentum and above-normal volume.",
                common_up,
                fast_ema=13,
                slow_ema=34,
                rsi_min=50,
                rsi_max=72,
                adx_min=22,
                relative_volume_min=1.10,
                stop_atr=1.9,
                target_atr=3.2,
            )

        if regime in {"BREAKOUT_EXPANSION", "HIGH_VOLATILITY", "HIGH_VOLATILITY_UPTREND", "TRANSITION"}:
            add(
                "Donchian Volume Breakout",
                "DONCHIAN_BREAKOUT",
                "Enters only after price closes above a prior range with trend and volume confirmation.",
                ("BREAKOUT_EXPANSION", "HIGH_VOLATILITY", "HIGH_VOLATILITY_UPTREND", "TRANSITION"),
                fast_ema=20,
                slow_ema=50,
                breakout_lookback=24,
                adx_min=20,
                relative_volume_min=1.20,
                stop_atr=2.0,
                target_atr=3.6,
                trailing_atr=1.6,
            )
            add(
                "ATR Expansion Breakout",
                "VOLATILITY_BREAKOUT",
                "Uses an ATR-normalized expansion trigger so the threshold adapts to current volatility.",
                ("BREAKOUT_EXPANSION", "HIGH_VOLATILITY", "HIGH_VOLATILITY_UPTREND", "TRANSITION"),
                breakout_lookback=12,
                breakout_atr=0.45,
                adx_min=18,
                relative_volume_min=1.15,
                stop_atr=1.8,
                target_atr=3.2,
            )

        if regime in {"SIDEWAYS", "MEAN_REVERSION", "TRANSITION"}:
            add(
                "Volatility-Adjusted Mean Reversion",
                "MEAN_REVERSION",
                "Buys statistically extended declines only when the broader market structure is not strongly bearish.",
                ("SIDEWAYS", "MEAN_REVERSION", "TRANSITION"),
                fast_ema=20,
                slow_ema=50,
                rsi_min=20,
                rsi_max=38,
                adx_min=0,
                relative_volume_min=0.70,
                pullback_atr=0.85,
                stop_atr=1.4,
                target_atr=2.0,
                max_holding_candles=16,
            )

        if not specs:
            add(
                "Defensive Trend Re-entry",
                "TREND_PULLBACK",
                "Uses strict filters and waits for a bullish structure before considering a long entry.",
                ("TRANSITION", "WEAK_UPTREND", "STRONG_UPTREND"),
                rsi_min=45,
                rsi_max=62,
                adx_min=22,
                relative_volume_min=1.10,
                pullback_atr=0.30,
                stop_atr=1.6,
                target_atr=2.8,
            )

        return specs


class WebStrategyResearcher:
    """Optional server-side research using the OpenAI Responses API web search tool."""

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
    ) -> tuple[list[StrategySpecification], str, tuple[str, ...]]:
        if not self.enabled:
            reason = (
                "Web research is disabled or OPENAI_API_KEY is not configured; "
                "the selector used its internal strategy research library."
            )
            return [], reason, ()

        prompt = f"""
You are a quantitative strategy research assistant for PAPER-ONLY crypto trading.
Research reputable public material on systematic long-only entry methods suitable for:
market={market}, execution timeframe={execution_timeframe}, trend timeframe={trend_timeframe},
current regime={regime}.

Return ONLY valid JSON with this exact shape:
{{
  "summary": "short research summary",
  "strategies": [
    {{
      "name": "strategy name",
      "family": "TREND_PULLBACK|DONCHIAN_BREAKOUT|VOLATILITY_BREAKOUT|MEAN_REVERSION|MOMENTUM_CONTINUATION",
      "rationale": "why this hypothesis matches the regime",
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
        "max_holding_candles": 24
      }}
    }}
  ]
}}

Provide at most three distinct hypotheses. Do not give investment advice, current price targets,
or a direct buy instruction. The application will independently backtest and validate every hypothesis.
""".strip()

        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.adaptive_research_openai_model,
            "tools": [{"type": "web_search"}],
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
        with httpx.Client(timeout=self.settings.adaptive_research_web_timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        text = self._extract_output_text(data)
        urls = tuple(dict.fromkeys(self._extract_source_urls(data)))
        parsed = self._parse_json(text)
        summary = str(parsed.get("summary") or "Web research completed.")
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
            raise ValueError("The web research response did not contain a JSON object.")
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
        rationale = str(row.get("rationale") or "Web-researched strategy hypothesis.").strip()[:600]
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
        }
        if parameters["fast_ema"] >= parameters["slow_ema"]:
            parameters["slow_ema"] = min(100, parameters["fast_ema"] + 10)
        code = StrategyTemplateLibrary._code(name, family, parameters)
        return StrategySpecification(
            code=code,
            name=name,
            family=family,
            origin="WEB_RESEARCHED",
            rationale=rationale,
            allowed_regimes=(regime, "TRANSITION"),
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
        headers = {
            "Authorization": f"Bearer {self.settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.settings.adaptive_research_web_timeout_seconds) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
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
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.executor = GeneratedStrategyExecutor(settings)

    @staticmethod
    def _prepare_frame(frame: pd.DataFrame, spec: StrategySpecification) -> pd.DataFrame:
        required = [
            "timestamp", "open", "high", "low", "close", "atr_14", "rsi_14",
            "adx_14", "relative_volume", "ema_20", "ema_50", "ema_200",
        ]
        for period in {spec.fast_ema, spec.slow_ema, spec.regime_ema}:
            key = f"ema_{period}"
            if key not in frame.columns:
                frame = frame.copy()
                frame[key] = frame["close"].astype(float).ewm(
                    span=period, adjust=False, min_periods=period
                ).mean()
            required.append(key)
        return (
            frame.sort_values("timestamp")
            .dropna(subset=list(dict.fromkeys(required)))
            .tail(5000)
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
                    trade_returns.append(proceeds / max(entry_price * quantity, 1e-12) - 1)
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
                    target = close + atr * self._active_spec.target_atr
                    trailing = close - atr * self._active_spec.trailing_atr
                    cash = 0.0

            equity = cash if quantity == 0 else quantity * close
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1 - equity / max(peak, 1e-12))

        if quantity > 0:
            final_close = float(frame.iloc[-1]["close"])
            proceeds = quantity * final_close * (1 - exit_cost)
            trade_returns.append(proceeds / max(entry_price * quantity, 1e-12) - 1)
            cash = proceeds

        gains = sum(value for value in trade_returns if value > 0)
        losses = abs(sum(value for value in trade_returns if value < 0))
        return {
            "net_return": cash - 1,
            "max_drawdown_pct": max_drawdown,
            "trade_count": len(trade_returns),
            "wins": sum(1 for value in trade_returns if value > 0),
            "gross_profit": gains,
            "gross_loss": losses,
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
        net_return: float,
        max_drawdown: float,
        profit_factor: float | None,
        trade_count: int,
        stability: float,
    ) -> float:
        pf = min(profit_factor or 0.0, 3.0)
        trade_quality = min(trade_count / max(self.settings.adaptive_research_min_trades, 1), 1.5)
        raw = (
            45.0
            + net_return * 450.0
            - max_drawdown * 220.0
            + pf * 8.0
            + stability * 16.0
            + trade_quality * 8.0
        )
        return round(min(max(raw, 0.0), 100.0), 2)

    @staticmethod
    def _row_regime(row: pd.Series) -> str:
        close = float(row["close"])
        ema20 = float(row["ema_20"])
        ema50 = float(row["ema_50"])
        ema200 = float(row["ema_200"])
        adx = float(row["adx_14"])
        volatility = float(row.get("volatility_20", 0.0) or 0.0)
        if volatility >= 0.025:
            return "HIGH_VOLATILITY_UPTREND" if close > ema50 else "HIGH_VOLATILITY"
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
        clean = self._prepare_frame(frame, spec)
        if len(clean) < self.settings.adaptive_research_min_candles:
            return StrategyValidationMetrics(0, 0, 1, None, 0, None, 0, (), False)
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
        full = self._run(clean, costs, trade_start_index=max(0, len(clean) - 3 * validation_rows))
        positive_folds = sum(1 for value in fold_returns if value > 0)
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
        score = self._score(net_return, max_drawdown, profit_factor, trade_count, stability)
        eligible = all(
            [
                trade_count >= self.settings.adaptive_research_min_trades,
                net_return > 0,
                max_drawdown <= self.settings.adaptive_research_max_drawdown_pct,
                (profit_factor or 0.0) >= self.settings.adaptive_research_min_profit_factor,
                stability >= self.settings.adaptive_research_min_stability,
                score >= self.settings.adaptive_research_min_validation_score,
            ]
        )
        return StrategyValidationMetrics(
            score, net_return, max_drawdown, profit_factor, trade_count, win_rate,
            stability, tuple(fold_returns), eligible,
        )


class AdaptiveStrategyResearchEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.templates = StrategyTemplateLibrary()
        self.web = WebStrategyResearcher(settings)
        self.reviewer = OpenAIStrategyReviewer(settings)
        self.backtest = StrategyBacktestEngine(settings)
        self.executor = GeneratedStrategyExecutor(settings)

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
        retry_at = now + timedelta(minutes=self.settings.adaptive_research_retry_minutes)
        internal = self.templates.candidates(regime)
        web_candidates: list[StrategySpecification] = []
        source_urls: tuple[str, ...] = ()
        summaries: list[str] = []
        web_error: str | None = None
        try:
            web_candidates, web_summary, source_urls = self.web.research(
                market, regime, execution_timeframe, trend_timeframe
            )
            summaries.append(web_summary)
        except Exception as exc:  # research failure must not stop paper trading
            web_error = f"{type(exc).__name__}: {exc}"
            summaries.append("Web research failed; internal hypotheses were still validated.")
            logger.warning("Adaptive web research failed for %s: %s", market, web_error)

        candidates = [*web_candidates, *internal]
        scored_rows: list[dict[str, Any]] = []
        validated: list[tuple[StrategySpecification, StrategyValidationMetrics]] = []
        for spec in candidates[: self.settings.adaptive_research_max_candidates]:
            metrics = self.backtest.validate(spec, frame, costs)
            scored_rows.append(
                {
                    "code": spec.code,
                    "name": spec.name,
                    "family": spec.family,
                    "origin": spec.origin,
                    "score": metrics.score,
                    "net_return": round(metrics.net_return, 8),
                    "max_drawdown_pct": round(metrics.max_drawdown_pct, 8),
                    "profit_factor": (
                        round(metrics.profit_factor, 6) if metrics.profit_factor is not None else None
                    ),
                    "trade_count": metrics.trade_count,
                    "win_rate": round(metrics.win_rate, 6) if metrics.win_rate is not None else None,
                    "stability": round(metrics.stability, 6),
                    "eligible": metrics.eligible,
                }
            )
            if metrics.eligible:
                validated.append((spec, metrics))

        scored_rows.sort(key=lambda item: float(item["score"]), reverse=True)
        candidate_scores_json = json.dumps(scored_rows, separators=(",", ":"))
        if not validated:
            summary = (
                f"{len(candidates)} hypotheses were generated and tested, but none passed all "
                "walk-forward, cost, trade-count and drawdown requirements."
            )
            if summaries:
                summary += " " + " ".join(summaries)
            return StrategyResearchOutcome(
                specification=None,
                regime=regime,
                metrics=None,
                research_status="WAITING_FOR_VALID_STRATEGY",
                research_summary=summary,
                candidate_scores_json=candidate_scores_json,
                source_urls_json=json.dumps(source_urls, separators=(",", ":")),
                next_research_at=retry_at,
                error_message=web_error,
                ai_provider="OPENAI" if self.web.enabled else "LOCAL",
                ai_model=(self.settings.adaptive_research_openai_model if self.web.enabled else None),
                ai_review_status="NOT_USED",
            )

        validated.sort(key=lambda item: item[1].score, reverse=True)
        winner, metrics = validated[0]
        review = AIStrategyReview(None, None, "Local validation score selected the winner.", "NOT_USED")
        try:
            review = self.reviewer.review(market, regime, validated)
            if review.selected_code:
                winner, metrics = next(
                    item for item in validated if item[0].code == review.selected_code
                )
        except Exception as exc:  # AI review is advisory and cannot stop local selection
            review = AIStrategyReview(
                None, None, f"OpenAI review failed; local score selected the winner: {type(exc).__name__}: {exc}", "ERROR"
            )
            logger.warning("OpenAI strategy review failed for %s: %s", market, exc)
        summary = (
            f"Selected {winner.name} after validating {len(candidates)} generated hypotheses. "
            f"It achieved the strongest cost-adjusted walk-forward score for regime {regime}."
        )
        if summaries:
            summary += " " + " ".join(summaries)
        return StrategyResearchOutcome(
            specification=winner,
            regime=regime,
            metrics=metrics,
            research_status="ACTIVE",
            research_summary=summary,
            candidate_scores_json=candidate_scores_json,
            source_urls_json=json.dumps(winner.source_urls or source_urls, separators=(",", ":")),
            next_research_at=next_research_at,
            error_message=web_error,
            ai_provider="OPENAI" if (self.web.enabled or self.reviewer.enabled) else "LOCAL",
            ai_model=(
                self.settings.adaptive_research_openai_review_model
                if review.status == "COMPLETED"
                else (self.settings.adaptive_research_openai_model if self.web.enabled else None)
            ),
            ai_review_status=review.status,
            ai_review_score=review.suitability_score,
            ai_review_summary=review.summary,
        )
