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
]


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
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

    for period in (5, 9, 13, 20, 21, 34, 50, 200):
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

    numeric_columns = list(
        dict.fromkeys(
            [
                "ema_5",
                "ema_9",
                "ema_13",
                "ema_20",
                "ema_21",
                "ema_34",
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
