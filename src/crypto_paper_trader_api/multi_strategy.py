from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

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


def _ema(row: pd.Series, period: int) -> float:
    return float(row[f"ema_{period}"])


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

        reasons = [
            f"profile={active_profile.code}",
            f"ema_periods={active_profile.fast_ema_period}/{active_profile.slow_ema_period}/{active_profile.regime_ema_period}",
            f"technical_confirmations={confirmations}/8",
            f"bearish_confirmations={bearish_count}/4",
            f"model_probability_up={prediction.upward_probability:.4f}",
            f"expected_return={prediction.expected_return:.6f}",
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
        atr = float(current_row["atr_14"])
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
        }
        confirmations = sum(checks.values())
        reasons = [
            f"profile={profile.code}",
            f"ema_periods={profile.fast_ema_period}/{profile.slow_ema_period}/{profile.regime_ema_period}",
            f"crossed_up={crossed_up}",
            f"crossed_down={crossed_down}",
            f"confirmations={confirmations}/7",
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
            # A pending 9.1 entry is valid only while EMA 9 is still clearly rising.
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
        reversal_detected = strict_reversal and candle_crossed_ema9
        if not reversal_detected:
            if account.setup_status not in {"CANCELLED", "MISSED_ENTRY", "REJECTED"}:
                account.setup_status = "IDLE"
            account.last_setup_event = "WAITING_FOR_REVERSAL"
            if strict_reversal and not candle_crossed_ema9:
                account.last_setup_event_reason = (
                    "EMA 9 turned up, but the reversal candle did not cross the average."
                )
                reasons.append("strict_reversal_without_ema9_cross")
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
