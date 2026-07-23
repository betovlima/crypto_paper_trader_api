from __future__ import annotations

import asyncio
from types import MethodType

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.mexc_client import MEXCPublicClient


def _row(open_time_ms: int) -> list[object]:
    close_time_ms = open_time_ms + 1_800_000 - 1
    price = 100.0 + open_time_ms / 1_000_000_000
    return [
        open_time_ms,
        str(price),
        str(price + 1),
        str(price - 1),
        str(price + 0.5),
        "10",
        close_time_ms,
        "1000",
    ]


def test_get_candles_paginates_above_mexc_batch_limit() -> None:
    client = MEXCPublicClient(Settings())
    start_ms = 1_700_000_000_000
    all_rows = [_row(start_ms + index * 1_800_000) for index in range(2500)]
    calls: list[dict[str, object]] = []

    async def fake_get_json(self, path, params):
        assert path == "/api/v3/klines"
        calls.append(dict(params))
        end_time = int(params.get("endTime", all_rows[-1][6]))
        eligible = [row for row in all_rows if int(row[0]) <= end_time]
        return eligible[-int(params["limit"]):]

    client._get_json = MethodType(fake_get_json, client)

    try:
        frame = asyncio.run(
            client.get_candles(
                "BTCUSDT",
                "30min",
                limit=2500,
                closed_only=True,
            )
        )
    finally:
        asyncio.run(client.close())

    assert len(frame) == 2500
    assert len(calls) == 3
    assert [int(call["limit"]) for call in calls] == [1000, 1000, 500]
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].nunique() == 2500


def test_get_candles_continues_after_open_candle_is_filtered() -> None:
    client = MEXCPublicClient(Settings())
    start_ms = 1_700_000_000_000
    all_rows = [_row(start_ms + index * 1_800_000) for index in range(1300)]
    # MEXC may include the currently forming candle in a full 1,000-row response.
    # closed_only removes it, so the client must continue paging instead of stopping at 999.
    all_rows[-1][6] = 9_999_999_999_999
    calls: list[dict[str, object]] = []

    async def fake_get_json(self, path, params):
        assert path == "/api/v3/klines"
        calls.append(dict(params))
        end_time = int(params.get("endTime", 9_999_999_999_999))
        eligible = [row for row in all_rows if int(row[0]) <= end_time]
        return eligible[-int(params["limit"]):]

    client._get_json = MethodType(fake_get_json, client)

    try:
        frame = asyncio.run(
            client.get_candles(
                "BTCUSDT",
                "30min",
                limit=1100,
                closed_only=True,
            )
        )
    finally:
        asyncio.run(client.close())

    assert len(frame) == 1100
    assert len(calls) == 2
    assert [int(call["limit"]) for call in calls] == [1000, 101]
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].nunique() == 1100


def test_get_candles_recovers_when_latest_page_is_partial() -> None:
    client = MEXCPublicClient(Settings())
    start_ms = 1_700_000_000_000
    all_rows = [_row(start_ms + index * 1_800_000) for index in range(1800)]
    calls: list[dict[str, object]] = []

    async def fake_get_json(self, path, params):
        assert path == "/api/v3/klines"
        calls.append(dict(params))
        if "startTime" not in params and "endTime" not in params:
            # Reproduce a partial latest response similar to the 512 raw candles
            # observed for SOLBTC in the local environment.
            return all_rows[-512:]
        assert "startTime" in params and "endTime" in params
        lower = int(params["startTime"])
        upper = int(params["endTime"])
        eligible = [row for row in all_rows if lower <= int(row[0]) <= upper]
        return eligible[-int(params["limit"]):]

    client._get_json = MethodType(fake_get_json, client)

    try:
        frame = asyncio.run(
            client.get_candles(
                "SOLBTC",
                "30min",
                limit=1100,
                closed_only=True,
            )
        )
    finally:
        asyncio.run(client.close())

    assert len(frame) == 1100
    assert len(calls) >= 2
    assert "startTime" not in calls[0]
    assert "endTime" not in calls[0]
    assert all("startTime" in call and "endTime" in call for call in calls[1:])
    assert frame["timestamp"].is_monotonic_increasing
    assert frame["timestamp"].nunique() == 1100


def test_get_candle_page_falls_back_when_bounded_window_is_empty() -> None:
    client = MEXCPublicClient(Settings())
    start_ms = 1_700_000_000_000
    rows = [_row(start_ms + index * 1_800_000) for index in range(40)]
    calls: list[dict[str, object]] = []

    async def fake_get_json(self, path, params):
        assert path == "/api/v3/klines"
        calls.append(dict(params))
        if "startTime" in params:
            # Reproduce a MEXC response seen on sparse pairs: the explicit bounded
            # window is empty although an endTime-only request can return history.
            return []
        end_time = int(params["endTime"])
        eligible = [row for row in rows if int(row[0]) <= end_time]
        return eligible[-int(params["limit"]):]

    client._get_json = MethodType(fake_get_json, client)

    try:
        frame = asyncio.run(
            client.get_candle_page(
                market="SOLBTC",
                period="30min",
                limit=20,
                closed_only=True,
                start_time_ms=start_ms,
                end_time_ms=start_ms + 39 * 1_800_000,
            )
        )
    finally:
        asyncio.run(client.close())

    assert len(frame) == 20
    assert len(calls) == 2
    assert "startTime" in calls[0]
    assert "startTime" not in calls[1]
    assert "endTime" in calls[1]
    assert frame["timestamp"].is_monotonic_increasing
