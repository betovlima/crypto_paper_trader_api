from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import math
from typing import Any, Iterable

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
    expectancy_r: float
    average_win_r: float | None
    average_loss_r: float | None
    stability: float
    fold_returns: tuple[float, ...]
    eligible: bool
    failed_gates: tuple[str, ...] = ()
    positive_folds: int = 0
    fold_count: int = 0


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

        variants: list[StrategySpecification] = []
        for spec in specs:
            variants.append(spec)
            for suffix, adjustments in (
                ("Conservative", {"adx_min": spec.adx_min + 3, "relative_volume_min": spec.relative_volume_min + 0.10, "stop_atr": max(0.8, spec.stop_atr - 0.15)}),
                ("Responsive", {"adx_min": max(0.0, spec.adx_min - 2), "relative_volume_min": max(0.5, spec.relative_volume_min - 0.10), "max_holding_candles": min(96, spec.max_holding_candles + 8)}),
            ):
                params = asdict(spec)
                params.update(adjustments)
                params["name"] = f"{spec.name} — {suffix}"
                params["origin"] = "SYSTEM_VARIANT"
                params["code"] = self._code(params["name"], spec.family, params)
                variants.append(StrategySpecification(**params))
        return variants






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
            return StrategyValidationMetrics(0, 0, 1, None, 0, None, 0, None, None, 0, (), False)
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
        target_trades = max(self.settings.adaptive_research_min_trades, self.settings.expectancy_min_trades)
        hard_min_trades = max(8, math.ceil(target_trades * 0.50))
        required_positive_folds = max(1, math.ceil(len(fold_returns) * 0.50))
        hard_failures: list[str] = []
        if trade_count < hard_min_trades: hard_failures.append("INSUFFICIENT_TRADES")
        if expectancy_r <= 0: hard_failures.append("NON_POSITIVE_EXPECTANCY")
        if net_return <= 0: hard_failures.append("NON_POSITIVE_NET_RETURN")
        if max_drawdown > self.settings.adaptive_research_max_drawdown_pct: hard_failures.append("MAX_DRAWDOWN_EXCEEDED")
        if positive_folds < required_positive_folds: hard_failures.append("INSUFFICIENT_POSITIVE_FOLDS")
        soft_checks = {
            "TARGET_TRADE_COUNT": trade_count >= target_trades,
            "TARGET_PROFIT_FACTOR": (profit_factor or 0.0) >= self.settings.adaptive_research_min_profit_factor,
            "TARGET_STABILITY": stability >= self.settings.adaptive_research_min_stability,
            "TARGET_VALIDATION_SCORE": score >= self.settings.adaptive_research_min_validation_score,
        }
        soft_passes = sum(1 for passed in soft_checks.values() if passed)
        activation_floor = max(45.0, self.settings.adaptive_research_min_validation_score - 10.0)
        eligible = not hard_failures and score >= activation_floor and soft_passes >= 2
        failed_gates = tuple(hard_failures + [name for name, passed in soft_checks.items() if not passed])
        return StrategyValidationMetrics(score, net_return, max_drawdown, profit_factor, trade_count, win_rate, expectancy_r, average_win_r, average_loss_r, stability, tuple(fold_returns), eligible, failed_gates, positive_folds, len(fold_returns))


class AdaptiveStrategyResearchEngine:
    """Generates and validates strategies using only local deterministic research."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.templates = StrategyTemplateLibrary()
        self.backtest = StrategyBacktestEngine(settings)
        self.executor = GeneratedStrategyExecutor(settings)

    def research(
        self, market: str, regime: str, execution_timeframe: str,
        trend_timeframe: str, frame: pd.DataFrame, costs: ExecutionCosts, now: datetime,
    ) -> StrategyResearchOutcome:
        research_context = {
            "market": market,
            "execution_timeframe": execution_timeframe,
            "trend_timeframe": trend_timeframe,
            "regime": regime,
        }
        next_research_at = now + timedelta(hours=self.settings.adaptive_research_interval_hours)
        retry_at = now + timedelta(minutes=self.settings.adaptive_research_retry_minutes)
        candidates = self.templates.candidates(regime)
        scored_rows: list[dict[str, Any]] = []
        validated: list[tuple[StrategySpecification, StrategyValidationMetrics]] = []
        for spec in candidates[: self.settings.adaptive_research_max_candidates]:
            metrics = self.backtest.validate(spec, frame, costs)
            scored_rows.append({
                "code": spec.code, "name": spec.name, "family": spec.family,
                "origin": spec.origin, "score": metrics.score,
                "net_return": round(metrics.net_return, 8),
                "max_drawdown_pct": round(metrics.max_drawdown_pct, 8),
                "profit_factor": round(metrics.profit_factor, 6) if metrics.profit_factor is not None else None,
                "trade_count": metrics.trade_count,
                "win_rate": round(metrics.win_rate, 6) if metrics.win_rate is not None else None,
                "stability": round(metrics.stability, 6),
                "expectancy_r": round(metrics.expectancy_r, 6),
                "eligible": metrics.eligible, "failed_gates": list(metrics.failed_gates),
                "positive_folds": metrics.positive_folds, "fold_count": metrics.fold_count,
            })
            if metrics.eligible:
                validated.append((spec, metrics))
        scored_rows.sort(key=lambda item: float(item["score"]), reverse=True)
        rejection_counts: dict[str, int] = {}
        for row in scored_rows:
            for gate in row.get("failed_gates", []):
                rejection_counts[gate] = rejection_counts.get(gate, 0) + 1
        diagnostics = {
            "context": research_context,
            "evaluated_count": len(scored_rows),
            "eligible_count": sum(1 for row in scored_rows if row.get("eligible")),
            "best_candidate": scored_rows[0] if scored_rows else None,
            "rejection_summary": [
                {"gate": gate, "count": count}
                for gate, count in sorted(rejection_counts.items(), key=lambda item: (-item[1], item[0]))
            ],
            "candidates": scored_rows,
        }
        candidate_scores_json = json.dumps(diagnostics, separators=(",", ":"))
        if not validated:
            return StrategyResearchOutcome(
                specification=None, regime=regime, metrics=None,
                research_status="WAITING_FOR_VALID_STRATEGY",
                research_summary=(
                    f"{len(scored_rows)} local hypotheses were generated and tested for "
                    f"{market} ({execution_timeframe}/{trend_timeframe}). "
                    "None reached the activation requirements. The best rejected candidate "
                    "and every failed validation gate were preserved for diagnosis."
                ),
                candidate_scores_json=candidate_scores_json, source_urls_json="[]",
                next_research_at=retry_at, ai_provider="LOCAL", ai_model=None,
                ai_review_status="NOT_USED", ai_review_summary="Local validation only.",
            )
        validated.sort(key=lambda item: item[1].score, reverse=True)
        winner, metrics = validated[0]
        return StrategyResearchOutcome(
            specification=winner, regime=regime, metrics=metrics, research_status="ACTIVE",
            research_summary=(
                f"Selected {winner.name} for {market} ({execution_timeframe}/{trend_timeframe}) "
                f"after validating {len(candidates)} local hypotheses. "
                f"It achieved the strongest cost-adjusted walk-forward score for regime {regime}."
            ),
            candidate_scores_json=candidate_scores_json,
            source_urls_json=json.dumps(winner.source_urls, separators=(",", ":")),
            next_research_at=next_research_at, ai_provider="LOCAL", ai_model=None,
            ai_review_status="NOT_USED", ai_review_summary="Local validation score selected the winner.",
        )
