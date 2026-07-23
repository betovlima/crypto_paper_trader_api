from __future__ import annotations

from .common import *  # noqa: F403

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
