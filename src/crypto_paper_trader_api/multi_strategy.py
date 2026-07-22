from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timezone

import pandas as pd

from .adaptive_strategy_research import (
    AdaptiveStrategyResearchEngine,
    MarketRegimeAnalyzer,
    StrategySpecification,
)
from .config import Settings
from .execution_costs import ExecutionCosts
from .ml_model import ModelPrediction
from .models import StrategyAccount
from .trading_profiles import TradingProfile, get_trading_profile


@dataclass(frozen=True)
class StrategyDecision:
    technical_signal: str
    model_signal: str
    final_signal: str
    technical_confirmations: int
    reason: str
    execution_reference_price: float | None = None
    setup_status: str | None = None
    potential_target_price: float | None = None
    potential_gross_return: float | None = None
    reward_risk_ratio: float | None = None
    stop_loss_override: float | None = None
    take_profit_override: float | None = None

    # Optional diagnostics emitted by the autonomous AI Pattern Trader.
    ai_mode: str | None = None
    ai_proposed_action: str | None = None
    ai_regime: str | None = None
    ai_pattern_cluster: int | None = None
    ai_confidence: float | None = None
    ai_upward_probability: float | None = None
    ai_neighbor_count: int | None = None
    ai_positive_neighbor_rate: float | None = None
    ai_expected_gross_return: float | None = None
    ai_expected_net_return: float | None = None
    ai_worst_adverse_return: float | None = None
    ai_model_version: str | None = None
    ai_training_samples: int | None = None
    ai_validation_accuracy: float | None = None
    ai_validation_mae: float | None = None
    ai_risk_status: str | None = None
    ai_risk_reason: str | None = None
    ai_horizon_candles: int | None = None
    ai_feature_summary: str | None = None

    # Optional diagnostics emitted by the Adaptive Strategy Selector.
    selector_selected_strategy: str | None = None
    selector_market_regime: str | None = None
    selector_confidence: float | None = None
    selector_expected_net_return: float | None = None
    selector_candidate_scores: str | None = None
    selector_model_version: str | None = None
    selector_active_strategy_name: str | None = None
    selector_strategy_origin: str | None = None
    selector_research_status: str | None = None
    selector_research_summary: str | None = None
    selector_validation_score: float | None = None
    selector_profit_factor: float | None = None
    selector_max_drawdown_pct: float | None = None
    selector_net_return: float | None = None
    selector_trade_count: int | None = None
    selector_next_research_at: datetime | None = None
    selector_strategy_spec_json: str | None = None
    selector_source_urls_json: str | None = None
    selector_ai_provider: str | None = None
    selector_ai_model: str | None = None
    selector_ai_review_status: str | None = None
    selector_ai_review_score: float | None = None
    selector_ai_review_summary: str | None = None


def _ema(row: pd.Series, period: int) -> float:
    return float(row[f"ema_{period}"])


def _candle_body_atr(row: pd.Series, atr: float) -> float:
    return abs(float(row["close"]) - float(row["open"])) / max(atr, 1e-12)


def _bullish_confirmation(row: pd.Series, atr: float, minimum_body_atr: float) -> bool:
    return (
        float(row["close"]) > float(row["open"])
        and _candle_body_atr(row, atr) >= minimum_body_atr
    )


def _not_overextended(
    close: float,
    reference_price: float,
    atr: float,
    maximum_extension_atr: float,
) -> bool:
    extension = close - reference_price
    return 0.0 <= extension <= max(atr, 1e-12) * maximum_extension_atr


def _market_context_values(row: pd.Series) -> tuple[float, float, float]:
    ignition = float(row.get("ignition_score", 0.0) or 0.0)
    exhaustion = float(row.get("exhaustion_score", 0.0) or 0.0)
    compression_ratio = float(row.get("compression_ratio", 1.0) or 1.0)
    compression_score = max(0.0, min(1.0, 1.0 - compression_ratio))
    return ignition, exhaustion, compression_score


def _context_entry_allowed(
    row: pd.Series,
    settings: Settings,
    *,
    require_ignition: bool = False,
) -> bool:
    ignition, exhaustion, _ = _market_context_values(row)
    if exhaustion > settings.exhaustion_max_entry_score:
        return False
    if (
        require_ignition
        and "ignition_score" in row.index
        and ignition < settings.ignition_min_score
    ):
        return False
    return True


def _risk_levels(
    close: float,
    atr: float,
    profile: TradingProfile,
) -> tuple[float, float, float]:
    """Return technical stop and target levels without using trading fees."""

    raw_stop_pct = profile.stop_atr_multiplier * atr / max(close, 1e-9)
    stop_pct = min(max(raw_stop_pct, profile.stop_loss_min_pct), profile.stop_loss_max_pct)
    stop = close * (1 - stop_pct)
    atr_target_pct = profile.take_profit_atr_multiplier * atr / max(close, 1e-9)
    target_pct = max(stop_pct * profile.reward_risk_ratio, atr_target_pct)
    target = close * (1 + target_pct)
    return stop, target, target_pct


