from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler


BULLISH_CANDLE_PATTERNS = {
    "HAMMER",
    "BULLISH_ENGULFING",
    "MORNING_STAR",
    "BULLISH_OUTSIDE_BAR",
}

BEARISH_CANDLE_PATTERNS = {
    "SHOOTING_STAR",
    "BEARISH_ENGULFING",
    "EVENING_STAR",
    "BEARISH_OUTSIDE_BAR",
}

PATTERN_FLAG_COLUMNS = {
    "DOJI": "pattern_doji",
    "HAMMER": "pattern_hammer",
    "SHOOTING_STAR": "pattern_shooting_star",
    "BULLISH_ENGULFING": "pattern_bullish_engulfing",
    "BEARISH_ENGULFING": "pattern_bearish_engulfing",
    "INSIDE_BAR": "pattern_inside_bar",
    "BULLISH_OUTSIDE_BAR": "pattern_bullish_outside_bar",
    "BEARISH_OUTSIDE_BAR": "pattern_bearish_outside_bar",
    "MORNING_STAR": "pattern_morning_star",
    "EVENING_STAR": "pattern_evening_star",
}


@dataclass(frozen=True, slots=True)
class TimeSeriesPatternSummary:
    status: str
    market: str
    execution_timeframe: str
    trend_timeframe: str
    history_candles_analyzed: int
    history_start_at: str | None
    history_end_at: str | None
    pattern_window_candles: int
    forecast_horizon_candles: int
    current_patterns: tuple[str, ...]
    similar_pattern_count: int
    positive_after_cost_rate: float | None
    expected_next_return: float | None
    median_next_return: float | None
    expected_adverse_return: float | None
    expected_favourable_return: float | None
    similarity_confidence: float | None
    nearest_mean_distance: float | None
    range_state: str
    range_bound_score: float | None
    range_support: float | None
    range_resistance: float | None
    range_position: float | None
    bollinger_zscore: float | None
    bollinger_bandwidth: float | None
    stochastic_k: float | None
    stochastic_d: float | None
    mean_crossings_20: float | None
    range_efficiency_20: float | None
    recommended_families: tuple[str, ...]
    dominant_historical_patterns: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["current_patterns"] = list(self.current_patterns)
        value["recommended_families"] = list(self.recommended_families)
        value["dominant_historical_patterns"] = list(self.dominant_historical_patterns)
        return value


class CandlestickPatternDetector:
    """Deterministic candlestick pattern flags used by the adaptive strategy engine.

    Patterns are treated as context features, never as standalone buy or sell advice.
    """

    @staticmethod
    def add_flags(frame: pd.DataFrame) -> pd.DataFrame:
        data = frame.copy()
        open_ = data["open"].astype(float)
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        close = data["close"].astype(float)

        candle_range = (high - low).replace(0, np.nan)
        body = (close - open_).abs()
        upper_wick = high - np.maximum(open_, close)
        lower_wick = np.minimum(open_, close) - low
        bullish = close > open_
        bearish = close < open_
        close_location = (close - low) / candle_range

        data["pattern_doji"] = body <= candle_range * 0.10
        data["pattern_hammer"] = (
            (lower_wick >= body.clip(lower=1e-12) * 2.0)
            & (upper_wick <= body.clip(lower=1e-12) * 0.80)
            & (close_location >= 0.58)
        )
        data["pattern_shooting_star"] = (
            (upper_wick >= body.clip(lower=1e-12) * 2.0)
            & (lower_wick <= body.clip(lower=1e-12) * 0.80)
            & (close_location <= 0.48)
        )

        previous_open = open_.shift(1)
        previous_close = close.shift(1)
        previous_bullish = previous_close > previous_open
        previous_bearish = previous_close < previous_open
        data["pattern_bullish_engulfing"] = (
            bullish
            & previous_bearish
            & (open_ <= previous_close)
            & (close >= previous_open)
        )
        data["pattern_bearish_engulfing"] = (
            bearish
            & previous_bullish
            & (open_ >= previous_close)
            & (close <= previous_open)
        )

        previous_high = high.shift(1)
        previous_low = low.shift(1)
        data["pattern_inside_bar"] = (high < previous_high) & (low > previous_low)
        outside = (high > previous_high) & (low < previous_low)
        data["pattern_bullish_outside_bar"] = outside & bullish
        data["pattern_bearish_outside_bar"] = outside & bearish

        body_two_back = body.shift(2)
        range_two_back = candle_range.shift(2)
        bearish_two_back = bearish.shift(2, fill_value=False)
        bullish_two_back = bullish.shift(2, fill_value=False)
        small_middle = body.shift(1) <= candle_range.shift(1) * 0.35
        first_midpoint = (open_.shift(2) + close.shift(2)) / 2.0
        data["pattern_morning_star"] = (
            bearish_two_back
            & (body_two_back >= range_two_back * 0.45)
            & small_middle.fillna(False)
            & bullish
            & (close >= first_midpoint)
        )
        data["pattern_evening_star"] = (
            bullish_two_back
            & (body_two_back >= range_two_back * 0.45)
            & small_middle.fillna(False)
            & bearish
            & (close <= first_midpoint)
        )

        for column in PATTERN_FLAG_COLUMNS.values():
            data[column] = data[column].fillna(False).astype(bool)
        return data

    @staticmethod
    def current_patterns(frame: pd.DataFrame) -> tuple[str, ...]:
        if frame.empty:
            return ()
        flagged = CandlestickPatternDetector.add_flags(frame)
        row = flagged.iloc[-1]
        return tuple(
            name for name, column in PATTERN_FLAG_COLUMNS.items() if bool(row[column])
        )

    @staticmethod
    def patterns_in_window(frame: pd.DataFrame) -> tuple[str, ...]:
        """Return every confirmed pattern present in the supplied recent window."""

        if frame.empty:
            return ()
        flagged = CandlestickPatternDetector.add_flags(frame)
        return tuple(
            name
            for name, column in PATTERN_FLAG_COLUMNS.items()
            if bool(flagged[column].astype(bool).any())
        )


