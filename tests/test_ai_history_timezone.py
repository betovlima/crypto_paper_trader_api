from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from crypto_paper_trader_api.ai_history_service import AIHistoryService


def test_sqlite_naive_timestamp_is_normalized_to_utc_before_comparison() -> None:
    sqlite_timestamp = datetime(2026, 7, 21, 12, 0, 0)
    mexc_timestamp = pd.Timestamp("2026-07-21T11:30:00Z")

    normalized_first = AIHistoryService._as_utc_timestamp(sqlite_timestamp)

    assert normalized_first == pd.Timestamp("2026-07-21T12:00:00Z")
    assert mexc_timestamp < normalized_first


def test_aware_timestamp_is_converted_to_utc() -> None:
    timestamp = pd.Timestamp("2026-07-21T09:00:00-03:00")

    normalized = AIHistoryService._as_utc_timestamp(timestamp)

    assert normalized == pd.Timestamp("2026-07-21T12:00:00Z")
    assert normalized.tzinfo is not None


def test_candle_frame_normalizes_naive_and_aware_timestamps() -> None:
    frame = pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 7, 21, 10, 0, 0),
                datetime(2026, 7, 21, 11, 0, 0, tzinfo=timezone.utc),
            ],
            "open": [1.0, 1.1],
            "high": [1.2, 1.3],
            "low": [0.9, 1.0],
            "close": [1.1, 1.2],
            "volume": [100.0, 110.0],
            "value": [110.0, 132.0],
        }
    )

    normalized = AIHistoryService._normalize_timestamp_column(frame)

    assert str(normalized["timestamp"].dtype) == "datetime64[us, UTC]" or str(
        normalized["timestamp"].dtype
    ) == "datetime64[ns, UTC]"
    assert normalized.iloc[0]["timestamp"] == pd.Timestamp("2026-07-21T10:00:00Z")
    assert normalized.iloc[1]["timestamp"] == pd.Timestamp("2026-07-21T11:00:00Z")
