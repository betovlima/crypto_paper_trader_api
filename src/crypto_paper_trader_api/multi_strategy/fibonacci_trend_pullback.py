from __future__ import annotations

from .common import *  # noqa: F403
from ..risk_management.fibonacci import (
    bullish_extension_price,
    bullish_retracement_price,
    calculate_bullish_fibonacci_stop,
    detect_latest_bullish_impulse,
)


class FibonacciTrendPullbackStrategy:
    """Trend-following pullback strategy with causal Fibonacci risk levels.

    The strategy is independent from the existing EMA pullback implementation.
    It requires a confirmed bullish EMA structure, a causal impulse of at least the
    configured ATR size, a retracement into the 38.2%-61.8% zone and a bullish
    closed-candle recovery above EMA 9. The initial stop sits below 78.6% with an
    ATR buffer. Once in position, a 50% Fibonacci structural stop can only rise.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        account: StrategyAccount,
        history: pd.DataFrame,
        current_index: int,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> StrategyDecision:
        current_row = history.iloc[current_index]
        previous_row = history.iloc[max(current_index - 1, 0)]
        close = float(current_row["close"])
        open_price = float(current_row["open"])
        high = float(current_row["high"])
        low = float(current_row["low"])
        atr = max(float(current_row["atr_14"]), 1e-12)
        ema9 = float(current_row["ema_9"])
        ema21 = float(current_row["ema_21"])
        ema50 = float(current_row["ema_50"])
        previous_ema21 = float(previous_row["ema_21"])
        trend_ema21 = float(trend_row["ema_21"])
        trend_ema50 = float(trend_row["ema_50"])
        trend_close = float(trend_row["close"])

        impulse = detect_latest_bullish_impulse(
            history,
            current_index=current_index,
            pivot_bars=self.settings.fibonacci_pivot_bars,
            lookback_bars=self.settings.fibonacci_impulse_lookback_bars,
            min_impulse_atr=self.settings.fibonacci_min_impulse_atr,
        )

        reasons = [
            f"profile={profile.code}",
            "strategy=FIBONACCI_TREND_PULLBACK",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]
        if impulse is None:
            reasons.append("no_confirmed_bullish_impulse")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", 0, "; ".join(reasons)
            )

        entry_min = min(
            self.settings.fibonacci_pullback_entry_min,
            self.settings.fibonacci_pullback_entry_max,
        )
        entry_max = max(
            self.settings.fibonacci_pullback_entry_min,
            self.settings.fibonacci_pullback_entry_max,
        )
        zone_upper = bullish_retracement_price(
            impulse.low_price, impulse.high_price, entry_min
        )
        zone_lower = bullish_retracement_price(
            impulse.low_price, impulse.high_price, entry_max
        )
        touched_zone = low <= zone_upper and high >= zone_lower
        closed_above_deep_zone = close > zone_lower
        bullish_recovery = (
            _bullish_confirmation(current_row, atr, self.settings.entry_min_body_atr)
            and close > ema9
            and close >= float(previous_row["close"])
        )
        execution_trend = ema21 > ema50 and ema21 > previous_ema21
        trend_context = trend_ema21 > trend_ema50 and trend_close > trend_ema50
        adx_ok = float(current_row["adx_14"]) >= profile.adx_min
        volume_ok = float(current_row["relative_volume"]) >= profile.relative_volume_min
        rsi = float(current_row["rsi_14"])
        rsi_ok = profile.rsi_buy_min <= rsi <= min(profile.rsi_buy_max, 72.0)
        context_ok = _context_entry_allowed(current_row, self.settings)
        impulse_completed_before_current = impulse.high_index < current_index

        stop_result = calculate_bullish_fibonacci_stop(
            history,
            current_price=close,
            current_index=current_index,
            retracement_ratio=self.settings.fibonacci_pullback_initial_stop_level,
            buffer_atr_multiplier=self.settings.fibonacci_stop_buffer_atr,
            pivot_bars=self.settings.fibonacci_pivot_bars,
            lookback_bars=self.settings.fibonacci_impulse_lookback_bars,
            min_impulse_atr=self.settings.fibonacci_min_impulse_atr,
            max_stop_distance_atr=self.settings.fibonacci_max_stop_distance_atr,
        )
        stop_valid = stop_result is not None

        checks = {
            "execution_trend": execution_trend,
            "trend_context": trend_context,
            "impulse_completed_before_current": impulse_completed_before_current,
            "retracement_zone_touched": touched_zone,
            "closed_above_deep_zone": closed_above_deep_zone,
            "bullish_recovery": bullish_recovery,
            "adx_confirmed": adx_ok,
            "volume_confirmed": volume_ok,
            "rsi_confirmed": rsi_ok,
            "context_not_exhausted": context_ok,
            "fibonacci_stop_valid": stop_valid,
        }
        confirmations = sum(checks.values())
        reasons.extend(
            [
                f"impulse_low={impulse.low_price:.8f}",
                f"impulse_high={impulse.high_price:.8f}",
                f"impulse_size_atr={impulse.size_atr:.6f}",
                f"fib_entry_zone={zone_lower:.8f}-{zone_upper:.8f}",
                f"retracement_zone_touched={str(touched_zone).lower()}",
                f"bullish_recovery={str(bullish_recovery).lower()}",
                f"execution_trend={str(execution_trend).lower()}",
                f"trend_context={str(trend_context).lower()}",
                f"confirmations={confirmations}/{len(checks)}",
            ]
        )

        if account.has_open_position:
            if close < ema50 or not trend_context:
                reasons.append("fibonacci_trend_invalidated")
                return StrategyDecision(
                    "SELL", "NOT_USED", "SELL", confirmations, "; ".join(reasons), close
                )

            trailing = calculate_bullish_fibonacci_stop(
                history,
                current_price=close,
                current_index=current_index,
                retracement_ratio=self.settings.fibonacci_pullback_trailing_stop_level,
                buffer_atr_multiplier=self.settings.fibonacci_stop_buffer_atr,
                pivot_bars=self.settings.fibonacci_pivot_bars,
                lookback_bars=self.settings.fibonacci_impulse_lookback_bars,
                min_impulse_atr=self.settings.fibonacci_min_impulse_atr,
            )
            active_stop = max(
                float(account.stop_loss_price or 0.0),
                float(account.trailing_stop_price or 0.0),
            )
            if trailing is not None and active_stop < trailing.stop_price < close:
                account.trailing_stop_price = trailing.stop_price
                account.last_setup_event = "FIBONACCI_TRAILING_STOP_RAISED"
                account.last_setup_event_reason = (
                    "The Fibonacci trend-pullback stop was raised to the protected "
                    "retracement level of the latest confirmed impulse."
                )
                reasons.extend(
                    [
                        f"fibonacci_trailing_ratio={trailing.retracement_ratio:.3f}",
                        f"fibonacci_trailing_level={trailing.retracement_price:.8f}",
                        f"fibonacci_trailing_stop_raised={trailing.stop_price:.8f}",
                    ]
                )
            else:
                reasons.append(f"fibonacci_trailing_stop_unchanged={active_stop:.8f}")
            reasons.append("fibonacci_trend_position_maintained")
            return StrategyDecision(
                "HOLD",
                "NOT_USED",
                "HOLD",
                confirmations,
                "; ".join(reasons),
                stop_loss_override=max(
                    float(account.stop_loss_price or 0.0),
                    float(account.trailing_stop_price or 0.0),
                ),
            )

        if not all(checks.values()) or stop_result is None:
            reasons.append("fibonacci_pullback_filters_not_all_satisfied")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", confirmations, "; ".join(reasons)
            )

        stop = stop_result.stop_price
        risk = close - stop
        extension_target = bullish_extension_price(
            impulse.low_price,
            impulse.high_price,
            self.settings.fibonacci_pullback_extension_target,
        )
        risk_target = close + self.settings.fibonacci_pullback_reward_risk_ratio * risk
        target = max(impulse.high_price, risk_target, extension_target)
        reward_risk = (target - close) / max(risk, 1e-12)
        potential_return = (target - close) / max(close, 1e-12)
        reasons.extend(
            [
                "fibonacci_pullback_entry_approved",
                f"fibonacci_initial_stop_ratio={stop_result.retracement_ratio:.3f}",
                f"fibonacci_initial_level={stop_result.retracement_price:.8f}",
                f"fibonacci_atr_buffer={stop_result.atr_buffer:.8f}",
                f"fibonacci_initial_stop={stop:.8f}",
                f"fibonacci_extension_target={extension_target:.8f}",
                f"reward_risk_ratio={reward_risk:.6f}",
            ]
        )
        return StrategyDecision(
            "BUY",
            "NOT_USED",
            "BUY",
            confirmations,
            "; ".join(reasons),
            close,
            potential_target_price=target,
            potential_gross_return=potential_return,
            reward_risk_ratio=reward_risk,
            stop_loss_override=stop,
            take_profit_override=target,
        )