class HybridComparisonStrategy:
    """Profile-aware hybrid strategy using technical filters and XGBoost.

    Fees, spread and slippage are deliberately excluded from BUY/SELL authorization.
    They are applied later by the paper broker and reported as execution costs.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        account: StrategyAccount,
        execution_row: pd.Series,
        trend_row: pd.Series,
        prediction: ModelPrediction,
        costs: ExecutionCosts,
        now: datetime,
        profile: TradingProfile | None = None,
    ) -> StrategyDecision:
        active_profile = profile or get_trading_profile(None)
        close = float(execution_row["close"])
        high = float(execution_row["high"])
        open_price = float(execution_row["open"])
        low = float(execution_row["low"])
        atr = float(execution_row["atr_14"])
        fast = _ema(execution_row, active_profile.fast_ema_period)
        slow = _ema(execution_row, active_profile.slow_ema_period)
        regime = _ema(execution_row, active_profile.regime_ema_period)
        trend_fast = _ema(trend_row, active_profile.fast_ema_period)
        trend_slow = _ema(trend_row, active_profile.slow_ema_period)
        trend_regime = _ema(trend_row, active_profile.regime_ema_period)

        bullish_checks = {
            "price_above_regime_ema": close > regime,
            "fast_ema_above_slow_ema": fast > slow,
            "trend_price_above_regime_ema": float(trend_row["close"]) > trend_regime,
            "trend_fast_ema_above_slow_ema": trend_fast > trend_slow,
            "rsi_in_buy_zone": active_profile.rsi_buy_min
            <= float(execution_row["rsi_14"])
            <= active_profile.rsi_buy_max,
            "adx_has_trend": float(execution_row["adx_14"]) >= active_profile.adx_min,
            "volume_confirmed": float(execution_row["relative_volume"])
            >= active_profile.relative_volume_min,
            "trend_adx_has_strength": float(trend_row["adx_14"])
            >= active_profile.trend_adx_min,
        }
        confirmations = sum(bullish_checks.values())
        technical_signal = (
            "BUY" if confirmations >= active_profile.min_technical_confirmations else "HOLD"
        )

        bearish_checks = {
            "fast_ema_below_slow_ema": fast < slow,
            "price_below_regime_ema": close < regime,
            "trend_is_bearish": trend_fast < trend_slow,
            "rsi_is_weak": float(execution_row["rsi_14"]) < 45,
        }
        bearish_count = sum(bearish_checks.values())
        if bearish_count >= 3:
            technical_signal = "SELL"

        current_equity = account.current_equity(close)
        daily_loss_limit_hit = current_equity <= account.initial_capital * (
            1 - active_profile.max_daily_loss_pct
        )
        cooldown_active = bool(
            account.cooldown_until and self._as_utc(account.cooldown_until) > self._as_utc(now)
        )
        stop, target, target_pct = _risk_levels(close, atr, active_profile)
        bullish_entry_candle = _bullish_confirmation(
            execution_row, atr, self.settings.entry_min_body_atr
        )
        close_above_fast = close > fast
        entry_not_overextended = _not_overextended(
            close, fast, atr, self.settings.entry_max_extension_atr
        )
        ignition_score, exhaustion_score, compression_score = _market_context_values(
            execution_row
        )
        context_not_exhausted = _context_entry_allowed(execution_row, self.settings)

        reasons = [
            f"profile={active_profile.code}",
            f"ema_periods={active_profile.fast_ema_period}/{active_profile.slow_ema_period}/{active_profile.regime_ema_period}",
            f"technical_confirmations={confirmations}/8",
            f"bearish_confirmations={bearish_count}/4",
            f"model_probability_up={prediction.upward_probability:.4f}",
            f"expected_return={prediction.expected_return:.6f}",
            f"bullish_entry_candle={str(bullish_entry_candle).lower()}",
            f"entry_body_atr={_candle_body_atr(execution_row, atr):.6f}",
            f"close_above_fast_ema={str(close_above_fast).lower()}",
            f"entry_not_overextended={str(entry_not_overextended).lower()}",
            f"ignition_score={ignition_score:.6f}",
            f"exhaustion_score={exhaustion_score:.6f}",
            f"compression_score={compression_score:.6f}",
            f"context_not_exhausted={str(context_not_exhausted).lower()}",
            "fees_are_accounting_only=true",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            protective_levels = [
                value
                for value in (account.stop_loss_price, account.trailing_stop_price)
                if value is not None
            ]
            protective_stop = max(protective_levels) if protective_levels else None
            if protective_stop is not None and low <= protective_stop:
                reasons.append(f"protective_stop_triggered={protective_stop:.8f}")
                return StrategyDecision(
                    technical_signal,
                    prediction.model_signal,
                    "SELL",
                    confirmations,
                    "; ".join(reasons),
                    protective_stop,
                )
            if account.take_profit_price is not None and high >= account.take_profit_price:
                reasons.append(f"take_profit_triggered={account.take_profit_price:.8f}")
                return StrategyDecision(
                    technical_signal,
                    prediction.model_signal,
                    "SELL",
                    confirmations,
                    "; ".join(reasons),
                    account.take_profit_price,
                )
            if account.entry_time:
                holding_hours = (
                    self._as_utc(now) - self._as_utc(account.entry_time)
                ).total_seconds() / 3600
                if holding_hours >= active_profile.max_holding_hours:
                    reasons.append(f"time_stop_triggered_after_hours={holding_hours:.2f}")
                    return StrategyDecision(
                        technical_signal,
                        prediction.model_signal,
                        "SELL",
                        confirmations,
                        "; ".join(reasons),
                        close,
                    )
            if daily_loss_limit_hit:
                reasons.append("daily_loss_limit_triggered")
                return StrategyDecision(
                    technical_signal,
                    prediction.model_signal,
                    "SELL",
                    confirmations,
                    "; ".join(reasons),
                    close,
                )
            if prediction.model_signal == "SELL" and bearish_count >= 2:
                reasons.append("model_and_bearish_technical_exit")
                return StrategyDecision(
                    technical_signal,
                    prediction.model_signal,
                    "SELL",
                    confirmations,
                    "; ".join(reasons),
                    close,
                )
            reasons.append("open_position_maintained")
            return StrategyDecision(
                technical_signal,
                prediction.model_signal,
                "HOLD",
                confirmations,
                "; ".join(reasons),
            )

        if daily_loss_limit_hit:
            reasons.append("new_entries_blocked_by_daily_loss_limit")
            return StrategyDecision(
                technical_signal,
                prediction.model_signal,
                "HOLD",
                confirmations,
                "; ".join(reasons),
            )
        if cooldown_active:
            reasons.append(f"cooldown_active_until={account.cooldown_until}")
            return StrategyDecision(
                technical_signal,
                prediction.model_signal,
                "HOLD",
                confirmations,
                "; ".join(reasons),
            )

        buy_authorized = all(
            [
                technical_signal == "BUY",
                prediction.upward_probability >= active_profile.buy_probability_threshold,
                prediction.model_signal == "BUY",
                bullish_entry_candle,
                close_above_fast,
                entry_not_overextended,
                context_not_exhausted,
                atr > 0,
            ]
        )
        if buy_authorized:
            reasons.append("technical_and_model_filters_approved")
            return StrategyDecision(
                technical_signal,
                prediction.model_signal,
                "BUY",
                confirmations,
                "; ".join(reasons),
                close,
                potential_target_price=target,
                potential_gross_return=target_pct,
                reward_risk_ratio=active_profile.reward_risk_ratio,
                stop_loss_override=stop,
                take_profit_override=target,
            )

        reasons.append("technical_or_model_filters_not_satisfied")
        return StrategyDecision(
            technical_signal,
            prediction.model_signal,
            "HOLD",
            confirmations,
            "; ".join(reasons),
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class EmaCrossoverStrategy:
    """Fresh fast/slow EMA crossover with technical confirmations only."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        previous_row: pd.Series,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> StrategyDecision:
        close = float(current_row["close"])
        atr = max(float(current_row["atr_14"]), 1e-12)
        fast = _ema(current_row, profile.fast_ema_period)
        slow = _ema(current_row, profile.slow_ema_period)
        regime = _ema(current_row, profile.regime_ema_period)
        previous_fast = _ema(previous_row, profile.fast_ema_period)
        previous_slow = _ema(previous_row, profile.slow_ema_period)
        trend_fast = _ema(trend_row, profile.fast_ema_period)
        trend_slow = _ema(trend_row, profile.slow_ema_period)
        trend_regime = _ema(trend_row, profile.regime_ema_period)

        crossed_up = previous_fast <= previous_slow and fast > slow
        crossed_down = previous_fast >= previous_slow and fast < slow
        stop, target, potential_return = _risk_levels(close, atr, profile)
        bullish_entry_candle = _bullish_confirmation(
            current_row, atr, self.settings.entry_min_body_atr
        )
        close_above_cross = close > max(fast, slow)
        entry_not_overextended = _not_overextended(
            close, fast, atr, self.settings.entry_max_extension_atr
        )
        ignition_score, exhaustion_score, compression_score = _market_context_values(current_row)
        context_not_exhausted = (
            not self.settings.crossover_block_exhaustion
            or _context_entry_allowed(current_row, self.settings)
        )

        checks = {
            "fresh_fast_slow_cross": crossed_up,
            "price_above_regime_ema": close > regime,
            "trend_fast_above_slow": trend_fast > trend_slow,
            "trend_price_above_regime": float(trend_row["close"]) > trend_regime,
            "adx_confirmed": float(current_row["adx_14"]) >= profile.adx_min,
            "volume_confirmed": float(current_row["relative_volume"])
            >= profile.relative_volume_min,
            "rsi_confirmed": profile.rsi_buy_min
            <= float(current_row["rsi_14"])
            <= profile.rsi_buy_max,
            "bullish_entry_candle": bullish_entry_candle,
            "close_above_cross": close_above_cross,
            "entry_not_overextended": entry_not_overextended,
            "context_not_exhausted": context_not_exhausted,
        }
        confirmations = sum(checks.values())
        reasons = [
            f"profile={profile.code}",
            f"ema_periods={profile.fast_ema_period}/{profile.slow_ema_period}/{profile.regime_ema_period}",
            f"crossed_up={crossed_up}",
            f"crossed_down={crossed_down}",
            f"confirmations={confirmations}/11",
            f"entry_body_atr={_candle_body_atr(current_row, atr):.6f}",
            f"ignition_score={ignition_score:.6f}",
            f"exhaustion_score={exhaustion_score:.6f}",
            f"compression_score={compression_score:.6f}",
            f"technical_target_return={potential_return:.6f}",
            "fees_are_accounting_only=true",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            if crossed_down or close < slow:
                reasons.append("fast_ema_crossed_below_slow_or_close_below_slow")
                return StrategyDecision(
                    "SELL", "NOT_USED", "SELL", confirmations, "; ".join(reasons), close
                )
            reasons.append("position_maintained_while_fast_ema_above_slow")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons)
            )

        if all(checks.values()):
            reasons.append("crossover_and_technical_confirmations_approved")
            return StrategyDecision(
                "BUY",
                "NOT_USED",
                "BUY",
                confirmations,
                "; ".join(reasons),
                close,
                potential_target_price=target,
                potential_gross_return=potential_return,
                reward_risk_ratio=profile.reward_risk_ratio,
                stop_loss_override=stop,
                take_profit_override=target,
            )

        reasons.append("crossover_entry_filters_not_all_satisfied")
        return StrategyDecision(
            "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons)
        )


