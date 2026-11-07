from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


@dataclass(frozen=True, slots=True)
class BullishImpulse:
    low_index: int
    high_index: int
    low_price: float
    high_price: float
    low_timestamp: datetime | pd.Timestamp | None
    high_timestamp: datetime | pd.Timestamp | None
    atr: float
    size_atr: float

    @property
    def price_range(self) -> float:
        return self.high_price - self.low_price


def _confirmed_pivot_lows(frame: pd.DataFrame, pivot_bars: int) -> list[int]:
    lows = frame["low"].astype(float).reset_index(drop=True)
    result: list[int] = []
    for index in range(pivot_bars, len(frame) - pivot_bars):
        center = float(lows.iloc[index])
        window = lows.iloc[index - pivot_bars : index + pivot_bars + 1]
        if center == float(window.min()) and center < float(lows.iloc[index - 1]):
            result.append(index)
    return result


def detect_latest_bullish_impulse(
    frame: pd.DataFrame,
    *,
    current_index: int | None = None,
    pivot_bars: int = 3,
    lookback_bars: int = 120,
    min_impulse_atr: float = 2.0,
) -> BullishImpulse | None:
    """Detect the latest causal bullish impulse ending at a known historical high.

    The swing low must already be confirmed by ``pivot_bars`` closed candles on both
    sides. The impulse high may be the latest known high after that confirmed low, so
    the calculation never needs future candles and can expand while a trend advances.
    """

    required = {"low", "high", "atr_14"}
    if frame.empty or not required.issubset(frame.columns):
        return None
    end_index = len(frame) - 1 if current_index is None else int(current_index)
    if end_index < pivot_bars * 2 + 1:
        return None

    start_index = max(0, end_index - max(int(lookback_bars), pivot_bars * 2 + 2) + 1)
    history = frame.iloc[start_index : end_index + 1].reset_index(drop=True)
    pivot_lows = _confirmed_pivot_lows(history, int(pivot_bars))
    if not pivot_lows:
        return None

    latest: BullishImpulse | None = None
    for local_low_index in reversed(pivot_lows):
        after_low = history.iloc[local_low_index:]
        if len(after_low) < 2:
            continue
        local_high_offset = int(after_low["high"].astype(float).to_numpy().argmax())
        local_high_index = local_low_index + local_high_offset
        if local_high_index <= local_low_index:
            continue

        low_price = float(history.iloc[local_low_index]["low"])
        high_price = float(history.iloc[local_high_index]["high"])
        atr_value = float(history.iloc[-1].get("atr_14", 0.0) or 0.0)
        if atr_value <= 0 or high_price <= low_price:
            continue
        size_atr = (high_price - low_price) / atr_value
        if size_atr < float(min_impulse_atr):
            continue

        low_timestamp = (
            history.iloc[local_low_index].get("timestamp")
            if "timestamp" in history.columns
            else None
        )
        high_timestamp = (
            history.iloc[local_high_index].get("timestamp")
            if "timestamp" in history.columns
            else None
        )
        latest = BullishImpulse(
            low_index=start_index + local_low_index,
            high_index=start_index + local_high_index,
            low_price=low_price,
            high_price=high_price,
            low_timestamp=low_timestamp,
            high_timestamp=high_timestamp,
            atr=atr_value,
            size_atr=size_atr,
        )
        break
    return latest
