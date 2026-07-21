from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pandas as pd

from .config import Settings
from .execution_costs import DepthSnapshot, MarketRules


TIMEFRAME_SECONDS: dict[str, int] = {
    "1min": 60,
    "3min": 180,
    "5min": 300,
    "15min": 900,
    "30min": 1800,
    "1hour": 3600,
    "2hour": 7200,
    "4hour": 14400,
    "6hour": 21600,
    "12hour": 43200,
    "1day": 86400,
    "3day": 259200,
    "1week": 604800,
}


class CoinExAPIError(RuntimeError):
    """Raised when CoinEx returns an invalid or unsuccessful response."""


class CoinExPublicClient:
    """Read-only client for public CoinEx Spot market data.

    This class intentionally contains no authentication and no order methods.
    """

    def __init__(self, settings: Settings) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.coinex_base_url.rstrip("/"),
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": "crypto-paper-trader/0.7"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_ticker(self, market: str) -> dict[str, Any]:
        response = await self._get("/spot/ticker", params={"market": market})
        payload = self._parse_response(response)
        rows = payload.get("data") or []
        if not rows:
            raise CoinExAPIError(f"CoinEx returned no ticker data for {market}.")
        return rows[0]

    async def get_latest_price(self, market: str) -> float:
        ticker = await self.get_ticker(market)
        return float(ticker["last"])

    async def get_market_rules(self, market: str) -> MarketRules:
        """Read public fee and minimum-order metadata for one Spot market."""
        response = await self._get("/spot/market", params={"market": market})
        payload = self._parse_response(response)
        rows = payload.get("data") or []
        if not rows:
            raise CoinExAPIError(f"CoinEx returned no market rules for {market}.")
        row = rows[0]
        return MarketRules(
            market=str(row["market"]),
            maker_fee_rate=float(row["maker_fee_rate"]),
            taker_fee_rate=float(row["taker_fee_rate"]),
            min_amount=float(row["min_amount"]),
            base_currency=str(row["base_ccy"]),
            quote_currency=str(row["quote_ccy"]),
            base_precision=int(row["base_ccy_precision"]),
            quote_precision=int(row["quote_ccy_precision"]),
            status=str(row["status"]),
        )

    async def get_depth_snapshot(self, market: str) -> DepthSnapshot:
        """Read best bid/ask and calculate the current relative spread."""
        response = await self._get(
            "/spot/depth",
            params={"market": market, "limit": 5, "interval": "0"},
        )
        payload = self._parse_response(response)
        data = payload.get("data") or {}
        depth = data.get("depth") or {}
        bids = depth.get("bids") or []
        asks = depth.get("asks") or []
        if not bids or not asks:
            raise CoinExAPIError(f"CoinEx returned incomplete depth for {market}.")

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            raise CoinExAPIError(f"CoinEx returned invalid bid/ask values for {market}.")
        mid = (best_bid + best_ask) / 2
        spread_rate = (best_ask - best_bid) / mid if mid > 0 else 0.0
        return DepthSnapshot(
            market=market,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid,
            spread_rate=spread_rate,
            updated_at_ms=int(depth.get("updated_at") or 0),
        )

    async def get_candles(
        self,
        market: str,
        period: str,
        limit: int = 500,
        closed_only: bool = True,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> pd.DataFrame:
        if period not in TIMEFRAME_SECONDS:
            raise ValueError(f"Unsupported CoinEx timeframe: {period}")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")

        params: dict[str, Any] = {"market": market, "period": period, "limit": limit}
        if start_time_ms is not None:
            params["start_time"] = int(start_time_ms)
        if end_time_ms is not None:
            params["end_time"] = int(end_time_ms)
        response = await self._get("/spot/kline", params=params)
        payload = self._parse_response(response)
        rows = payload.get("data") or []
        if not rows:
            raise CoinExAPIError(f"CoinEx returned no candles for {market} ({period}).")

        records: list[dict[str, Any]] = []
        for row in rows:
            timestamp_ms = self._normalize_timestamp_ms(int(row["created_at"]))
            records.append(
                {
                    "market": row["market"],
                    "timestamp": pd.to_datetime(timestamp_ms, unit="ms", utc=True),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                    "value": float(row["value"]),
                }
            )

        frame = (
            pd.DataFrame.from_records(records)
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
        )
        frame.reset_index(drop=True, inplace=True)

        if closed_only:
            now = datetime.now(timezone.utc)
            period_seconds = TIMEFRAME_SECONDS[period]
            candle_end = frame["timestamp"] + pd.to_timedelta(period_seconds, unit="s")
            frame = frame.loc[candle_end <= now].copy()
            frame.reset_index(drop=True, inplace=True)

        if frame.empty:
            raise CoinExAPIError(f"No closed candles available for {market} ({period}).")
        return frame

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        try:
            return await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise CoinExAPIError(f"CoinEx connection failed: {exc}") from exc

    @staticmethod
    def _normalize_timestamp_ms(value: int) -> int:
        while value > 10_000_000_000_000:
            value //= 10
        return value

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise CoinExAPIError(f"CoinEx request failed: {exc}") from exc

        if payload.get("code") != 0:
            raise CoinExAPIError(
                f"CoinEx error code {payload.get('code')}: {payload.get('message', 'Unknown error')}"
            )
        return payload
