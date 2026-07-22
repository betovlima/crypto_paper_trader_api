from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.cluster import MiniBatchKMeans
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from .config import Settings
from .execution_costs import ExecutionCosts
from .models import StrategyAccount
from .multi_strategy import StrategyDecision
from .trading_profiles import TradingProfile


AI_PATTERN_MODEL_VERSION = "AI-PATTERN-v4-MARKET-CONTEXT"


@dataclass(frozen=True)
class PatternDataset:
    frame: pd.DataFrame
    feature_columns: list[str]


class AIPatternTrader:
    """Autonomous paper strategy that learns recurring OHLCV patterns.

    The model does not select one of the handcrafted strategies. It builds a
    supervised pattern memory directly from the candle sequence available at the
    current point in time. Historical windows are labelled with their future
    return, while the current window is evaluated by an Extra Trees ensemble,
    nearest-neighbour pattern memory and unsupervised clustering.

    The implementation is intentionally deterministic and auditable. It is a
    paper-only model and every decision is still subject to the portfolio risk
    governor implemented here and the broker's protective stops.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def decide(
        self,
        account: StrategyAccount,
        frame: pd.DataFrame,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        now: datetime,
        profile: TradingProfile,
    ) -> StrategyDecision:
        dataset = self._build_dataset(frame, self.settings.ai_pattern_horizon_candles)
        data = dataset.frame
        current = data.iloc[-1]
        regime = self._detect_regime(data, trend_row)
        mode = self.settings.ai_pattern_mode

        account.ai_mode = mode
        account.ai_regime = regime
        account.ai_model_version = AI_PATTERN_MODEL_VERSION
        account.ai_last_prediction_at = self._as_utc(now)
        account.stop_management_mode = "AI_DYNAMIC"

        training = data.dropna(
            subset=[*dataset.feature_columns, "future_gross_return", "future_adverse_return"]
        ).copy()
        minimum_rows = self.settings.ai_pattern_min_training_rows
        if len(training) < minimum_rows or current[dataset.feature_columns].isna().any():
            reason = (
                f"ai_mode={mode}; model_version={AI_PATTERN_MODEL_VERSION}; regime={regime}; "
                f"training_rows={len(training)}; required_training_rows={minimum_rows}; "
                "risk_status=LEARNING; autonomous_action=HOLD; "
                "reason=not_enough_chronological_pattern_samples"
            )
            self._update_account_diagnostics(
                account=account,
                cluster=None,
                confidence=0.0,
                upward_probability=None,
                expected_net_return=None,
                similar_patterns=0,
                risk_status="LEARNING",
                risk_reason="Not enough chronological pattern samples are available yet.",
            )
            return StrategyDecision(
                technical_signal="HOLD",
                model_signal="LEARNING",
                final_signal="HOLD",
                technical_confirmations=0,
                reason=reason,
                ai_mode=mode,
                ai_proposed_action="HOLD",
                ai_regime=regime,
                ai_pattern_cluster=None,
                ai_confidence=0.0,
                ai_upward_probability=None,
                ai_neighbor_count=0,
                ai_positive_neighbor_rate=None,
                ai_expected_gross_return=None,
                ai_expected_net_return=None,
                ai_worst_adverse_return=None,
                ai_model_version=AI_PATTERN_MODEL_VERSION,
                ai_training_samples=len(training),
                ai_validation_accuracy=None,
                ai_validation_mae=None,
                ai_risk_status="LEARNING",
                ai_risk_reason="Not enough chronological pattern samples are available yet.",
                ai_horizon_candles=self.settings.ai_pattern_horizon_candles,
                ai_feature_summary=self._feature_summary(current, dataset.feature_columns),
            )

        if len(training) > self.settings.ai_pattern_training_max_rows:
            training = training.tail(self.settings.ai_pattern_training_max_rows).copy()

        training, selected_window, validation_accuracy, validation_mae = (
            self._select_adaptive_training_window(training, dataset.feature_columns)
        )
        x = training[dataset.feature_columns].astype(float).to_numpy()
        y = training["future_gross_return"].astype(float).to_numpy()
        current_x = current[dataset.feature_columns].astype(float).to_numpy().reshape(1, -1)
        model = self._new_model()
        sample_weight = self._recency_weights(training)
        model.fit(x, y, sample_weight=sample_weight)
        tree_predictions = np.asarray(
            [float(tree.predict(current_x)[0]) for tree in model.estimators_], dtype=float
        )
        model_expected_gross = float(tree_predictions.mean())
        model_positive_probability = float(
            np.mean(tree_predictions > costs.estimated_round_trip_rate)
        )

        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(x)
        current_scaled = scaler.transform(current_x)
        neighbour_count = min(self.settings.ai_pattern_neighbors, len(training))
        neighbours = NearestNeighbors(n_neighbors=neighbour_count, metric="euclidean")
        neighbours.fit(x_scaled)
        _, indices = neighbours.kneighbors(current_scaled)
        neighbour_rows = training.iloc[indices[0]]
        neighbour_returns = neighbour_rows["future_gross_return"].astype(float).to_numpy()
        neighbour_adverse = neighbour_rows["future_adverse_return"].astype(float).to_numpy()
        neighbour_positive_rate = float(
            np.mean(neighbour_returns > costs.estimated_round_trip_rate)
        )
        neighbour_expected_gross = float(np.mean(neighbour_returns))
        worst_adverse_return = float(np.quantile(neighbour_adverse, 0.20))

        cluster = self._cluster_current_pattern(x_scaled, current_scaled)
        expected_gross_return = (
            0.62 * model_expected_gross + 0.38 * neighbour_expected_gross
        )
        expected_net_return = expected_gross_return - costs.estimated_round_trip_rate
        upward_probability = (
            0.62 * model_positive_probability + 0.38 * neighbour_positive_rate
        )
        confidence = self._confidence(
            upward_probability=upward_probability,
            neighbour_positive_rate=neighbour_positive_rate,
            validation_accuracy=validation_accuracy,
            sample_count=len(training),
        )

        proposed_action = self._proposed_action(
            account=account,
            regime=regime,
            upward_probability=upward_probability,
            expected_net_return=expected_net_return,
            confidence=confidence,
        )
        risk_status, risk_reason = self._risk_governor(
            account=account,
            proposed_action=proposed_action,
            regime=regime,
            upward_probability=upward_probability,
            expected_net_return=expected_net_return,
            confidence=confidence,
            costs=costs,
            now=now,
            profile=profile,
        )

        ignition_score = float(current.get("ignition_score", 0.0) or 0.0)
        exhaustion_score = float(current.get("exhaustion_score", 0.0) or 0.0)
        compression_ratio = float(current.get("compression_ratio", 1.0) or 1.0)
        if (
            proposed_action == "BUY"
            and exhaustion_score > self.settings.exhaustion_max_entry_score
        ):
            risk_status = "BLOCKED"
            risk_reason = (
                "The current candle context is classified as possible exhaustion "
                f"({exhaustion_score:.4f}), above the configured entry limit."
            )

        final_signal = proposed_action if risk_status == "APPROVED" else "HOLD"
        if mode == "OBSERVATION":
            final_signal = "HOLD"
            if risk_status == "APPROVED":
                risk_status = "OBSERVATION"
                risk_reason = "The model is in observation mode; the proposed action was not executed."

        stop_price = None
        target_price = None
        reward_risk_ratio = None
        if proposed_action == "BUY":
            stop_price, target_price, reward_risk_ratio = self._risk_levels(
                current=current,
                expected_gross_return=expected_gross_return,
                worst_adverse_return=worst_adverse_return,
                profile=profile,
            )

        confirmations = sum(
            [
                upward_probability >= self.settings.ai_pattern_buy_probability_threshold,
                expected_net_return >= self.settings.ai_pattern_min_expected_net_return,
                confidence >= self.settings.ai_pattern_min_confidence,
                regime not in {"TREND_DOWN", "HIGH_VOLATILITY"},
            ]
        )
        reason_parts = [
            f"ai_mode={mode}",
            f"model_version={AI_PATTERN_MODEL_VERSION}",
            f"regime={regime}",
            f"pattern_cluster={cluster}",
            f"training_rows={len(training)}",
            f"selected_training_window={selected_window}",
            f"similar_patterns={neighbour_count}",
            f"probability_up={upward_probability:.6f}",
            f"neighbour_positive_rate={neighbour_positive_rate:.6f}",
            f"expected_gross_return={expected_gross_return:.6f}",
            f"estimated_round_trip_cost={costs.estimated_round_trip_rate:.6f}",
            f"expected_net_return={expected_net_return:.6f}",
            f"confidence={confidence:.6f}",
            f"worst_similar_adverse_return={worst_adverse_return:.6f}",
            f"ignition_score={ignition_score:.6f}",
            f"exhaustion_score={exhaustion_score:.6f}",
            f"compression_ratio={compression_ratio:.6f}",
            f"proposed_action={proposed_action}",
            f"risk_status={risk_status}",
            f"risk_reason={risk_reason}",
            f"final_signal={final_signal}",
        ]

        self._update_account_diagnostics(
            account=account,
            cluster=cluster,
            confidence=confidence,
            upward_probability=upward_probability,
            expected_net_return=expected_net_return,
            similar_patterns=neighbour_count,
            risk_status=risk_status,
            risk_reason=risk_reason,
        )

        return StrategyDecision(
            technical_signal=proposed_action,
            model_signal=proposed_action,
            final_signal=final_signal,
            technical_confirmations=confirmations,
            reason="; ".join(reason_parts),
            execution_reference_price=(float(current["close"]) if final_signal != "HOLD" else None),
            potential_target_price=target_price,
            potential_gross_return=expected_gross_return,
            reward_risk_ratio=reward_risk_ratio,
            stop_loss_override=stop_price,
            take_profit_override=target_price,
            ai_mode=mode,
            ai_proposed_action=proposed_action,
            ai_regime=regime,
            ai_pattern_cluster=cluster,
            ai_confidence=confidence,
            ai_upward_probability=upward_probability,
            ai_neighbor_count=neighbour_count,
            ai_positive_neighbor_rate=neighbour_positive_rate,
            ai_expected_gross_return=expected_gross_return,
            ai_expected_net_return=expected_net_return,
            ai_worst_adverse_return=worst_adverse_return,
            ai_model_version=AI_PATTERN_MODEL_VERSION,
            ai_training_samples=len(training),
            ai_validation_accuracy=validation_accuracy,
            ai_validation_mae=validation_mae,
            ai_risk_status=risk_status,
            ai_risk_reason=risk_reason,
            ai_horizon_candles=self.settings.ai_pattern_horizon_candles,
            ai_feature_summary=self._feature_summary(current, dataset.feature_columns),
        )

    def _build_dataset(self, frame: pd.DataFrame, horizon: int) -> PatternDataset:
        data = frame.copy().sort_values("timestamp").reset_index(drop=True)
        close = data["close"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        open_ = data["open"].astype(float)
        volume = data["volume"].astype(float)
        safe_close = close.replace(0, np.nan)
        candle_range = (high - low).replace(0, np.nan)

        data["range_pct"] = (high - low) / safe_close
        data["close_location"] = (close - low) / candle_range
        data["open_gap_pct"] = (open_ - close.shift(1)) / close.shift(1).replace(0, np.nan)
        data["return_12"] = close.pct_change(12)
        data["return_24"] = close.pct_change(24)
        data["ema9_slope_pct"] = data["ema_9"].pct_change()
        data["ema20_slope_3"] = data["ema_20"].pct_change(3)
        data["ema50_slope_6"] = data["ema_50"].pct_change(6)
        data["atr_change_3"] = data["atr_14"].pct_change(3)
        data["volume_change_3"] = volume.pct_change(3)
        data["positive_ratio_8"] = (data["return_1"] > 0).rolling(8).mean()
        data["positive_ratio_20"] = (data["return_1"] > 0).rolling(20).mean()
        data["rolling_high_gap_20"] = close / high.rolling(20).max() - 1
        data["rolling_low_gap_20"] = close / low.rolling(20).min() - 1
        data["volatility_ratio"] = data["volatility_20"] / data["volatility_20"].rolling(60).median()
        volume_mean = volume.rolling(20).mean()
        volume_std = volume.rolling(20).std().replace(0, np.nan)
        data["volume_zscore_20"] = (volume - volume_mean) / volume_std
        data["trend_strength"] = (
            (data["ema_20"] - data["ema_50"]) / safe_close
        ) * (data["adx_14"] / 100.0)

        for lag in range(1, 9):
            data[f"return_lag_{lag}"] = data["return_1"].shift(lag - 1)
        for lag in range(1, 5):
            data[f"body_lag_{lag}"] = data["candle_body_pct"].shift(lag - 1)
            data[f"range_lag_{lag}"] = data["range_pct"].shift(lag - 1)
            data[f"volume_lag_{lag}"] = data["relative_volume"].shift(lag - 1)

        future_closes = pd.concat([close.shift(-step) for step in range(1, horizon + 1)], axis=1)
        future_lows = pd.concat([low.shift(-step) for step in range(1, horizon + 1)], axis=1)
        future_highs = pd.concat([high.shift(-step) for step in range(1, horizon + 1)], axis=1)
        data["future_gross_return"] = close.shift(-horizon) / safe_close - 1
        data["future_adverse_return"] = future_lows.min(axis=1) / safe_close - 1
        data["future_favourable_return"] = future_highs.max(axis=1) / safe_close - 1

        feature_columns = [
            "ema_gap_20_50",
            "price_gap_ema_20",
            "price_gap_ema_50",
            "price_gap_ema_200",
            "rsi_14",
            "atr_pct",
            "adx_14",
            "relative_volume",
            "volatility_20",
            "return_1",
            "return_3",
            "return_6",
            "return_12",
            "return_24",
            "candle_body_pct",
            "upper_wick_pct",
            "lower_wick_pct",
            "range_pct",
            "close_location",
            "open_gap_pct",
            "ema9_slope_pct",
            "ema20_slope_3",
            "ema50_slope_6",
            "atr_change_3",
            "volume_change_3",
            "positive_ratio_8",
            "positive_ratio_20",
            "rolling_high_gap_20",
            "rolling_low_gap_20",
            "volatility_ratio",
            "volume_zscore_20",
            "trend_strength",
            "range_ratio_20",
            "body_ratio",
            "compression_ratio",
            "trend_age_up",
            "extension_ema20_atr",
            "ignition_score",
            "exhaustion_score",
            *[f"return_lag_{lag}" for lag in range(1, 9)],
            *[f"body_lag_{lag}" for lag in range(1, 5)],
            *[f"range_lag_{lag}" for lag in range(1, 5)],
            *[f"volume_lag_{lag}" for lag in range(1, 5)],
        ]
        data[feature_columns] = data[feature_columns].replace([np.inf, -np.inf], np.nan)
        return PatternDataset(frame=data, feature_columns=feature_columns)


    def _candidate_windows(self, available_rows: int) -> list[int]:
        raw = self.settings.ai_pattern_candidate_windows.strip()
        parsed: list[int] = []
        if raw:
            for item in raw.split(","):
                try:
                    value = int(item.strip())
                except ValueError:
                    continue
                if value >= self.settings.ai_pattern_min_training_rows:
                    parsed.append(value)
        parsed.append(self.settings.ai_pattern_training_max_rows)
        return sorted({min(value, available_rows) for value in parsed if value <= available_rows})

    def _select_adaptive_training_window(
        self, training: pd.DataFrame, feature_columns: list[str]
    ) -> tuple[pd.DataFrame, int, float | None, float | None]:
        candidates = self._candidate_windows(len(training))
        if not candidates:
            x = training[feature_columns].astype(float).to_numpy()
            y = training["future_gross_return"].astype(float).to_numpy()
            accuracy, mae = self._time_ordered_validation(x, y)
            return training, len(training), accuracy, mae

        best: tuple[float, int, float | None, float | None] | None = None
        for window in candidates:
            subset = training.tail(window)
            x = subset[feature_columns].astype(float).to_numpy()
            y = subset["future_gross_return"].astype(float).to_numpy()
            accuracy, mae = self._time_ordered_validation(x, y)
            if accuracy is None or mae is None:
                continue
            scale = max(float(np.mean(np.abs(y))), 1e-6)
            score = accuracy - 0.10 * min(mae / scale, 5.0)
            if best is None or score > best[0] or (score == best[0] and window > best[1]):
                best = (score, window, accuracy, mae)

        if best is None:
            window = candidates[-1]
            subset = training.tail(window).copy()
            x = subset[feature_columns].astype(float).to_numpy()
            y = subset["future_gross_return"].astype(float).to_numpy()
            accuracy, mae = self._time_ordered_validation(x, y)
            return subset, window, accuracy, mae

        _, window, accuracy, mae = best
        return training.tail(window).copy(), window, accuracy, mae

    def _recency_weights(self, training: pd.DataFrame) -> np.ndarray:
        """Weight recent regimes more heavily without discarding older patterns."""
        timestamps = pd.to_datetime(training["timestamp"], utc=True)
        age_days = (timestamps.max() - timestamps).dt.total_seconds().to_numpy() / 86400.0
        half_life = self.settings.ai_pattern_recency_half_life_days
        weights = np.power(0.5, age_days / half_life)
        return np.clip(weights, 0.10, 1.0)

    def _new_model(self) -> ExtraTreesRegressor:
        return ExtraTreesRegressor(
            n_estimators=self.settings.ai_pattern_tree_count,
            max_depth=self.settings.ai_pattern_tree_max_depth,
            min_samples_leaf=self.settings.ai_pattern_min_samples_leaf,
            max_features="sqrt",
            random_state=self.settings.ai_pattern_random_state,
            n_jobs=1,
        )

    def _time_ordered_validation(
        self, x: np.ndarray, y: np.ndarray
    ) -> tuple[float | None, float | None]:
        validation_size = min(
            self.settings.ai_pattern_validation_rows,
            max(20, int(len(x) * 0.20)),
        )
        training_size = len(x) - validation_size
        if training_size < max(100, self.settings.ai_pattern_min_training_rows // 2):
            return None, None
        gap = self.settings.ai_pattern_horizon_candles
        effective_training_size = training_size - gap
        if effective_training_size < max(100, self.settings.ai_pattern_min_training_rows // 2):
            return None, None
        model = self._new_model()
        model.fit(x[:effective_training_size], y[:effective_training_size])
        predictions = model.predict(x[training_size:])
        actual = y[training_size:]
        accuracy = float(np.mean((predictions >= 0) == (actual >= 0)))
        mae = float(mean_absolute_error(actual, predictions))
        return accuracy, mae

    def _cluster_current_pattern(self, x_scaled: np.ndarray, current_scaled: np.ndarray) -> int:
        cluster_count = min(
            self.settings.ai_pattern_clusters,
            max(2, len(x_scaled) // 60),
            len(x_scaled),
        )
        if cluster_count < 2:
            return 0
        model = MiniBatchKMeans(
            n_clusters=cluster_count,
            random_state=self.settings.ai_pattern_random_state,
            batch_size=min(256, len(x_scaled)),
            n_init=5,
        )
        model.fit(x_scaled)
        return int(model.predict(current_scaled)[0])

    def _detect_regime(self, data: pd.DataFrame, trend_row: pd.Series) -> str:
        row = data.iloc[-1]
        adx = float(row["adx_14"])
        atr_pct = float(row["atr_pct"])
        volatility = float(row["volatility_20"])
        atr_q75 = float(data["atr_pct"].dropna().tail(self.settings.ai_pattern_recent_regime_rows).quantile(0.75))
        atr_q25 = float(data["atr_pct"].dropna().tail(self.settings.ai_pattern_recent_regime_rows).quantile(0.25))
        vol_q75 = float(data["volatility_20"].dropna().tail(self.settings.ai_pattern_recent_regime_rows).quantile(0.75))
        vol_q25 = float(data["volatility_20"].dropna().tail(self.settings.ai_pattern_recent_regime_rows).quantile(0.25))
        trend_bullish = (
            float(trend_row["close"]) > float(trend_row["ema_50"])
            and float(trend_row["ema_20"]) > float(trend_row["ema_50"])
        )
        trend_bearish = (
            float(trend_row["close"]) < float(trend_row["ema_50"])
            and float(trend_row["ema_20"]) < float(trend_row["ema_50"])
        )
        if atr_pct >= atr_q75 and volatility >= vol_q75:
            return "HIGH_VOLATILITY"
        if adx >= 23 and trend_bullish and float(row["ema20_slope_3"]) > 0:
            return "TREND_UP"
        if adx >= 23 and trend_bearish and float(row["ema20_slope_3"]) < 0:
            return "TREND_DOWN"
        if atr_pct <= atr_q25 and volatility <= vol_q25:
            return "LOW_VOLATILITY"
        if adx < 18 and abs(float(row["return_12"])) < max(atr_pct * 2.0, 0.002):
            return "RANGE"
        if abs(float(row["rolling_high_gap_20"])) <= max(atr_pct * 0.5, 0.001):
            return "BREAKOUT_TEST"
        return "TRANSITION"

    def _proposed_action(
        self,
        account: StrategyAccount,
        regime: str,
        upward_probability: float,
        expected_net_return: float,
        confidence: float,
    ) -> str:
        if account.has_open_position:
            if (
                upward_probability <= self.settings.ai_pattern_sell_probability_threshold
                or expected_net_return <= -self.settings.ai_pattern_min_expected_net_return
                or (regime == "TREND_DOWN" and confidence >= self.settings.ai_pattern_min_confidence)
            ):
                return "SELL"
            return "HOLD"
        if (
            upward_probability >= self.settings.ai_pattern_buy_probability_threshold
            and expected_net_return >= self.settings.ai_pattern_min_expected_net_return
            and confidence >= self.settings.ai_pattern_min_confidence
        ):
            return "BUY"
        return "HOLD"

    def _risk_governor(
        self,
        account: StrategyAccount,
        proposed_action: str,
        regime: str,
        upward_probability: float,
        expected_net_return: float,
        confidence: float,
        costs: ExecutionCosts,
        now: datetime,
        profile: TradingProfile,
    ) -> tuple[str, str]:
        if proposed_action == "HOLD":
            return "MONITORING", "The learned pattern does not currently justify a new action."
        if proposed_action == "SELL":
            return "APPROVED", "An autonomous exit is allowed because a paper position is open."
        if account.cooldown_until and self._as_utc(account.cooldown_until) > self._as_utc(now):
            return "BLOCKED", f"The AI portfolio is in cooldown until {account.cooldown_until}."
        if account.current_equity(None) <= account.initial_capital * (1 - profile.max_daily_loss_pct):
            return "BLOCKED", "The maximum paper loss limit blocks new AI entries."
        if costs.spread_rate > self.settings.ai_pattern_max_spread_rate:
            return "BLOCKED", "The observed spread is above the autonomous risk limit."
        if regime == "HIGH_VOLATILITY" and confidence < self.settings.ai_pattern_high_vol_min_confidence:
            return "BLOCKED", "High volatility requires a stronger pattern confidence."
        if upward_probability < self.settings.ai_pattern_buy_probability_threshold:
            return "BLOCKED", "The probability of a positive net move is below the entry threshold."
        if expected_net_return < self.settings.ai_pattern_min_expected_net_return:
            return "BLOCKED", "Expected return after costs is below the minimum entry edge."
        if confidence < self.settings.ai_pattern_min_confidence:
            return "BLOCKED", "Pattern confidence is below the autonomous entry threshold."
        return "APPROVED", "Pattern, expected net return and deterministic risk limits approved."

    def _risk_levels(
        self,
        current: pd.Series,
        expected_gross_return: float,
        worst_adverse_return: float,
        profile: TradingProfile,
    ) -> tuple[float, float, float]:
        close = float(current["close"])
        atr_pct = float(current["atr_pct"])
        learned_adverse_pct = abs(min(worst_adverse_return, 0.0))
        raw_stop_pct = max(
            atr_pct * self.settings.ai_pattern_stop_atr_multiplier,
            learned_adverse_pct * self.settings.ai_pattern_adverse_buffer,
        )
        stop_pct = min(
            max(raw_stop_pct, profile.stop_loss_min_pct),
            profile.stop_loss_max_pct,
        )
        reward_risk = max(
            self.settings.ai_pattern_reward_risk_ratio,
            profile.reward_risk_ratio,
        )
        target_pct = max(
            stop_pct * reward_risk,
            expected_gross_return,
            atr_pct * self.settings.ai_pattern_target_atr_multiplier,
        )
        return close * (1 - stop_pct), close * (1 + target_pct), reward_risk

    def _confidence(
        self,
        upward_probability: float,
        neighbour_positive_rate: float,
        validation_accuracy: float | None,
        sample_count: int,
    ) -> float:
        probability_strength = abs(upward_probability - 0.5) * 2
        neighbour_strength = abs(neighbour_positive_rate - 0.5) * 2
        validation_strength = (
            max(0.0, min(1.0, (validation_accuracy - 0.5) * 2))
            if validation_accuracy is not None
            else 0.0
        )
        sample_strength = min(1.0, sample_count / max(self.settings.ai_pattern_confident_rows, 1))
        confidence = (
            0.38 * probability_strength
            + 0.24 * neighbour_strength
            + 0.23 * validation_strength
            + 0.15 * sample_strength
        )
        return float(max(0.0, min(1.0, confidence)))

    @staticmethod
    def _feature_summary(row: pd.Series, feature_columns: list[str]) -> str:
        preferred = [
            "return_1",
            "return_6",
            "return_24",
            "atr_pct",
            "adx_14",
            "relative_volume",
            "ema9_slope_pct",
            "ema20_slope_3",
            "rolling_high_gap_20",
            "positive_ratio_8",
        ]
        summary = {
            name: round(float(row[name]), 8)
            for name in preferred
            if name in feature_columns and pd.notna(row[name])
        }
        return json.dumps(summary, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _update_account_diagnostics(
        account: StrategyAccount,
        cluster: int | None,
        confidence: float,
        upward_probability: float | None,
        expected_net_return: float | None,
        similar_patterns: int,
        risk_status: str,
        risk_reason: str,
    ) -> None:
        account.ai_pattern_cluster = cluster
        account.ai_confidence = confidence
        account.ai_upward_probability = upward_probability
        account.ai_expected_net_return = expected_net_return
        account.ai_similar_patterns = similar_patterns
        account.ai_risk_status = risk_status
        account.ai_risk_reason = risk_reason

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
