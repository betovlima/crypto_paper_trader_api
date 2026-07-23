from __future__ import annotations

from .common import *  # noqa: F403

class Lbr310AntiContextStrategy:
    """Long-only 3/10 Anti pullback with a fixed UTC crypto-session baseline.

    The oscillator follows Linda Bradford Raschke's documented construction:
    SMA(3) - SMA(10), with a 16-period SMA signal line. The fixed UTC day is an
    application adaptation for a market without an official opening or closing bell.
    """

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

    @staticmethod
    def _period_return(window: pd.DataFrame) -> float | None:
        if window.empty:
            return None
        first_open = float(window.iloc[0]["open"])
        last_close = float(window.iloc[-1]["close"])
        if first_open <= 0:
            return None
        return last_close / first_open - 1.0

    def _utc_baseline(self, history: pd.DataFrame, timestamp: datetime) -> dict[str, float | int | bool | None]:
        timestamps = pd.to_datetime(history["timestamp"], utc=True)
        current_day_start = pd.Timestamp(timestamp).floor("D")
        previous_day_start = current_day_start - pd.Timedelta(hours=24)
        previous_last_hour_start = current_day_start - pd.Timedelta(hours=1)
        current_first_hour_end = current_day_start + pd.Timedelta(hours=1)

        previous_day = history.loc[
            (timestamps >= previous_day_start) & (timestamps < current_day_start)
        ]
        previous_last_hour = history.loc[
            (timestamps >= previous_last_hour_start) & (timestamps < current_day_start)
        ]
        first_hour_complete = pd.Timestamp(timestamp) >= current_first_hour_end
        current_first_hour = history.loc[
            (timestamps >= current_day_start) & (timestamps < current_first_hour_end)
        ] if first_hour_complete else history.iloc[0:0]

        previous_return = self._period_return(previous_day)
        closing_hour_return = self._period_return(previous_last_hour)
        opening_hour_return = self._period_return(current_first_hour)

        directional_values = [previous_return, closing_hour_return]
        if opening_hour_return is not None:
            directional_values.append(opening_hour_return)
        score = sum(1 if value > 0 else -1 if value < 0 else 0 for value in directional_values if value is not None)

        previous_range = None
        previous_close_location = None
        if not previous_day.empty:
            previous_high = float(previous_day["high"].max())
            previous_low = float(previous_day["low"].min())
            previous_range = max(previous_high - previous_low, 0.0)
            if previous_range > 0:
                previous_close_location = (
                    float(previous_day.iloc[-1]["close"]) - previous_low
                ) / previous_range

        available = previous_return is not None and closing_hour_return is not None
        aligned = not available or score >= 0
        return {
            "available": available,
            "aligned": aligned,
            "score": score,
            "previous_return": previous_return,
            "closing_hour_return": closing_hour_return,
            "opening_hour_return": opening_hour_return,
            "previous_range": previous_range,
            "previous_close_location": previous_close_location,
            "first_hour_complete": first_hour_complete,
        }

    def _find_pullback_setup(
        self,
        history: pd.DataFrame,
        current_index: int,
        atr: float,
    ) -> dict[str, float | int] | None:
        settings = self.settings
        current = history.iloc[current_index]
        previous = history.iloc[current_index - 1]
        previous_previous = history.iloc[current_index - 2]

        fast = float(current["lbr_310_fast"])
        slow = float(current["lbr_310_slow"])
        previous_fast = float(previous["lbr_310_fast"])
        previous_slow = float(previous["lbr_310_slow"])
        previous_previous_slow = float(previous_previous["lbr_310_slow"])

        hook_up = (
            float(previous_previous["lbr_310_fast"]) > previous_fast
            and fast > previous_fast
        )
        slow_rising = slow > previous_slow >= previous_previous_slow
        signal_confirmed = (
            fast > slow and previous_fast <= previous_slow
            if settings.lbr_anti_require_signal_cross
            else fast > previous_fast and slow_rising
        )
        if not (hook_up and slow_rising and signal_confirmed):
            return None

        for pullback_bars in range(
            settings.lbr_anti_pullback_min_bars,
            settings.lbr_anti_pullback_max_bars + 1,
        ):
            pullback_start = current_index - pullback_bars
            impulse_end = pullback_start - 1
            impulse_start = impulse_end - settings.lbr_anti_impulse_lookback + 1
            if impulse_start < 0 or impulse_end <= impulse_start:
                continue

            impulse = history.iloc[impulse_start : impulse_end + 1]
            pullback = history.iloc[pullback_start:current_index]
            if impulse.empty or pullback.empty:
                continue

            impulse_start_price = float(impulse.iloc[0]["open"])
            impulse_end_price = float(impulse.iloc[-1]["close"])
            impulse_advance = impulse_end_price - impulse_start_price
            if impulse_advance < settings.lbr_anti_min_impulse_atr * atr:
                continue

            pullback_low = float(pullback["low"].min())
            pullback_depth = max(impulse_end_price - pullback_low, 0.0)
            pullback_strength = pullback_depth / max(impulse_advance, 1e-12)
            if pullback_strength > settings.lbr_anti_max_pullback_strength:
                continue

            impulse_average_range = float((impulse["high"] - impulse["low"]).mean())
            pullback_average_range = float((pullback["high"] - pullback["low"]).mean())
            pullback_range_ratio = pullback_average_range / max(impulse_average_range, 1e-12)
            if pullback_range_ratio > settings.lbr_anti_max_pullback_range_ratio:
                continue

            impulse_volume = float(impulse["volume"].mean())
            pullback_volume = float(pullback["volume"].mean())
            pullback_volume_ratio = pullback_volume / max(impulse_volume, 1e-12)

            return {
                "pullback_bars": pullback_bars,
                "impulse_advance": impulse_advance,
                "pullback_low": pullback_low,
                "pullback_strength": pullback_strength,
                "pullback_range_ratio": pullback_range_ratio,
                "pullback_volume_ratio": pullback_volume_ratio,
            }
        return None

    def decide(
        self,
        account: StrategyAccount,
        history: pd.DataFrame,
        current_index: int,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        profile: TradingProfile,
    ) -> StrategyDecision:
        if current_index < 30:
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", 0,
                "lbr_anti_waiting_for_sufficient_history",
                setup_status="WAITING",
            )

        current = history.iloc[current_index]
        previous = history.iloc[current_index - 1]
        timestamp = self._timestamp(current)
        close = float(current["close"])
        high = float(current["high"])
        low = float(current["low"])
        atr = max(float(current["atr_14"]), 1e-12)
        fast = float(current["lbr_310_fast"])
        slow = float(current["lbr_310_slow"])
        previous_fast = float(previous["lbr_310_fast"])
        previous_slow = float(previous["lbr_310_slow"])
        fast_slope = fast - previous_fast
        slow_slope = slow - previous_slow
        baseline = self._utc_baseline(history.iloc[: current_index + 1], timestamp)
        baseline_allowed = (
            not self.settings.lbr_anti_require_utc_baseline_alignment
            or not bool(baseline["available"])
            or bool(baseline["aligned"])
        )
        ignition, exhaustion, compression = _market_context_values(current)
        trend_bullish = (
            float(trend_row["close"]) > _ema(trend_row, profile.regime_ema_period)
            and _ema(trend_row, profile.fast_ema_period) > _ema(trend_row, profile.slow_ema_period)
        )
        extension_ok = float(current.get("extension_ema20_atr", 0.0) or 0.0) <= self.settings.entry_max_extension_atr
        context_allowed = _context_entry_allowed(current, self.settings)

        reasons = [
            "strategy=lbr_310_anti_context",
            f"lbr_fast={fast:.8f}",
            f"lbr_slow={slow:.8f}",
            f"lbr_fast_slope={fast_slope:.8f}",
            f"lbr_slow_slope={slow_slope:.8f}",
            f"utc_baseline_score={int(baseline['score'])}",
            f"utc_baseline_available={bool(baseline['available'])}",
            f"utc_baseline_aligned={baseline_allowed}",
            f"previous_24h_return={baseline['previous_return']}",
            f"previous_closing_hour_return={baseline['closing_hour_return']}",
            f"current_opening_hour_return={baseline['opening_hour_return']}",
            f"ignition_score={ignition:.6f}",
            f"exhaustion_score={exhaustion:.6f}",
            f"compression_score={compression:.6f}",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
        ]

        if account.has_open_position:
            account.setup_status = "IN_POSITION"
            oscillator_exit = fast < slow and fast_slope < 0 and slow_slope <= 0
            trend_failed = close < _ema(current, profile.fast_ema_period) and not trend_bullish
            if oscillator_exit or trend_failed:
                reasons.extend([
                    f"oscillator_exit={oscillator_exit}",
                    f"trend_failed={trend_failed}",
                ])
                return StrategyDecision(
                    "SELL", "NOT_USED", "SELL", 2,
                    "; ".join(reasons), close, setup_status="IN_POSITION",
                )
            reasons.append("lbr_anti_position_maintained")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", 2,
                "; ".join(reasons), setup_status="IN_POSITION",
            )

        if account.setup_status == "ARMED" and account.entry_trigger_price is not None:
            setup_time = account.setup_candle_timestamp
            setup_age = 0
            if setup_time is not None:
                setup_timestamp = pd.Timestamp(setup_time)
                if setup_timestamp.tzinfo is None:
                    setup_timestamp = setup_timestamp.tz_localize("UTC")
                else:
                    setup_timestamp = setup_timestamp.tz_convert("UTC")
                history_times = pd.to_datetime(history.iloc[: current_index + 1]["timestamp"], utc=True)
                setup_age = int((history_times > setup_timestamp).sum())

            cancel_reasons = []
            if setup_age > self.settings.lbr_anti_setup_max_age_bars:
                cancel_reasons.append("setup_expired")
            if slow_slope <= 0:
                cancel_reasons.append("slow_line_lost_upward_slope")
            if not baseline_allowed:
                cancel_reasons.append("utc_baseline_turned_bearish")
            if account.setup_candle_low is not None and close < float(account.setup_candle_low):
                cancel_reasons.append("pullback_structure_broken")
            if exhaustion > self.settings.exhaustion_max_entry_score:
                cancel_reasons.append("market_context_exhausted")

            if cancel_reasons:
                self._clear_setup(account, ",".join(cancel_reasons))
                account.last_setup_event = "SETUP_CANCELLED"
                account.last_setup_event_reason = ", ".join(cancel_reasons)
                reasons.extend(cancel_reasons)
                return StrategyDecision(
                    "HOLD", "NOT_USED", "HOLD", 0,
                    "; ".join(reasons), setup_status="CANCELLED",
                )

            trigger = float(account.entry_trigger_price)
            setup_time = account.setup_candle_timestamp
            different_candle = setup_time is None or timestamp > setup_time
            breakout_buffer = atr * self.settings.breakout_close_buffer_atr
            breakout_confirmed = (
                different_candle
                and high >= trigger
                and close >= trigger + breakout_buffer
                and _bullish_confirmation(current, atr, self.settings.entry_min_body_atr)
                and context_allowed
                and extension_ok
                and baseline_allowed
                and trend_bullish
            )
            if breakout_confirmed:
                stop = float(account.initial_setup_stop_price or (low - atr * self.settings.lbr_anti_stop_atr_buffer))
                risk = max(trigger - stop, atr * 0.05, 1e-12)
                target = trigger + self.settings.lbr_anti_reward_risk_ratio * risk
                account.setup_status = "TRIGGERED"
                account.setup_target_price = target
                account.last_setup_event = "BREAKOUT_ENTRY"
                account.last_setup_event_reason = "A later closed candle confirmed the 3/10 Anti setup high."
                reasons.extend([
                    f"entry_trigger={trigger:.8f}",
                    f"setup_age_bars={setup_age}",
                    "closed_candle_breakout=true",
                ])
                return StrategyDecision(
                    "BUY", "NOT_USED", "BUY", 6,
                    "; ".join(reasons), trigger,
                    setup_status="TRIGGERED",
                    potential_target_price=target,
                    potential_gross_return=(target - trigger) / max(trigger, 1e-12),
                    reward_risk_ratio=self.settings.lbr_anti_reward_risk_ratio,
                    stop_loss_override=stop,
                    take_profit_override=target,
                )

            reasons.extend([
                f"setup_age_bars={setup_age}",
                "waiting_for_later_closed_candle_above_setup_high",
            ])
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", 4,
                "; ".join(reasons), trigger,
                setup_status="ARMED",
                potential_target_price=account.setup_target_price,
                reward_risk_ratio=self.settings.lbr_anti_reward_risk_ratio,
                stop_loss_override=account.initial_setup_stop_price,
                take_profit_override=account.setup_target_price,
            )

        setup = self._find_pullback_setup(history, current_index, atr)
        bullish_candle = _bullish_confirmation(current, atr, self.settings.entry_min_body_atr)
        checks = {
            "pullback_hook": setup is not None,
            "bullish_candle": bullish_candle,
            "trend_bullish": trend_bullish,
            "utc_baseline_aligned": baseline_allowed,
            "context_allowed": context_allowed,
            "extension_allowed": extension_ok,
        }
        confirmations = sum(checks.values())
        if setup is not None:
            reasons.extend([
                f"pullback_bars={int(setup['pullback_bars'])}",
                f"impulse_advance={float(setup['impulse_advance']):.8f}",
                f"pullback_strength={float(setup['pullback_strength']):.6f}",
                f"pullback_range_ratio={float(setup['pullback_range_ratio']):.6f}",
                f"pullback_volume_ratio={float(setup['pullback_volume_ratio']):.6f}",
            ])

        if all(checks.values()) and setup is not None:
            tick_buffer = max(close * self.settings.ema9_entry_tick_rate, atr * self.settings.breakout_close_buffer_atr)
            trigger = high + tick_buffer
            pullback_low = float(setup["pullback_low"])
            stop = pullback_low - atr * self.settings.lbr_anti_stop_atr_buffer
            risk = max(trigger - stop, atr * 0.05, 1e-12)
            target = trigger + self.settings.lbr_anti_reward_risk_ratio * risk
            account.setup_status = "ARMED"
            account.setup_candle_timestamp = timestamp
            account.setup_candle_high = high
            account.setup_candle_low = pullback_low
            account.entry_trigger_price = trigger
            account.initial_setup_stop_price = stop
            account.setup_target_price = target
            account.setup_cancel_reason = None
            account.last_setup_event = "LBR_ANTI_SETUP_ARMED"
            account.last_setup_event_reason = "Weak pullback and bullish 3/10 momentum hook confirmed."
            reasons.append("lbr_310_anti_setup_armed")
            return StrategyDecision(
                "HOLD", "NOT_USED", "HOLD", confirmations,
                "; ".join(reasons), trigger,
                setup_status="ARMED",
                potential_target_price=target,
                potential_gross_return=(target - trigger) / max(trigger, 1e-12),
                reward_risk_ratio=self.settings.lbr_anti_reward_risk_ratio,
                stop_loss_override=stop,
                take_profit_override=target,
            )

        reasons.append("waiting_for_lbr_310_anti_pullback_and_context")
        return StrategyDecision(
            "HOLD", "NOT_USED", "HOLD", confirmations,
            "; ".join(reasons), setup_status="WAITING",
        )
