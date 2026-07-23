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
