from __future__ import annotations

from .common import *  # noqa: F403

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
