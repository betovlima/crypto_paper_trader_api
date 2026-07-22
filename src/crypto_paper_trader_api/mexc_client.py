from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import pandas as pd

from .config import Settings
from .execution_costs import DepthSnapshot, MarketRules


# Internal timeframe names are retained for database/backward compatibility. MEXC's
# public Spot API currently supports the interval values mapped below.
TIMEFRAME_SECONDS: dict[str, int] = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "30min": 1800,
    "1hour": 3600,
    "4hour": 14400,
    "1day": 86400,
    "1week": 604800,
}

MEXC_INTERVALS: dict[str, str] = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "1hour": "60m",
    "4hour": "4h",
    "1day": "1d",
    "1week": "1W",
}


class MEXCAPIError(RuntimeError):
    """Raised when MEXC returns an invalid or unsuccessful public response."""


class MEXCPublicClient:
    """Read-only client for public MEXC Spot market data.

    The application is PAPER_ONLY. This class intentionally contains no API key,
    account, order, transfer or withdrawal methods.
    """

    def __init__(self, settings: Settings) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.mexc_base_url.rstrip("/"),
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": "crypto-paper-trader/0.16.9"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def get_24h_tickers(self) -> list[dict[str, Any]]:
        payload = await self._get_json("/api/v3/ticker/24hr", {})
        if not isinstance(payload, list):
            raise MEXCAPIError("MEXC returned no 24-hour ticker collection.")
        return [row for row in payload if isinstance(row, dict)]

    async def get_ticker(self, market: str) -> dict[str, Any]:
        payload = await self._get_json("/api/v3/ticker/price", {"symbol": market})
        if not isinstance(payload, dict) or "price" not in payload:
            raise MEXCAPIError(f"MEXC returned no ticker data for {market}.")
        return payload

    async def get_latest_price(self, market: str) -> float:
        ticker = await self.get_ticker(market)
        return float(ticker["price"])

    async def get_market_rules(self, market: str) -> MarketRules:
        """Read public symbol metadata.

        MEXC exposes maker/taker commission fields in exchangeInfo. They are used only
        when explicitly enabled because API-account rates can differ from public or
        promotional rates. The configured API taker baseline remains the safer default.
        """

        payload = await self._get_json("/api/v3/exchangeInfo", {"symbol": market})
        rows: list[dict[str, Any]]
        if isinstance(payload, dict) and isinstance(payload.get("symbols"), list):
            rows = [row for row in payload["symbols"] if row.get("symbol") == market]
        elif isinstance(payload, dict) and payload.get("symbol"):
            rows = [payload]
        elif isinstance(payload, list):
            rows = [row for row in payload if isinstance(row, dict) and row.get("symbol") == market]
        else:
            rows = []

        if not rows:
            raise MEXCAPIError(f"MEXC returned no market rules for {market}.")
        row = rows[0]

        base_step = self._positive_decimal(row.get("baseSizePrecision"), default="0")
        quote_step = self._positive_decimal(
            row.get("quoteAmountPrecision") or row.get("quoteAssetPrecision"),
            default="0",
        )
        base_precision = self._decimal_places(base_step)
        quote_precision = self._decimal_places(quote_step)
        if quote_precision == 0:
            try:
                quote_precision = int(row.get("quotePrecision") or 0)
            except (TypeError, ValueError):
                quote_precision = 0

        return MarketRules(
            market=str(row.get("symbol") or market),
            maker_fee_rate=float(row.get("makerCommission") or 0.0),
            taker_fee_rate=float(row.get("takerCommission") or 0.0),
            min_amount=float(base_step),
            base_currency=str(row.get("baseAsset") or ""),
            quote_currency=str(row.get("quoteAsset") or ""),
            base_precision=base_precision,
            quote_precision=quote_precision,
            status=str(row.get("status") or "UNKNOWN"),
            source="MEXC_PUBLIC_EXCHANGE_INFO",
        )

    async def get_depth_snapshot(self, market: str) -> DepthSnapshot:
        payload = await self._get_json("/api/v3/ticker/bookTicker", {"symbol": market})
        if not isinstance(payload, dict):
            raise MEXCAPIError(f"MEXC returned incomplete depth for {market}.")
        try:
            best_bid = float(payload["bidPrice"])
            best_ask = float(payload["askPrice"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MEXCAPIError(f"MEXC returned incomplete depth for {market}.") from exc
        if best_bid <= 0 or best_ask <= 0 or best_ask < best_bid:
            raise MEXCAPIError(f"MEXC returned invalid bid/ask values for {market}.")
        mid = (best_bid + best_ask) / 2
        spread_rate = (best_ask - best_bid) / mid if mid > 0 else 0.0
        return DepthSnapshot(
            market=market,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid,
            spread_rate=spread_rate,
            updated_at_ms=int(datetime.now(timezone.utc).timestamp() * 1000),
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
        """Return up to ``limit`` candles, transparently paging MEXC batches.

        The MEXC Spot endpoint accepts at most 1,000 candles per request. The
        application may need a longer history for adaptive AI training, so this
        method walks backwards in time and merges as many batches as necessary.
        """
        if period not in MEXC_INTERVALS:
            raise ValueError(f"Unsupported MEXC timeframe: {period}")
        if not 1 <= limit <= 50_000:
            raise ValueError("limit must be between 1 and 50000")

        remaining = limit
        cursor_end_ms = end_time_ms
        frames: list[pd.DataFrame] = []
        oldest_seen_ms: int | None = None

        while remaining > 0:
            batch_limit = min(1000, remaining)
            batch = await self._get_candle_batch(
                market=market,
                period=period,
                limit=batch_limit,
                closed_only=closed_only,
                start_time_ms=start_time_ms,
                end_time_ms=cursor_end_ms,
            )

            if batch.empty:
                break

            frames.append(batch)
            merged = (
                pd.concat(frames, ignore_index=True)
                .sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"], keep="last")
            )
            merged.reset_index(drop=True, inplace=True)

            oldest_timestamp = pd.Timestamp(batch["timestamp"].min())
            oldest_ms = int(oldest_timestamp.timestamp() * 1000)

            if oldest_seen_ms is not None and oldest_ms >= oldest_seen_ms:
                break

            oldest_seen_ms = oldest_ms
            cursor_end_ms = oldest_ms - 1
            remaining = limit - len(merged)

            if start_time_ms is not None and cursor_end_ms < start_time_ms:
                break
            if len(batch) < batch_limit:
                break

        if not frames:
            raise MEXCAPIError(f"MEXC returned no candles for {market} ({period}).")

        result = (
            pd.concat(frames, ignore_index=True)
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .tail(limit)
        )
        result.reset_index(drop=True, inplace=True)
        return result

    async def _get_candle_batch(
        self,
        *,
        market: str,
        period: str,
        limit: int,
        closed_only: bool,
        start_time_ms: int | None,
        end_time_ms: int | None,
    ) -> pd.DataFrame:
        if not 1 <= limit <= 1000:
            raise ValueError("MEXC candle batch limit must be between 1 and 1000")

        params: dict[str, Any] = {
            "symbol": market,
            "interval": MEXC_INTERVALS[period],
            "limit": limit,
        }
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        payload = await self._get_json("/api/v3/klines", params)
        if not isinstance(payload, list) or not payload:
            raise MEXCAPIError(f"MEXC returned no candles for {market} ({period}).")

        records: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, (list, tuple)) or len(row) < 8:
                continue
            timestamp_ms = self._normalize_timestamp_ms(int(row[0]))
            records.append(
                {
                    "market": market,
                    "timestamp": pd.to_datetime(timestamp_ms, unit="ms", utc=True),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "value": float(row[7]),
                    "close_time_ms": self._normalize_timestamp_ms(int(row[6])),
                }
            )
        if not records:
            raise MEXCAPIError(f"MEXC returned invalid candles for {market} ({period}).")

        frame = (
            pd.DataFrame.from_records(records)
            .sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
        )
        frame.reset_index(drop=True, inplace=True)

        if closed_only:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            frame = frame.loc[frame["close_time_ms"] <= now_ms].copy()
            frame.reset_index(drop=True, inplace=True)

        frame.drop(columns=["close_time_ms"], inplace=True, errors="ignore")
        if frame.empty:
            raise MEXCAPIError(f"No closed candles available for {market} ({period}).")
        return frame

    async def _get_json(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MEXCAPIError(f"MEXC request failed: {exc}") from exc

        if isinstance(payload, dict):
            code = payload.get("code")
            # Most market endpoints return raw payloads without a code. Error payloads may
            # return non-zero/non-200 codes with msg/message.
            if code not in (None, 0, 200):
                message = payload.get("msg") or payload.get("message") or "Unknown error"
                raise MEXCAPIError(f"MEXC error code {code}: {message}")
        return payload

    @staticmethod
    def _normalize_timestamp_ms(value: int) -> int:
        while value > 10_000_000_000_000:
            value //= 10
        return value

    @staticmethod
    def _positive_decimal(value: Any, default: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            parsed = Decimal(default)
        return parsed if parsed >= 0 else Decimal(default)

    @staticmethod
    def _decimal_places(value: Decimal) -> int:
        normalized = value.normalize()
        return max(-normalized.as_tuple().exponent, 0)
