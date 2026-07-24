from __future__ import annotations


def _validate_impulse(low_price: float, high_price: float) -> tuple[float, float]:
    low = float(low_price)
    high = float(high_price)
    if low <= 0 or high <= low:
        raise ValueError("A bullish impulse requires 0 < low_price < high_price.")
    return low, high


def bullish_retracement_price(low_price: float, high_price: float, ratio: float) -> float:
    """Return a retracement level measured down from a bullish impulse high."""

    low, high = _validate_impulse(low_price, high_price)
    normalized_ratio = float(ratio)
    if not 0 <= normalized_ratio <= 1:
        raise ValueError("A Fibonacci retracement ratio must be between 0 and 1.")
    return high - normalized_ratio * (high - low)


def bullish_extension_price(low_price: float, high_price: float, ratio: float) -> float:
    """Return a bullish extension where 1.272 means 27.2% above the impulse high."""

    low, high = _validate_impulse(low_price, high_price)
    normalized_ratio = float(ratio)
    if normalized_ratio < 1:
        raise ValueError("A Fibonacci extension ratio must be greater than or equal to 1.")
    return low + normalized_ratio * (high - low)
