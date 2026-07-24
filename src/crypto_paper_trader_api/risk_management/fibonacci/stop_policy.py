from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .levels import bullish_retracement_price
from .swing_detector import BullishImpulse, detect_latest_bullish_impulse


@dataclass(frozen=True, slots=True)
class FibonacciStop:
    impulse: BullishImpulse
    retracement_ratio: float
    retracement_price: float
    atr_buffer: float
    stop_price: float
    distance_atr: float


def calculate_bullish_fibonacci_stop(
    frame: pd.DataFrame,
    *,
    current_price: float,
    current_index: int | None = None,
    retracement_ratio: float = 0.618,
    buffer_atr_multiplier: float = 0.25,
    pivot_bars: int = 3,
    lookback_bars: int = 120,
    min_impulse_atr: float = 2.0,
    max_stop_distance_atr: float | None = None,
) -> FibonacciStop | None:
    impulse = detect_latest_bullish_impulse(
        frame,
        current_index=current_index,
        pivot_bars=pivot_bars,
        lookback_bars=lookback_bars,
        min_impulse_atr=min_impulse_atr,
    )
    if impulse is None:
        return None

    level_price = bullish_retracement_price(
        impulse.low_price,
        impulse.high_price,
        retracement_ratio,
    )
    buffer = max(float(buffer_atr_multiplier), 0.0) * impulse.atr
    stop_price = max(level_price - buffer, 0.0)
    price = float(current_price)
    if stop_price <= 0 or stop_price >= price:
        return None

    distance_atr = (price - stop_price) / max(impulse.atr, 1e-12)
    if max_stop_distance_atr is not None and distance_atr > float(max_stop_distance_atr):
        return None

    return FibonacciStop(
        impulse=impulse,
        retracement_ratio=float(retracement_ratio),
        retracement_price=level_price,
        atr_buffer=buffer,
        stop_price=stop_price,
        distance_atr=distance_atr,
    )