class EmaPullbackStrategy:
    """Buy a bullish pullback to the fast/slow EMA structure."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        previous_row: pd.Series,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> StrategyDecision:
        close = float(current_row["close"])
        open_price = float(current_row["open"])
        low = float(current_row["low"])
        atr = max(float(current_row["atr_14"]), 1e-12)
        fast = _ema(current_row, profile.fast_ema_period)
        slow = _ema(current_row, profile.slow_ema_period)
        regime = _ema(current_row, profile.regime_ema_period)
        previous_close = float(previous_row["close"])
        previous_fast = _ema(previous_row, profile.fast_ema_period)
        trend_fast = _ema(trend_row, profile.fast_ema_period)
        trend_slow = _ema(trend_row, profile.slow_ema_period)
        trend_regime = _ema(trend_row, profile.regime_ema_period)

        touch_buffer = atr * self.settings.ema_pullback_touch_atr
        touch_zone_low = slow - touch_buffer
        touch_zone_high = fast + touch_buffer
        touched_fast_or_slow = low <= touch_zone_high and float(current_row["high"]) >= touch_zone_low
        bullish_structure = fast > slow > regime
        trend_bullish = (
            trend_fast > trend_slow
            and float(trend_row["close"]) > trend_regime
        )
        bullish_rejection = (
            _bullish_confirmation(current_row, atr, self.settings.entry_min_body_atr)
            and close > fast
            and close >= previous_close
            and close - low >= float(current_row["high"]) - close
        )
        pullback_started_above_fast = previous_close >= previous_fast
        entry_not_overextended = _not_overextended(
            close, fast, atr, min(self.settings.entry_max_extension_atr, 0.90)
        )
        adx_ok = float(current_row["adx_14"]) >= profile.adx_min
        volume_ok = float(current_row["relative_volume"]) >= profile.relative_volume_min
        rsi_ok = profile.rsi_buy_min <= float(current_row["rsi_14"]) <= profile.rsi_buy_max
        ignition_score, exhaustion_score, compression_score = _market_context_values(current_row)
        context_not_exhausted = _context_entry_allowed(current_row, self.settings)
        checks = {
            "bullish_ema_structure": bullish_structure,
            "bullish_trend_timeframe": trend_bullish,
            "pulled_back_to_ema": touched_fast_or_slow,
            "bullish_rejection_close": bullish_rejection,
            "pullback_started_above_fast": pullback_started_above_fast,
            "entry_not_overextended": entry_not_overextended,
            "adx_confirmed": adx_ok,
            "volume_confirmed": volume_ok,
            "rsi_confirmed": rsi_ok,
            "context_not_exhausted": context_not_exhausted,
        }
        confirmations = sum(checks.values())
        stop, target, potential_return = _risk_levels(close, atr, profile)
        stop = min(stop, low - 0.05 * atr)
        risk = max(close - stop, 1e-12)
        target = max(target, close + profile.reward_risk_ratio * risk)
        potential_return = (target - close) / max(close, 1e-12)
        rr = (target - close) / risk
        reasons = [
            f"profile={profile.code}",
            f"ema_structure={bullish_structure}",
            f"trend_bullish={trend_bullish}",
            f"pulled_back_to_ema={touched_fast_or_slow}",
            f"bullish_rejection={bullish_rejection}",
            f"confirmations={confirmations}/10",
            f"entry_body_atr={_candle_body_atr(current_row, atr):.6f}",
            f"ignition_score={ignition_score:.6f}",
            f"exhaustion_score={exhaustion_score:.6f}",
            f"compression_score={compression_score:.6f}",
            f"touch_zone={touch_zone_low:.8f}-{touch_zone_high:.8f}",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            if close < slow or not trend_bullish:
                reasons.append("close_below_slow_ema_or_trend_reversed")
                return StrategyDecision(
                    "SELL", "NOT_USED", "SELL", confirmations, "; ".join(reasons), close
                )
            reasons.append("bullish_pullback_position_maintained")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons)
            )

        if all(checks.values()):
            reasons.append("ema_pullback_entry_approved")
            return StrategyDecision(
                "BUY", "NOT_USED", "BUY", confirmations, "; ".join(reasons), close,
                potential_target_price=target,
                potential_gross_return=potential_return,
                reward_risk_ratio=rr,
                stop_loss_override=stop,
                take_profit_override=target,
            )
        reasons.append("ema_pullback_filters_not_all_satisfied")
        return StrategyDecision(
            "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons)
        )


class StormerFilhaMalCriadaStrategy:
    """Long-only Stormer-style EMA ribbon pullback setup for paper trading."""

    EMA_PERIODS = (20, 25, 30, 35, 40, 45, 50)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @staticmethod
    def _timestamp(row: pd.Series) -> datetime:
        value = pd.Timestamp(row["timestamp"]).to_pydatetime()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _clear_setup(account: StrategyAccount, reason: str | None = None) -> None:
        account.setup_status = "IDLE"
        account.setup_candle_timestamp = None
        account.setup_candle_high = None
        account.setup_candle_low = None
        account.entry_trigger_price = None
        account.initial_setup_stop_price = None
        account.setup_target_price = None
        account.setup_cancel_reason = reason

    def decide(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        previous_row: pd.Series,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> StrategyDecision:
        close = float(current_row["close"])
        high = float(current_row["high"])
        low = float(current_row["low"])
        atr = max(float(current_row["atr_14"]), 1e-12)
        timestamp = self._timestamp(current_row)
        emas = {period: _ema(current_row, period) for period in self.EMA_PERIODS}
        previous_emas = {period: _ema(previous_row, period) for period in self.EMA_PERIODS}
        trend_emas = {period: _ema(trend_row, period) for period in self.EMA_PERIODS}

        aligned = all(emas[left] > emas[right] for left, right in zip(self.EMA_PERIODS, self.EMA_PERIODS[1:]))
        slopes_up = all(emas[period] > previous_emas[period] for period in self.EMA_PERIODS)
        trend_aligned = all(
            trend_emas[left] > trend_emas[right]
            for left, right in zip(self.EMA_PERIODS, self.EMA_PERIODS[1:])
        )
        price_above_longest = close > emas[50]
        touched = [period for period in self.EMA_PERIODS[:-1] if low <= emas[period]]
        deepest_touched = max(touched) if touched else None
        tick_buffer = max(close * 1e-6, atr * 0.001)
        stop_buffer = max(close * 1e-6, atr * 0.10)

        checks = {
            "ema_ribbon_aligned": aligned,
            "ema_ribbon_sloping_up": slopes_up,
            "trend_timeframe_aligned": trend_aligned,
            "price_above_ema_50": price_above_longest,
            "pullback_touched_ribbon": deepest_touched is not None,
        }
        confirmations = sum(checks.values())
        ignition_score, exhaustion_score, compression_score = _market_context_values(current_row)
        context_not_exhausted = _context_entry_allowed(current_row, self.settings)
        reasons = [
            "setup=STORMER_FILHA_MAL_CRIADA",
            f"ema_periods={','.join(map(str, self.EMA_PERIODS))}",
            f"aligned={str(aligned).lower()}",
            f"slopes_up={str(slopes_up).lower()}",
            f"trend_aligned={str(trend_aligned).lower()}",
            f"deepest_touched={deepest_touched}",
            f"confirmations={confirmations}/5",
            f"ignition_score={ignition_score:.6f}",
            f"exhaustion_score={exhaustion_score:.6f}",
            f"compression_score={compression_score:.6f}",
            f"context_not_exhausted={str(context_not_exhausted).lower()}",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            if close < emas[50] or not aligned:
                self._clear_setup(account, "EMA ribbon invalidated while position was open.")
                reasons.append("close_below_ema50_or_alignment_lost")
                return StrategyDecision("SELL", "NOT_USED", "SELL", confirmations, "; ".join(reasons), close, setup_status="IN_POSITION")
            reasons.append("position_maintained_inside_aligned_ribbon_trend")
            return StrategyDecision("HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons), setup_status="IN_POSITION")

        if account.setup_status == "ARMED" and account.entry_trigger_price is not None:
            if close < emas[50] or not aligned or not trend_aligned:
                self._clear_setup(account, "EMA ribbon alignment was lost before entry.")
                account.last_setup_event = "SETUP_CANCELLED"
                account.last_setup_event_reason = "The candle closed below EMA 50 or the EMA ribbon lost alignment."
                reasons.append("armed_setup_cancelled")
                return StrategyDecision("HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons), setup_status="CANCELLED")

            trigger = float(account.entry_trigger_price)
            setup_time = account.setup_candle_timestamp
            different_candle = setup_time is None or timestamp > setup_time
            breakout_confirmed = (
                different_candle
                and high >= trigger
                and close >= trigger
                and _bullish_confirmation(current_row, atr, self.settings.entry_min_body_atr)
                and close - trigger <= atr * self.settings.entry_max_extension_atr
                and context_not_exhausted
            )
            if breakout_confirmed:
                stop = float(account.initial_setup_stop_price or (emas[50] - stop_buffer))
                risk = max(trigger - stop, tick_buffer)
                target = trigger + 3.0 * risk
                account.setup_status = "TRIGGERED"
                account.setup_target_price = target
                account.last_setup_event = "BREAKOUT_ENTRY"
                account.last_setup_event_reason = "Price broke above the armed pullback candle high."
                reasons.extend([
                    f"entry_triggered={trigger:.8f}",
                    "breakout_closed_above_trigger=true",
                    f"entry_body_atr={_candle_body_atr(current_row, atr):.6f}",
                ])
                return StrategyDecision(
                    "BUY", "NOT_USED", "BUY", confirmations, "; ".join(reasons), trigger,
                    setup_status="TRIGGERED", potential_target_price=target,
                    potential_gross_return=(target-trigger)/max(trigger,1e-12), reward_risk_ratio=3.0,
                    stop_loss_override=stop, take_profit_override=target,
                )

            if deepest_touched is not None:
                next_period = next((period for period in self.EMA_PERIODS if period > deepest_touched), 50)
                stop = emas[next_period] - stop_buffer
                account.setup_candle_timestamp = timestamp
                account.setup_candle_high = high
                account.setup_candle_low = low
                account.entry_trigger_price = high + tick_buffer
                account.initial_setup_stop_price = stop
                account.setup_target_price = account.entry_trigger_price + 3.0 * max(account.entry_trigger_price - stop, tick_buffer)
                account.last_setup_event = "ENTRY_TRIGGER_UPDATED"
                account.last_setup_event_reason = "The pullback continued, so the buy-stop was moved above the latest candle."
                reasons.append("armed_trigger_updated_after_deeper_pullback")
            else:
                reasons.append("waiting_for_closed_bullish_breakout_above_armed_trigger")
            return StrategyDecision("HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons), setup_status="ARMED", potential_target_price=account.setup_target_price, reward_risk_ratio=3.0, stop_loss_override=account.initial_setup_stop_price, take_profit_override=account.setup_target_price)

        if aligned and slopes_up and trend_aligned and price_above_longest and deepest_touched is not None:
            next_period = next((period for period in self.EMA_PERIODS if period > deepest_touched), 50)
            trigger = high + tick_buffer
            stop = emas[next_period] - stop_buffer
            risk = max(trigger - stop, tick_buffer)
            target = trigger + 3.0 * risk
            account.setup_status = "ARMED"
            account.setup_candle_timestamp = timestamp
            account.setup_candle_high = high
            account.setup_candle_low = low
            account.entry_trigger_price = trigger
            account.initial_setup_stop_price = stop
            account.setup_target_price = target
            account.setup_cancel_reason = None
            account.last_setup_event = "PULLBACK_SETUP_ARMED"
            account.last_setup_event_reason = f"The bullish EMA ribbon was touched at EMA {deepest_touched}."
            reasons.append(f"setup_armed_at_ema={deepest_touched}")
            return StrategyDecision("HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons), setup_status="ARMED", potential_target_price=target, potential_gross_return=(target-trigger)/max(trigger,1e-12), reward_risk_ratio=3.0, stop_loss_override=stop, take_profit_override=target)

        reasons.append("waiting_for_aligned_ribbon_and_pullback")
        return StrategyDecision("HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons), setup_status="WAITING")


class LarryVolatilityBreakoutStrategy:
    """Intraday open-plus-range breakout with trend and volume confirmation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        previous_window: pd.DataFrame,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> StrategyDecision:
        close = float(current_row["close"])
        high = float(current_row["high"])
        open_price = float(current_row["open"])
        atr = max(float(current_row["atr_14"]), 1e-12)
        if previous_window.empty:
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", 0,
                "larry_breakout_waiting_for_lookback_window",
            )
        reference_range = float(previous_window["high"].max() - previous_window["low"].min())
        trigger = open_price + reference_range * self.settings.larry_breakout_factor
        trend_bullish = (
            float(trend_row["close"]) > _ema(trend_row, profile.regime_ema_period)
            and _ema(trend_row, profile.fast_ema_period) > _ema(trend_row, profile.slow_ema_period)
        )
        price_above_regime = close > _ema(current_row, profile.regime_ema_period)
        breakout_buffer = atr * self.settings.breakout_close_buffer_atr
        breakout = high >= trigger and close >= trigger + breakout_buffer
        bullish_breakout_candle = _bullish_confirmation(
            current_row, atr, self.settings.entry_min_body_atr
        )
        close_near_high = close >= high - max((high - float(current_row["low"])) * 0.30, 1e-12)
        entry_not_overextended = close - trigger <= atr * self.settings.entry_max_extension_atr
        volume_ok = float(current_row["relative_volume"]) >= profile.relative_volume_min
        adx_ok = float(current_row["adx_14"]) >= profile.adx_min
        ignition_score, exhaustion_score, compression_score = _market_context_values(current_row)
        ignition_confirmed = (
            not self.settings.breakout_require_ignition
            or "ignition_score" not in current_row.index
            or ignition_score >= self.settings.ignition_min_score
        )
        context_not_exhausted = _context_entry_allowed(current_row, self.settings)
        checks = {
            "range_breakout": breakout,
            "trend_bullish": trend_bullish,
            "price_above_regime": price_above_regime,
            "volume_confirmed": volume_ok,
            "adx_confirmed": adx_ok,
            "bullish_breakout_candle": bullish_breakout_candle,
            "close_near_high": close_near_high,
            "entry_not_overextended": entry_not_overextended,
            "ignition_confirmed": ignition_confirmed,
            "context_not_exhausted": context_not_exhausted,
        }
        confirmations = sum(checks.values())
        stop = close - self.settings.larry_breakout_stop_atr * atr
        target = close + self.settings.larry_breakout_target_atr * atr
        risk = max(close - stop, 1e-12)
        rr = (target - close) / risk
        potential_return = (target - close) / max(close, 1e-12)
        reasons = [
            f"profile={profile.code}",
            f"lookback={len(previous_window)}",
            f"reference_range={reference_range:.8f}",
            f"breakout_trigger={trigger:.8f}",
            f"breakout={breakout}",
            f"confirmations={confirmations}/10",
            f"breakout_buffer={breakout_buffer:.8f}",
            f"ignition_score={ignition_score:.6f}",
            f"exhaustion_score={exhaustion_score:.6f}",
            f"compression_score={compression_score:.6f}",
            f"entry_body_atr={_candle_body_atr(current_row, atr):.6f}",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            fast = _ema(current_row, profile.fast_ema_period)
            if close < fast or not trend_bullish:
                reasons.append("breakout_momentum_lost")
                return StrategyDecision(
                    "SELL", "NOT_USED", "SELL", confirmations, "; ".join(reasons), close
                )
            reasons.append("breakout_position_maintained")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons)
            )

        if all(checks.values()):
            reasons.append("larry_volatility_breakout_approved")
            return StrategyDecision(
                "BUY", "NOT_USED", "BUY", confirmations, "; ".join(reasons), trigger,
                potential_target_price=target,
                potential_gross_return=potential_return,
                reward_risk_ratio=rr,
                stop_loss_override=stop,
                take_profit_override=target,
            )
        reasons.append("larry_volatility_breakout_filters_not_all_satisfied")
        return StrategyDecision(
            "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons),
            execution_reference_price=trigger,
        )


