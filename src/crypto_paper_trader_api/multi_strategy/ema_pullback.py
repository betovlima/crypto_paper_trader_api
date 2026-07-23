from __future__ import annotations

from .common import *  # noqa: F403

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
