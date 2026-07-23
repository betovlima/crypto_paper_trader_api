from __future__ import annotations

from .common import *  # noqa: F403

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