class TimeSeriesPatternAnalyzer:
    """Find historical windows similar to the current movement of one selected asset."""

    BASE_FEATURES = (
        "ema_gap_20_50",
        "price_gap_ema_20",
        "price_gap_ema_50",
        "price_gap_ema_200",
        "rsi_14",
        "adx_14",
        "atr_pct",
        "relative_volume",
        "volatility_20",
        "return_3",
        "return_6",
        "candle_body_pct",
        "upper_wick_pct",
        "lower_wick_pct",
        "range_ratio_20",
        "compression_ratio",
        "ignition_score",
        "exhaustion_score",
        "distance_to_resistance_20",
        "distance_to_support_20",
        "range_position_20",
        "bollinger_width_20",
        "bollinger_zscore_20",
        "stochastic_k_14",
        "stochastic_d_3",
        "ema50_slope_10",
        "mean_crossings_20",
        "range_efficiency_20",
        "range_position_24",
        "range_bound_score",
    )

    def analyze(
        self,
        *,
        market: str,
        execution_timeframe: str,
        trend_timeframe: str,
        frame: pd.DataFrame,
        pattern_window_candles: int,
        horizon_candles: int,
        neighbor_count: int,
        max_history_candles: int,
        estimated_round_trip_cost: float,
    ) -> TimeSeriesPatternSummary:
        required_columns = {"timestamp", "open", "high", "low", "close"}
        if frame.empty or not required_columns.issubset(frame.columns):
            return self._empty_summary(
                status="INSUFFICIENT_PATTERN_HISTORY",
                market=market,
                execution_timeframe=execution_timeframe,
                trend_timeframe=trend_timeframe,
                data=frame.copy(),
                pattern_window_candles=pattern_window_candles,
                horizon_candles=horizon_candles,
                current_patterns=(),
            )
        data = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        data = data.tail(max_history_candles).reset_index(drop=True)
        data = CandlestickPatternDetector.add_flags(data)
        close = data["close"].astype(float).replace(0, np.nan)
        prior_high_20 = data["high"].astype(float).rolling(20).max().shift(1)
        prior_low_20 = data["low"].astype(float).rolling(20).min().shift(1)
        prior_range_20 = (prior_high_20 - prior_low_20).replace(0, np.nan)
        data["distance_to_resistance_20"] = prior_high_20 / close - 1.0
        data["distance_to_support_20"] = close / prior_low_20 - 1.0
        data["range_position_20"] = (close - prior_low_20) / prior_range_20
        current_patterns = CandlestickPatternDetector.current_patterns(data.tail(3))
        range_snapshot = self._range_snapshot(data.iloc[-1])

        minimum_rows = max(pattern_window_candles * 4, 240)
        if len(data) < minimum_rows:
            return self._empty_summary(
                status="INSUFFICIENT_PATTERN_HISTORY",
                market=market,
                execution_timeframe=execution_timeframe,
                trend_timeframe=trend_timeframe,
                data=data,
                pattern_window_candles=pattern_window_candles,
                horizon_candles=horizon_candles,
                current_patterns=current_patterns,
            )

        sequence_length = max(6, min(pattern_window_candles, 24))
        feature_columns = [
            *self.BASE_FEATURES,
            *PATTERN_FLAG_COLUMNS.values(),
        ]
        for column in feature_columns:
            if column not in data.columns:
                data[column] = np.nan

        candidate_rows: list[int] = []
        candidate_vectors: list[np.ndarray] = []
        future_returns: list[float] = []
        adverse_returns: list[float] = []
        favourable_returns: list[float] = []
        first_index = max(pattern_window_candles - 1, 200)
        last_historical_index = len(data) - horizon_candles - pattern_window_candles - 1

        for index in range(first_index, max(first_index, last_historical_index + 1)):
            vector = self._vector(data, index, sequence_length, feature_columns)
            if vector is None:
                continue
            close = float(data.iloc[index]["close"])
            if close <= 0:
                continue
            future = data.iloc[index + 1 : index + horizon_candles + 1]
            if len(future) < horizon_candles:
                continue
            candidate_rows.append(index)
            candidate_vectors.append(vector)
            future_returns.append(float(future.iloc[-1]["close"]) / close - 1.0)
            adverse_returns.append(float(future["low"].astype(float).min()) / close - 1.0)
            favourable_returns.append(float(future["high"].astype(float).max()) / close - 1.0)

        current_vector = self._vector(
            data,
            len(data) - 1,
            sequence_length,
            feature_columns,
        )
        if current_vector is None or len(candidate_vectors) < 20:
            return self._empty_summary(
                status="INSUFFICIENT_COMPARABLE_WINDOWS",
                market=market,
                execution_timeframe=execution_timeframe,
                trend_timeframe=trend_timeframe,
                data=data,
                pattern_window_candles=pattern_window_candles,
                horizon_candles=horizon_candles,
                current_patterns=current_patterns,
            )

        x = np.vstack(candidate_vectors)
        scaler = StandardScaler()
        x_scaled = scaler.fit_transform(x)
        current_scaled = scaler.transform(current_vector.reshape(1, -1))
        requested_neighbors = min(max(8, neighbor_count), len(candidate_rows))
        model = NearestNeighbors(n_neighbors=requested_neighbors, metric="euclidean")
        model.fit(x_scaled)
        distances, positions = model.kneighbors(current_scaled)
        selected_positions = positions[0]
        selected_rows = [candidate_rows[position] for position in selected_positions]
        selected_returns = np.asarray([future_returns[position] for position in selected_positions])
        selected_adverse = np.asarray([adverse_returns[position] for position in selected_positions])
        selected_favourable = np.asarray(
            [favourable_returns[position] for position in selected_positions]
        )

        positive_rate = float(np.mean(selected_returns > estimated_round_trip_cost))
        mean_distance = float(np.mean(distances[0]))
        sample_strength = min(1.0, requested_neighbors / max(neighbor_count, 1))
        direction_strength = abs(positive_rate - 0.5) * 2.0
        similarity_strength = 1.0 / (1.0 + mean_distance)
        confidence = float(
            np.clip(
                0.45 * similarity_strength
                + 0.35 * direction_strength
                + 0.20 * sample_strength,
                0.0,
                1.0,
            )
        )

        dominant = self._dominant_patterns(data, selected_rows)
        recommended = self._recommended_families(
            current_patterns=current_patterns,
            positive_rate=positive_rate,
            expected_return=float(np.mean(selected_returns)),
            current_row=data.iloc[-1],
        )
        timestamps = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
        return TimeSeriesPatternSummary(
            status="READY",
            market=market,
            execution_timeframe=execution_timeframe,
            trend_timeframe=trend_timeframe,
            history_candles_analyzed=len(data),
            history_start_at=self._timestamp_text(timestamps.iloc[0]),
            history_end_at=self._timestamp_text(timestamps.iloc[-1]),
            pattern_window_candles=pattern_window_candles,
            forecast_horizon_candles=horizon_candles,
            current_patterns=current_patterns,
            similar_pattern_count=requested_neighbors,
            positive_after_cost_rate=positive_rate,
            expected_next_return=float(np.mean(selected_returns)),
            median_next_return=float(np.median(selected_returns)),
            expected_adverse_return=float(np.mean(selected_adverse)),
            expected_favourable_return=float(np.mean(selected_favourable)),
            similarity_confidence=confidence,
            nearest_mean_distance=mean_distance,
            range_state=range_snapshot["range_state"],
            range_bound_score=range_snapshot["range_bound_score"],
            range_support=range_snapshot["range_support"],
            range_resistance=range_snapshot["range_resistance"],
            range_position=range_snapshot["range_position"],
            bollinger_zscore=range_snapshot["bollinger_zscore"],
            bollinger_bandwidth=range_snapshot["bollinger_bandwidth"],
            stochastic_k=range_snapshot["stochastic_k"],
            stochastic_d=range_snapshot["stochastic_d"],
            mean_crossings_20=range_snapshot["mean_crossings_20"],
            range_efficiency_20=range_snapshot["range_efficiency_20"],
            recommended_families=recommended,
            dominant_historical_patterns=dominant,
        )

    @staticmethod
    def _vector(
        data: pd.DataFrame,
        index: int,
        sequence_length: int,
        feature_columns: list[str],
    ) -> np.ndarray | None:
        start = index - sequence_length + 1
        if start < 0:
            return None
        sequence = data.iloc[start : index + 1]
        returns = sequence["close"].astype(float).pct_change().fillna(0.0).to_numpy()
        if len(returns) != sequence_length:
            return None
        row = data.iloc[index]
        values: list[float] = [*returns.tolist()]
        for column in feature_columns:
            raw = row.get(column)
            if isinstance(raw, (bool, np.bool_)):
                values.append(1.0 if bool(raw) else 0.0)
            else:
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    return None
                if not np.isfinite(value):
                    return None
                values.append(value)
        vector = np.asarray(values, dtype=float)
        return vector if np.isfinite(vector).all() else None

    @staticmethod
    def _dominant_patterns(data: pd.DataFrame, rows: list[int]) -> tuple[str, ...]:
        counts: list[tuple[str, int]] = []
        for name, column in PATTERN_FLAG_COLUMNS.items():
            count = int(data.iloc[rows][column].astype(bool).sum())
            if count:
                counts.append((name, count))
        counts.sort(key=lambda item: (-item[1], item[0]))
        return tuple(name for name, _count in counts[:5])

    @staticmethod
    def _recommended_families(
        *,
        current_patterns: tuple[str, ...],
        positive_rate: float,
        expected_return: float,
        current_row: pd.Series,
    ) -> tuple[str, ...]:
        names: list[str] = []
        pattern_set = set(current_patterns)
        ema20 = float(current_row.get("ema_20", 0.0) or 0.0)
        ema50 = float(current_row.get("ema_50", 0.0) or 0.0)
        close = float(current_row.get("close", 0.0) or 0.0)
        adx = float(current_row.get("adx_14", 0.0) or 0.0)
        compression = float(current_row.get("compression_ratio", 1.0) or 1.0)
        range_score = float(current_row.get("range_bound_score", 0.0) or 0.0)
        range_position = float(current_row.get("range_position_24", 0.5) or 0.5)
        bollinger_zscore = float(current_row.get("bollinger_zscore_20", 0.0) or 0.0)
        stochastic_k = float(current_row.get("stochastic_k_14", 50.0) or 50.0)

        if pattern_set & BULLISH_CANDLE_PATTERNS:
            names.extend(["EMA_CANDLE_PULLBACK", "CANDLE_REVERSAL"])
        if pattern_set & BEARISH_CANDLE_PATTERNS:
            names.append("CANDLE_REVERSAL")
        if close > ema20 > ema50 and adx >= 18:
            names.extend(["TREND_PULLBACK", "MOMENTUM_CONTINUATION"])
        if compression < 0.85:
            names.extend(["VOLATILITY_BREAKOUT", "DONCHIAN_BREAKOUT"])
        if adx < 18:
            names.append("MEAN_REVERSION")
        if range_score >= 55:
            names.extend(["BOLLINGER_MEAN_REVERSION", "STOCHASTIC_RANGE"])
            if range_position <= 0.35:
                names.extend(["SUPPORT_CANDLE_REVERSAL", "FALSE_BREAKOUT_REVERSAL"])
            if bollinger_zscore <= -1.2:
                names.insert(0, "BOLLINGER_MEAN_REVERSION")
            if stochastic_k <= 30:
                names.insert(0, "STOCHASTIC_RANGE")
        if positive_rate >= 0.58 and expected_return > 0:
            names.append("MOMENTUM_CONTINUATION")
        if not names:
            names.extend(["TREND_PULLBACK", "MEAN_REVERSION"])
        return tuple(dict.fromkeys(names))

    def _empty_summary(
        self,
        *,
        status: str,
        market: str,
        execution_timeframe: str,
        trend_timeframe: str,
        data: pd.DataFrame,
        pattern_window_candles: int,
        horizon_candles: int,
        current_patterns: tuple[str, ...],
    ) -> TimeSeriesPatternSummary:
        if "timestamp" in data.columns:
            timestamps = pd.to_datetime(data["timestamp"], utc=True, errors="coerce")
        else:
            timestamps = pd.Series(dtype="datetime64[ns, UTC]")
        start = self._timestamp_text(timestamps.iloc[0]) if len(timestamps) else None
        end = self._timestamp_text(timestamps.iloc[-1]) if len(timestamps) else None
        range_snapshot = self._range_snapshot(data.iloc[-1] if len(data) else None)
        return TimeSeriesPatternSummary(
            status=status,
            market=market,
            execution_timeframe=execution_timeframe,
            trend_timeframe=trend_timeframe,
            history_candles_analyzed=len(data),
            history_start_at=start,
            history_end_at=end,
            pattern_window_candles=pattern_window_candles,
            forecast_horizon_candles=horizon_candles,
            current_patterns=current_patterns,
            similar_pattern_count=0,
            positive_after_cost_rate=None,
            expected_next_return=None,
            median_next_return=None,
            expected_adverse_return=None,
            expected_favourable_return=None,
            similarity_confidence=None,
            nearest_mean_distance=None,
            range_state=range_snapshot["range_state"],
            range_bound_score=range_snapshot["range_bound_score"],
            range_support=range_snapshot["range_support"],
            range_resistance=range_snapshot["range_resistance"],
            range_position=range_snapshot["range_position"],
            bollinger_zscore=range_snapshot["bollinger_zscore"],
            bollinger_bandwidth=range_snapshot["bollinger_bandwidth"],
            stochastic_k=range_snapshot["stochastic_k"],
            stochastic_d=range_snapshot["stochastic_d"],
            mean_crossings_20=range_snapshot["mean_crossings_20"],
            range_efficiency_20=range_snapshot["range_efficiency_20"],
            recommended_families=(),
            dominant_historical_patterns=(),
        )

    @staticmethod
    def _timestamp_text(value: Any) -> str | None:
        if value is None or pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()

    @staticmethod
    def _range_snapshot(row: pd.Series | None) -> dict[str, Any]:
        def finite(name: str) -> float | None:
            if row is None:
                return None
            try:
                value = float(row.get(name))
            except (TypeError, ValueError):
                return None
            return value if np.isfinite(value) else None

        score = finite("range_bound_score")
        if score is None:
            state = "UNKNOWN"
        elif score >= 65:
            state = "RANGE_BOUND"
        elif score >= 50:
            state = "RANGE_LIKELY"
        else:
            state = "NOT_RANGE_BOUND"
        return {
            "range_state": state,
            "range_bound_score": score,
            "range_support": finite("range_support_24"),
            "range_resistance": finite("range_resistance_24"),
            "range_position": finite("range_position_24"),
            "bollinger_zscore": finite("bollinger_zscore_20"),
            "bollinger_bandwidth": finite("bollinger_width_20"),
            "stochastic_k": finite("stochastic_k_14"),
            "stochastic_d": finite("stochastic_d_3"),
            "mean_crossings_20": finite("mean_crossings_20"),
            "range_efficiency_20": finite("range_efficiency_20"),
        }