class AdaptiveStrategySelector:
    """Researches, validates and executes a generated strategy for the selected market."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = AdaptiveStrategyResearchEngine(settings)

    @staticmethod
    def detect_regime(current_row: pd.Series, trend_row: pd.Series) -> str:
        return MarketRegimeAnalyzer.detect(current_row, trend_row)

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _needs_research(
        self,
        account: StrategyAccount,
        regime: str,
        now: datetime,
    ) -> bool:
        current_spec = StrategySpecification.from_json(account.selector_strategy_spec_json)
        if current_spec is None:
            return True
        if account.selector_market_regime != regime:
            return True
        next_research = self._as_utc(account.selector_next_research_at)
        return next_research is None or now >= next_research

    def decide(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        research_frame: pd.DataFrame,
        current_index: int,
        market: str,
        execution_timeframe: str,
        trend_timeframe: str,
        now: datetime,
    ) -> StrategyDecision:
        regime = self.detect_regime(current_row, trend_row)
        close = float(current_row["close"])
        active_spec = StrategySpecification.from_json(account.selector_strategy_spec_json)

        # An open paper position always remains attached to the strategy that opened it.
        # Research can replace the active strategy only after the position is flat.
        if not account.has_open_position and self._needs_research(account, regime, now):
            outcome = self.engine.research(
                market=market,
                regime=regime,
                execution_timeframe=execution_timeframe,
                trend_timeframe=trend_timeframe,
                frame=research_frame,
                costs=costs,
                now=now,
            )
            account.selector_market_regime = outcome.regime
            account.selector_research_status = outcome.research_status
            account.selector_research_summary = outcome.research_summary
            account.selector_candidate_scores = outcome.candidate_scores_json
            account.selector_source_urls_json = outcome.source_urls_json
            account.selector_next_research_at = outcome.next_research_at
            account.selector_model_version = self.settings.selector_model_version
            account.selector_last_error = outcome.error_message
            account.selector_ai_provider = outcome.ai_provider
            account.selector_ai_model = outcome.ai_model
            account.selector_ai_review_status = outcome.ai_review_status
            account.selector_ai_review_score = outcome.ai_review_score
            account.selector_ai_review_summary = outcome.ai_review_summary

            if outcome.specification is None or outcome.metrics is None:
                account.selector_selected_strategy = None
                account.selector_active_strategy_name = None
                account.selector_strategy_origin = None
                account.selector_strategy_spec_json = None
                account.selector_validation_score = None
                account.selector_profit_factor = None
                account.selector_max_drawdown_pct = None
                account.selector_net_return = None
                account.selector_trade_count = None
                return StrategyDecision(
                    "HOLD", "RESEARCH_SELECTOR", "HOLD", 0,
                    outcome.research_summary,
                    selector_market_regime=regime,
                    selector_candidate_scores=outcome.candidate_scores_json,
                    selector_model_version=self.settings.selector_model_version,
                    selector_research_status=outcome.research_status,
                    selector_research_summary=outcome.research_summary,
                    selector_next_research_at=outcome.next_research_at,
                    selector_source_urls_json=outcome.source_urls_json,
                    selector_ai_provider=outcome.ai_provider,
                    selector_ai_model=outcome.ai_model,
                    selector_ai_review_status=outcome.ai_review_status,
                    selector_ai_review_score=outcome.ai_review_score,
                    selector_ai_review_summary=outcome.ai_review_summary,
                )

            active_spec = outcome.specification
            metrics = outcome.metrics
            account.selector_selected_strategy = active_spec.code
            account.selector_active_strategy_name = active_spec.name
            account.selector_strategy_origin = active_spec.origin
            account.selector_strategy_spec_json = active_spec.to_json()
            account.selector_validation_score = metrics.score
            account.selector_profit_factor = metrics.profit_factor
            account.selector_max_drawdown_pct = metrics.max_drawdown_pct
            account.selector_net_return = metrics.net_return
            account.selector_trade_count = metrics.trade_count
            account.selector_confidence = min(max(metrics.score / 100.0, 0.0), 1.0)
            account.selector_expected_net_return = metrics.net_return

        if active_spec is None:
            reason = account.selector_research_summary or (
                "No generated strategy has passed the validation requirements yet."
            )
            return StrategyDecision(
                "HOLD", "RESEARCH_SELECTOR", "HOLD", 0, reason,
                selector_market_regime=regime,
                selector_candidate_scores=account.selector_candidate_scores,
                selector_model_version=self.settings.selector_model_version,
                selector_research_status=account.selector_research_status or "WAITING_FOR_VALID_STRATEGY",
                selector_research_summary=reason,
                selector_next_research_at=account.selector_next_research_at,
                selector_source_urls_json=account.selector_source_urls_json,
                selector_ai_provider=account.selector_ai_provider,
                selector_ai_model=account.selector_ai_model,
                selector_ai_review_status=account.selector_ai_review_status,
                selector_ai_review_score=account.selector_ai_review_score,
                selector_ai_review_summary=account.selector_ai_review_summary,
            )

        live = self.engine.executor.live_decision(
            spec=active_spec,
            account=account,
            frame=research_frame,
            current_index=current_index,
            regime=regime,
        )
        signal = str(live["signal"])
        reason = (
            f"generated_strategy={active_spec.code}; name={active_spec.name}; "
            f"origin={active_spec.origin}; regime={regime}; rule={live['reason']}; "
            f"validation_score={float(account.selector_validation_score or 0):.2f}"
        )
        return StrategyDecision(
            signal,
            "RESEARCH_SELECTOR",
            signal,
            0,
            reason,
            live.get("execution_reference_price") or close,
            potential_target_price=live.get("take_profit"),
            potential_gross_return=live.get("potential_gross_return"),
            reward_risk_ratio=live.get("reward_risk_ratio"),
            stop_loss_override=live.get("stop_loss"),
            take_profit_override=live.get("take_profit"),
            selector_selected_strategy=active_spec.code,
            selector_market_regime=regime,
            selector_confidence=account.selector_confidence,
            selector_expected_net_return=account.selector_expected_net_return,
            selector_candidate_scores=account.selector_candidate_scores,
            selector_model_version=self.settings.selector_model_version,
            selector_active_strategy_name=active_spec.name,
            selector_strategy_origin=active_spec.origin,
            selector_research_status=account.selector_research_status or "ACTIVE",
            selector_research_summary=account.selector_research_summary,
            selector_validation_score=account.selector_validation_score,
            selector_profit_factor=account.selector_profit_factor,
            selector_max_drawdown_pct=account.selector_max_drawdown_pct,
            selector_net_return=account.selector_net_return,
            selector_trade_count=account.selector_trade_count,
            selector_next_research_at=account.selector_next_research_at,
            selector_strategy_spec_json=active_spec.to_json(),
            selector_source_urls_json=account.selector_source_urls_json,
            selector_ai_provider=account.selector_ai_provider,
            selector_ai_model=account.selector_ai_model,
            selector_ai_review_status=account.selector_ai_review_status,
            selector_ai_review_score=account.selector_ai_review_score,
            selector_ai_review_summary=account.selector_ai_review_summary,
        )


# Backward-compatible class name used by v0.6.0 databases and imports.
EmaCrossoverCostAwareStrategy = EmaCrossoverStrategy


class Ema9Setup91Strategy:
    """Strict Larry Williams Setup 9.1 with selectable stop management.

    Both variants use the same entry setup:
    - EMA 9 must turn strictly from DOWN to UP on closed candles;
    - the reversal candle must cross EMA 9;
    - entry is armed above that candle high;
    - the initial protective stop is that candle low.

    ``CLASSIC`` keeps the setup stop and later arms an exit below the low of the
    candle that turns EMA 9 down. ``TREND_FOLLOWER`` raises a candle-low trailing
    stop after every closed candle and exits when EMA 9 turns bearish.
    """

    CLASSIC = "CLASSIC"
    TREND_FOLLOWER = "TREND_FOLLOWER"

    def __init__(
        self,
        settings: Settings | None = None,
        cost_aware: bool = False,
        mode: str = CLASSIC,
    ) -> None:
        self.settings = settings
        self.cost_aware = cost_aware  # retained for backward constructor compatibility
        normalized_mode = str(mode).strip().upper()
        if normalized_mode not in {self.CLASSIC, self.TREND_FOLLOWER}:
            raise ValueError(f"Unsupported EMA9 stop management mode: {mode}")
        self.mode = normalized_mode

    @staticmethod
    def _crosses_ema(row: pd.Series, ema_value: float) -> bool:
        return float(row["low"]) <= ema_value <= float(row["high"])

    @staticmethod
    def _clear_classic_exit_trigger(account: StrategyAccount) -> None:
        account.exit_trigger_price = None
        account.exit_trigger_candle_timestamp = None
        account.exit_trigger_candle_low = None

    def analyze_candle(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        previous_row: pd.Series,
        previous_previous_row: pd.Series,
        costs: ExecutionCosts,
        now: datetime,
        profile: TradingProfile | None = None,
    ) -> StrategyDecision:
        active_profile = profile or get_trading_profile(None)
        close = float(current_row["close"])
        high = float(current_row["high"])
        low = float(current_row["low"])
        open_price = float(current_row["open"])
        atr = max(float(current_row["atr_14"]), 1e-12)
        ema9 = float(current_row["ema_9"])
        ema9_prev = float(previous_row["ema_9"])
        ema9_prev2 = float(previous_previous_row["ema_9"])
        current_slope = ema9 - ema9_prev
        previous_slope = ema9_prev - ema9_prev2
        epsilon = max(abs(ema9) * 1e-8, 1e-12)
        direction = (
            "UP" if current_slope > epsilon else "DOWN" if current_slope < -epsilon else "FLAT"
        )
        candle_crossed_ema9 = self._crosses_ema(current_row, ema9)

        account.ema_9_previous = ema9_prev
        account.ema_9 = ema9
        account.ema_9_slope = current_slope
        account.ema_9_direction = direction
        account.stop_management_mode = self.mode

        reasons = [
            f"profile={active_profile.code}",
            f"stop_management_mode={self.mode}",
            f"ema9={ema9:.8f}",
            f"ema9_previous={ema9_prev:.8f}",
            f"previous_slope={previous_slope:.8f}",
            f"current_slope={current_slope:.8f}",
            f"candle_crossed_ema9={str(candle_crossed_ema9).lower()}",
            f"entry_body_atr={_candle_body_atr(current_row, atr):.6f}",
            "fees_are_accounting_only=true",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            if self.mode == self.TREND_FOLLOWER:
                # The candle that has just closed becomes the previous candle for the
                # next live interval. Its low can only raise, never loosen, the stop.
                if current_slope < -epsilon:
                    account.last_setup_event = "EMA9_TREND_EXIT"
                    account.last_setup_event_reason = "EMA 9 turned down on the closed candle."
                    reasons.append("ema9_turned_down_trend_exit")
                    return StrategyDecision(
                        "SELL",
                        "NOT_USED",
                        "SELL",
                        1,
                        "; ".join(reasons),
                        close,
                        setup_status="IN_POSITION",
                    )
                if close < ema9 and candle_crossed_ema9:
                    account.last_setup_event = "EMA9_CROSS_EXIT"
                    account.last_setup_event_reason = (
                        "The bearish reversal candle crossed EMA 9 and closed below it."
                    )
                    reasons.append("bearish_reversal_candle_closed_below_ema9")
                    return StrategyDecision(
                        "SELL",
                        "NOT_USED",
                        "SELL",
                        1,
                        "; ".join(reasons),
                        close,
                        setup_status="IN_POSITION",
                    )

                candidate_stop = low
                active_stop = max(
                    value
                    for value in (
                        float(account.stop_loss_price or 0.0),
                        float(account.trailing_stop_price or 0.0),
                    )
                )
                if candidate_stop > active_stop and candidate_stop < close:
                    account.trailing_stop_price = candidate_stop
                    account.last_setup_event = "CANDLE_LOW_STOP_RAISED"
                    account.last_setup_event_reason = (
                        "The trend-following stop was raised to the low of the latest closed candle."
                    )
                    reasons.append(f"candle_low_trailing_stop_raised={candidate_stop:.8f}")
                else:
                    reasons.append(f"candle_low_stop_unchanged={active_stop:.8f}")

                reasons.append("trend_follower_position_maintained")
                return StrategyDecision(
                    "HOLD",
                    "NOT_USED",
                    "HOLD",
                    1,
                    "; ".join(reasons),
                    setup_status="IN_POSITION",
                    stop_loss_override=max(
                        value
                        for value in (
                            account.stop_loss_price or 0.0,
                            account.trailing_stop_price or 0.0,
                        )
                    ),
                )

            # Classic management: keep the original setup stop. A strict UP-to-DOWN
            # turn on a candle crossing EMA 9 arms an exit below that candle low.
            if account.exit_trigger_price is not None:
                if current_slope > epsilon:
                    self._clear_classic_exit_trigger(account)
                    account.setup_status = "IN_POSITION"
                    account.last_setup_event = "CLASSIC_EXIT_CANCELLED"
                    account.last_setup_event_reason = (
                        "EMA 9 turned up again before the classical exit trigger was broken."
                    )
                    reasons.append("classic_exit_trigger_cancelled_ema9_turned_up")
                else:
                    account.setup_status = "EXIT_ARMED"
                    reasons.append(
                        f"classic_exit_waiting_below={account.exit_trigger_price:.8f}"
                    )
                    return StrategyDecision(
                        "EXIT_ARMED",
                        "NOT_USED",
                        "HOLD",
                        1,
                        "; ".join(reasons),
                        execution_reference_price=account.exit_trigger_price,
                        setup_status="EXIT_ARMED",
                    )

            bearish_reversal = previous_slope > epsilon and current_slope < -epsilon
            if bearish_reversal and candle_crossed_ema9:
                tick_rate = self.settings.ema9_entry_tick_rate if self.settings is not None else 0.0
                exit_trigger = max(low * (1 - tick_rate), 0.0)
                account.exit_trigger_price = exit_trigger
                account.exit_trigger_candle_timestamp = now
                account.exit_trigger_candle_low = low
                account.setup_status = "EXIT_ARMED"
                account.last_setup_event = "CLASSIC_EXIT_ARMED"
                account.last_setup_event_reason = (
                    "EMA 9 turned down. Waiting for price to break the reversal candle low."
                )
                reasons.extend(
                    [
                        "classic_up_to_down_reversal_detected",
                        f"classic_exit_trigger={exit_trigger:.8f}",
                    ]
                )
                return StrategyDecision(
                    "EXIT_ARMED",
                    "NOT_USED",
                    "HOLD",
                    1,
                    "; ".join(reasons),
                    execution_reference_price=exit_trigger,
                    setup_status="EXIT_ARMED",
                )

            reasons.append("classic_position_maintained_with_setup_stop")
            return StrategyDecision(
                "HOLD",
                "NOT_USED",
                "HOLD",
                1,
                "; ".join(reasons),
                setup_status="IN_POSITION",
                stop_loss_override=account.stop_loss_price,
            )

        # No open position: clear any exit state left by an older version.
        self._clear_classic_exit_trigger(account)

        if account.setup_status == "ARMED":
            # The original stop-entry is adapted to closed-candle confirmation. A wick above
            # the trigger is not enough: the later candle must close above it with a bullish
            # body and without being excessively extended from the trigger.
            trigger = float(account.entry_trigger_price or 0.0)
            setup_timestamp = account.setup_candle_timestamp
            different_candle = setup_timestamp is None or self._as_utc(now) > self._as_utc(setup_timestamp)
            ignition_score, exhaustion_score, compression_score = _market_context_values(current_row)
            context_not_exhausted = (
                self.settings is None
                or _context_entry_allowed(current_row, self.settings)
            )
            confirmed_breakout = (
                different_candle
                and trigger > 0
                and high >= trigger
                and close >= trigger
                and _bullish_confirmation(
                    current_row, atr, self.settings.entry_min_body_atr if self.settings else 0.08
                )
                and close - trigger <= atr * (
                    self.settings.entry_max_extension_atr if self.settings else 1.25
                )
                and context_not_exhausted
            )
            if confirmed_breakout:
                account.setup_status = "TRIGGERED"
                account.last_setup_event = "CLOSED_CANDLE_BREAKOUT_ENTRY"
                account.last_setup_event_reason = (
                    "A later bullish candle closed above the EMA 9 setup trigger."
                )
                reasons.extend(
                    [
                        f"closed_candle_breakout_trigger={trigger:.8f}",
                        f"breakout_close={close:.8f}",
                        "breakout_confirmed_on_closed_candle=true",
                        f"ignition_score={ignition_score:.6f}",
                        f"exhaustion_score={exhaustion_score:.6f}",
                        f"compression_score={compression_score:.6f}",
                    ]
                )
                return StrategyDecision(
                    "BUY",
                    "NOT_USED",
                    "BUY",
                    1,
                    "; ".join(reasons),
                    execution_reference_price=close,
                    setup_status="TRIGGERED",
                    stop_loss_override=account.initial_setup_stop_price,
                    take_profit_override=None,
                )
            if different_candle and high >= trigger and close < trigger:
                account.last_setup_event = "FALSE_BREAKOUT"
                account.last_setup_event_reason = (
                    "Price crossed the trigger intrabar but the candle did not close above it."
                )
                reasons.append("intrabar_breakout_rejected_without_close_confirmation")

            # A pending 9.1 entry is valid only while EMA 9 is still clearly rising
            # and while the setup remains recent enough to represent the same reversal.
            setup_age_hours = (
                (self._as_utc(now) - self._as_utc(account.setup_candle_timestamp)).total_seconds() / 3600
                if account.setup_candle_timestamp is not None
                else 0.0
            )
            if setup_age_hours > (self.settings.ema9_setup_max_age_hours if self.settings else 4.0):
                account.setup_status = "CANCELLED"
                account.setup_cancel_reason = "The EMA 9 breakout did not occur before the setup expired."
                account.last_setup_event = "SETUP_EXPIRED"
                account.last_setup_event_reason = account.setup_cancel_reason
                reasons.append(f"armed_setup_expired_after_hours={setup_age_hours:.2f}")
                return StrategyDecision(
                    "CANCELLED", "NOT_USED", "HOLD", 0, "; ".join(reasons),
                    setup_status="CANCELLED",
                )
            if current_slope <= epsilon:
                account.setup_status = "CANCELLED"
                account.setup_cancel_reason = (
                    "EMA 9 stopped rising before the entry trigger was reached."
                )
                account.last_setup_event = "SETUP_CANCELLED"
                account.last_setup_event_reason = account.setup_cancel_reason
                reasons.append("armed_setup_cancelled_ema9_not_rising")
                return StrategyDecision(
                    "CANCELLED",
                    "NOT_USED",
                    "HOLD",
                    0,
                    "; ".join(reasons),
                    setup_status="CANCELLED",
                )
            reasons.append("armed_setup_waiting_for_breakout")
            return StrategyDecision(
                "ARMED",
                "NOT_USED",
                "HOLD",
                1,
                "; ".join(reasons),
                execution_reference_price=account.entry_trigger_price,
                setup_status="ARMED",
                stop_loss_override=account.initial_setup_stop_price,
            )

        strict_reversal = previous_slope < -epsilon and current_slope > epsilon
        bullish_setup_candle = _bullish_confirmation(
            current_row, atr, self.settings.entry_min_body_atr if self.settings else 0.08
        )
        closed_above_ema9 = close > ema9
        reversal_detected = (
            strict_reversal
            and candle_crossed_ema9
            and bullish_setup_candle
            and closed_above_ema9
        )
        if not reversal_detected:
            if account.setup_status not in {"CANCELLED", "MISSED_ENTRY", "REJECTED"}:
                account.setup_status = "IDLE"
            account.last_setup_event = "WAITING_FOR_REVERSAL"
            if strict_reversal and not candle_crossed_ema9:
                account.last_setup_event_reason = (
                    "EMA 9 turned up, but the reversal candle did not cross the average."
                )
                reasons.append("strict_reversal_without_ema9_cross")
            elif strict_reversal and not bullish_setup_candle:
                account.last_setup_event_reason = (
                    "EMA 9 turned up, but the setup candle did not have a sufficiently bullish body."
                )
                reasons.append("strict_reversal_without_bullish_setup_candle")
            elif strict_reversal and not closed_above_ema9:
                account.last_setup_event_reason = (
                    "EMA 9 turned up, but the setup candle did not close above the average."
                )
                reasons.append("strict_reversal_without_close_above_ema9")
            else:
                account.last_setup_event_reason = (
                    "EMA 9 has not completed a strict down-to-up turn on closed candles."
                )
                reasons.append("no_strict_down_to_up_ema9_reversal")
            return StrategyDecision(
                "HOLD",
                "NOT_USED",
                "HOLD",
                0,
                "; ".join(reasons),
                setup_status=account.setup_status,
            )

        setup_high = high
        setup_low = low
        tick_rate = self.settings.ema9_entry_tick_rate if self.settings is not None else 0.0
        trigger = setup_high * (1 + tick_rate)
        stop = max(setup_low, 0.0)
        risk = trigger - stop

        reasons.extend(
            [
                "strict_ema9_down_to_up_reversal_detected",
                "setup_candle_crossed_ema9=true",
                "setup_candle_bullish=true",
                "setup_candle_closed_above_ema9=true",
                f"entry_trigger={trigger:.8f}",
                f"initial_stop={stop:.8f}",
                f"risk_pct={(risk / trigger if trigger > 0 else 0.0):.6f}",
            ]
        )

        if risk <= 0:
            account.setup_status = "CANCELLED"
            account.setup_cancel_reason = "The setup candle produced an invalid stop distance."
            account.last_setup_event = "SETUP_CANCELLED"
            account.last_setup_event_reason = account.setup_cancel_reason
            reasons.append("cancelled_invalid_risk")
            return StrategyDecision(
                "CANCELLED",
                "NOT_USED",
                "HOLD",
                0,
                "; ".join(reasons),
                setup_status="CANCELLED",
            )

        account.setup_status = "ARMED"
        account.setup_candle_timestamp = now
        account.setup_candle_high = setup_high
        account.setup_candle_low = setup_low
        account.entry_trigger_price = trigger
        account.initial_setup_stop_price = stop
        account.setup_target_price = None
        account.setup_cancel_reason = None
        account.last_setup_event = "SETUP_ARMED"
        account.last_setup_event_reason = (
            "EMA 9 turned strictly upward on a candle crossing the average. "
            "Waiting for price to break that candle high."
        )
        reasons.append("setup_armed_waiting_for_breakout")
        return StrategyDecision(
            "ARMED",
            "NOT_USED",
            "HOLD",
            1,
            "; ".join(reasons),
            execution_reference_price=trigger,
            setup_status="ARMED",
            stop_loss_override=stop,
            take_profit_override=None,
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

