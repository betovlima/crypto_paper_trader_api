from __future__ import annotations

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
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
    "candle_body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "range_ratio_20",
    "body_ratio",
    "close_location",
    "compression_ratio",
    "trend_age_up",
    "extension_ema20_atr",
    "ignition_score",
    "exhaustion_score",
]


def add_indicators(
    frame: pd.DataFrame,
    context_lookback: int = 20,
    compression_window: int = 5,
) -> pd.DataFrame:
    """Return a copy with technical indicators and model features."""

    required = {"open", "high", "low", "close", "volume", "timestamp"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")

    data = frame.copy().sort_values("timestamp").reset_index(drop=True)
    close = data["close"].astype(float)
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    open_ = data["open"].astype(float)
    volume = data["volume"].astype(float)

    for period in (5, 9, 13, 20, 21, 25, 30, 34, 35, 40, 45, 50, 200):
        data[f"ema_{period}"] = close.ewm(
            span=period, adjust=False, min_periods=period
        ).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    average_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = average_gain / average_loss.replace(0, np.nan)
    data["rsi_14"] = (100 - (100 / (1 + rs))).fillna(50.0)

    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    ).max(axis=1)
    data["atr_14"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    upward_move = high.diff()
    downward_move = -low.diff()
    plus_dm = pd.Series(
        np.where((upward_move > downward_move) & (upward_move > 0), upward_move, 0.0),
        index=data.index,
    )
    minus_dm = pd.Series(
        np.where((downward_move > upward_move) & (downward_move > 0), downward_move, 0.0),
        index=data.index,
    )
    smoothed_tr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smoothed_tr
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / smoothed_tr
    denominator = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denominator
    data["adx_14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().fillna(0.0)

    data["average_volume_20"] = volume.rolling(20, min_periods=20).mean()
    data["relative_volume"] = volume / data["average_volume_20"].replace(0, np.nan)

    data["return_1"] = close.pct_change(1)
    data["return_3"] = close.pct_change(3)
    data["return_6"] = close.pct_change(6)
    data["volatility_20"] = data["return_1"].rolling(20, min_periods=20).std()

    safe_close = close.replace(0, np.nan)
    candle_top = pd.concat([open_, close], axis=1).max(axis=1)
    candle_bottom = pd.concat([open_, close], axis=1).min(axis=1)
    data["candle_body_pct"] = (close - open_) / safe_close
    data["upper_wick_pct"] = (high - candle_top) / safe_close
    data["lower_wick_pct"] = (candle_bottom - low) / safe_close

    data["ema_gap_20_50"] = (data["ema_20"] - data["ema_50"]) / safe_close
    data["price_gap_ema_20"] = (close - data["ema_20"]) / safe_close
    data["price_gap_ema_50"] = (close - data["ema_50"]) / safe_close
    data["price_gap_ema_200"] = (close - data["ema_200"]) / safe_close
    data["atr_pct"] = data["atr_14"] / safe_close

    # Linda Bradford Raschke 3/10 oscillator. Unlike classic MACD, the
    # oscillator and signal line use simple moving averages.
    data["sma_3"] = close.rolling(3, min_periods=3).mean()
    data["sma_10"] = close.rolling(10, min_periods=10).mean()
    data["lbr_310_fast"] = data["sma_3"] - data["sma_10"]
    data["lbr_310_slow"] = data["lbr_310_fast"].rolling(16, min_periods=16).mean()
    data["lbr_310_fast_slope"] = data["lbr_310_fast"].diff()
    data["lbr_310_slow_slope"] = data["lbr_310_slow"].diff()

    # Context features use only the current and previously closed candles. The
    # reference medians are shifted by one row so the current range never changes
    # its own baseline. These features distinguish ignition after compression from
    # exhaustion after an already extended movement.
    candle_range = (high - low).replace(0, np.nan)
    previous_range_median = candle_range.shift(1).rolling(
        context_lookback, min_periods=context_lookback
    ).median()
    recent_range_median = candle_range.shift(1).rolling(
        compression_window, min_periods=compression_window
    ).median()
    data["range_ratio_20"] = candle_range / previous_range_median.replace(0, np.nan)
    data["body_ratio"] = (close - open_).abs() / candle_range
    data["close_location"] = (close - low) / candle_range
    data["upper_wick_ratio"] = (high - candle_top) / candle_range
    data["lower_wick_ratio"] = (candle_bottom - low) / candle_range
    data["compression_ratio"] = recent_range_median / previous_range_median.replace(0, np.nan)

    positive_candle = close.diff().gt(0)
    positive_groups = positive_candle.ne(positive_candle.shift()).cumsum()
    trend_age = positive_candle.groupby(positive_groups).cumcount().add(1)
    data["trend_age_up"] = trend_age.where(positive_candle, 0).astype(float)
    data["extension_ema20_atr"] = (close - data["ema_20"]).abs() / data["atr_14"].replace(0, np.nan)

    range_component = ((data["range_ratio_20"] - 1.0) / 1.5).clip(0, 1)
    body_component = ((data["body_ratio"] - 0.45) / 0.50).clip(0, 1)
    close_component = ((data["close_location"] - 0.55) / 0.45).clip(0, 1)
    volume_component = ((data["relative_volume"] - 1.0) / 1.5).clip(0, 1)
    compression_component = ((1.0 - data["compression_ratio"]) / 0.50).clip(0, 1)
    extension_penalty = ((data["extension_ema20_atr"] - 1.0) / 1.5).clip(0, 1)
    data["ignition_score"] = (
        0.25 * range_component
        + 0.25 * body_component
        + 0.20 * close_component
        + 0.15 * volume_component
        + 0.15 * compression_component
    ) * (1.0 - 0.55 * extension_penalty)

    trend_age_component = ((data["trend_age_up"] - 3.0) / 7.0).clip(0, 1)
    extension_component = ((data["extension_ema20_atr"] - 1.0) / 2.0).clip(0, 1)
    upper_wick_component = ((data["upper_wick_ratio"] - 0.12) / 0.50).clip(0, 1)
    extreme_volume_component = ((data["relative_volume"] - 1.5) / 2.0).clip(0, 1)
    data["exhaustion_score"] = (
        0.30 * range_component
        + 0.25 * trend_age_component
        + 0.25 * extension_component
        + 0.10 * upper_wick_component
        + 0.10 * extreme_volume_component
    ).clip(0, 1)

    # Range-bound evidence used by the adaptive pattern strategy. All rolling
    # calculations use only current and previous closed candles.
    range_window = 24
    data["range_support_24"] = low.rolling(range_window, min_periods=range_window).min()
    data["range_resistance_24"] = high.rolling(range_window, min_periods=range_window).max()
    range_width_24 = (data["range_resistance_24"] - data["range_support_24"]).replace(0, np.nan)
    data["range_position_24"] = (close - data["range_support_24"]) / range_width_24

    bollinger_mean = close.rolling(20, min_periods=20).mean()
    bollinger_std = close.rolling(20, min_periods=20).std().replace(0, np.nan)
    data["bollinger_zscore_20"] = (close - bollinger_mean) / bollinger_std
    data["bollinger_width_20"] = (4.0 * bollinger_std) / safe_close

    lowest_14 = low.rolling(14, min_periods=14).min()
    highest_14 = high.rolling(14, min_periods=14).max()
    stochastic_range = (highest_14 - lowest_14).replace(0, np.nan)
    data["stochastic_k_14"] = 100.0 * (close - lowest_14) / stochastic_range
    data["stochastic_d_3"] = data["stochastic_k_14"].rolling(3, min_periods=3).mean()

    ema50_delta = data["ema_50"].diff(10)
    data["ema50_slope_10"] = ema50_delta / safe_close
    centered = close - bollinger_mean
    crossing = (centered * centered.shift(1) < 0).astype(float)
    data["mean_crossings_20"] = crossing.rolling(20, min_periods=20).sum()
    net_change_20 = close.diff(20).abs()
    path_length_20 = close.diff().abs().rolling(20, min_periods=20).sum().replace(0, np.nan)
    data["range_efficiency_20"] = net_change_20 / path_length_20

    adx_component = (1.0 - (data["adx_14"] / 35.0)).clip(0, 1)
    slope_component = (1.0 - (data["ema50_slope_10"].abs() / 0.02)).clip(0, 1)
    efficiency_component = (1.0 - (data["range_efficiency_20"] / 0.45)).clip(0, 1)
    crossings_component = (data["mean_crossings_20"] / 6.0).clip(0, 1)
    bandwidth_component = (1.0 - (data["bollinger_width_20"] / 0.08)).clip(0, 1)
    data["range_bound_score"] = 100.0 * (
        0.30 * adx_component
        + 0.20 * slope_component
        + 0.25 * efficiency_component
        + 0.15 * crossings_component
        + 0.10 * bandwidth_component
    )

    numeric_columns = list(
        dict.fromkeys(
            [
                "ema_5",
                "ema_9",
                "ema_13",
                "ema_20",
                "ema_21",
                "ema_25",
                "ema_30",
                "ema_34",
                "ema_35",
                "ema_40",
                "ema_45",
                "ema_50",
                "ema_200",
                "sma_3",
                "sma_10",
                "lbr_310_fast",
                "lbr_310_slow",
                "lbr_310_fast_slope",
                "lbr_310_slow_slope",
                "rsi_14",
                "atr_14",
                "adx_14",
                "average_volume_20",
                "relative_volume",
                "volatility_20",
                "upper_wick_ratio",
                "lower_wick_ratio",
                "range_support_24",
                "range_resistance_24",
                "range_position_24",
                "bollinger_zscore_20",
                "bollinger_width_20",
                "stochastic_k_14",
                "stochastic_d_3",
                "ema50_slope_10",
                "mean_crossings_20",
                "range_efficiency_20",
                "range_bound_score",
                *FEATURE_COLUMNS,
            ]
        )
    )
    data[numeric_columns] = data[numeric_columns].replace([np.inf, -np.inf], np.nan)
    return data


def latest_complete_row(frame: pd.DataFrame) -> pd.Series:
    required = [
        "ema_9",
        "ema_20",
        "ema_50",
        "ema_200",
        "rsi_14",
        "atr_14",
        "adx_14",
        "average_volume_20",
        "relative_volume",
        "volatility_20",
        *FEATURE_COLUMNS,
    ]
    complete = frame.dropna(subset=required)
    if complete.empty:
        raise ValueError(
            "Not enough candles to calculate all indicators. At least 200 are required."
        )
    return complete.iloc[-1]
