from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from .config import Settings
from .execution_costs import ExecutionCosts
from .ml_model import ModelPrediction
from .models import Experiment


@dataclass(frozen=True)
class StrategyDecision:
    technical_signal: str
    final_signal: str
    technical_confirmations: int
    reason: str
    execution_reference_price: float | None = None


class HybridPaperStrategy:
    """Legacy single-portfolio hybrid strategy with signal-first decisions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        experiment: Experiment,
        execution_row: pd.Series,
        trend_row: pd.Series,
        prediction: ModelPrediction,
        costs: ExecutionCosts,
        now: datetime,
    ) -> StrategyDecision:
        close = float(execution_row["close"])
        high = float(execution_row["high"])
        low = float(execution_row["low"])
        atr = float(execution_row["atr_14"])

        bullish_checks = {
            "price_above_ema_200": close > float(execution_row["ema_200"]),
            "ema_20_above_ema_50": float(execution_row["ema_20"]) > float(execution_row["ema_50"]),
            "trend_price_above_ema_200": float(trend_row["close"]) > float(trend_row["ema_200"]),
            "trend_ema_20_above_ema_50": float(trend_row["ema_20"]) > float(trend_row["ema_50"]),
            "rsi_in_buy_zone": 48 <= float(execution_row["rsi_14"]) <= 68,
            "adx_has_trend": float(execution_row["adx_14"]) >= 18,
            "volume_confirmed": float(execution_row["relative_volume"]) >= 0.90,
            "trend_adx_has_strength": float(trend_row["adx_14"]) >= 16,
        }
        confirmations = sum(bullish_checks.values())
        technical_signal = (
            "BUY" if confirmations >= self.settings.min_technical_confirmations else "HOLD"
        )

        bearish_checks = {
            "ema_20_below_ema_50": float(execution_row["ema_20"]) < float(execution_row["ema_50"]),
            "price_below_ema_200": close < float(execution_row["ema_200"]),
            "trend_is_bearish": float(trend_row["ema_20"]) < float(trend_row["ema_50"]),
            "rsi_is_weak": float(execution_row["rsi_14"]) < 45,
        }
        bearish_count = sum(bearish_checks.values())
        if bearish_count >= 3:
            technical_signal = "SELL"

        cooldown_active = bool(
            experiment.cooldown_until
            and self._as_utc(experiment.cooldown_until) > self._as_utc(now)
        )
        daily_loss_limit_hit = experiment.current_equity <= experiment.initial_capital * (
            1 - self.settings.max_daily_loss_pct
        )

        reasons = [
            f"technical_confirmations={confirmations}/8",
            f"bearish_confirmations={bearish_count}/4",
            f"model_probability_up={prediction.upward_probability:.4f}",
            f"expected_return={prediction.expected_return:.6f}",
            f"taker_fee_per_side={costs.taker_fee_rate:.6f}",
            f"spread_rate={costs.spread_rate:.6f}",
            f"slippage_per_side={costs.slippage_rate:.6f}",
            "fees_are_accounting_only=true",
        ]

        if experiment.has_open_position:
            protective_levels = [
                value
                for value in [experiment.stop_loss_price, experiment.trailing_stop_price]
                if value is not None
            ]
            protective_stop = max(protective_levels) if protective_levels else None
            # Conservative OHLC rule: if stop and target are both touched in one candle, stop wins.
            if protective_stop is not None and low <= protective_stop:
                reasons.append(f"protective_stop_triggered={protective_stop:.8f}")
                return StrategyDecision(
                    technical_signal, "SELL", confirmations, "; ".join(reasons), protective_stop
                )

            if experiment.take_profit_price is not None and high >= experiment.take_profit_price:
                reasons.append(f"take_profit_triggered={experiment.take_profit_price:.8f}")
                return StrategyDecision(
                    technical_signal,
                    "SELL",
                    confirmations,
                    "; ".join(reasons),
                    experiment.take_profit_price,
                )

            if experiment.entry_time:
                holding_hours = (
                    self._as_utc(now) - self._as_utc(experiment.entry_time)
                ).total_seconds() / 3600
                if holding_hours >= self.settings.max_holding_hours:
                    reasons.append(f"time_stop_triggered_after_hours={holding_hours:.2f}")
                    return StrategyDecision(
                        technical_signal, "SELL", confirmations, "; ".join(reasons), close
                    )

            if daily_loss_limit_hit:
                reasons.append("daily_loss_limit_triggered")
                return StrategyDecision(
                    technical_signal, "SELL", confirmations, "; ".join(reasons), close
                )

            if prediction.model_signal == "SELL" and bearish_count >= 2:
                reasons.append("model_and_bearish_technical_exit")
                return StrategyDecision(
                    technical_signal, "SELL", confirmations, "; ".join(reasons), close
                )

            if bearish_count >= 3:
                reasons.append("technical_trend_exit")
                return StrategyDecision(
                    technical_signal, "SELL", confirmations, "; ".join(reasons), close
                )

            reasons.append("open_position_maintained")
            return StrategyDecision(technical_signal, "HOLD", confirmations, "; ".join(reasons))

        if daily_loss_limit_hit:
            reasons.append("new_entries_blocked_by_daily_loss_limit")
            return StrategyDecision(technical_signal, "HOLD", confirmations, "; ".join(reasons))
        if cooldown_active:
            reasons.append(f"cooldown_active_until={experiment.cooldown_until}")
            return StrategyDecision(technical_signal, "HOLD", confirmations, "; ".join(reasons))
        if experiment.consecutive_losses >= self.settings.max_consecutive_losses:
            reasons.append("new_entries_blocked_by_consecutive_losses")
            return StrategyDecision(technical_signal, "HOLD", confirmations, "; ".join(reasons))

        buy_authorized = all(
            [
                technical_signal == "BUY",
                prediction.model_signal == "BUY",
                atr > 0,
            ]
        )
        if buy_authorized:
            reasons.append("technical_model_and_risk_filters_approved")
            return StrategyDecision(
                technical_signal, "BUY", confirmations, "; ".join(reasons), close
            )

        reasons.append("entry_filters_not_all_satisfied")
        return StrategyDecision(technical_signal, "HOLD", confirmations, "; ".join(reasons))

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
