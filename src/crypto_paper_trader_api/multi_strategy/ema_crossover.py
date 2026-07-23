from __future__ import annotations

from .common import *  # noqa: F403

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
