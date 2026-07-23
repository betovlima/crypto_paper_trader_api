from __future__ import annotations

from .common import *  # noqa: F403

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
