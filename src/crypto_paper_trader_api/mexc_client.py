from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import logging
from typing import Any

import httpx
import pandas as pd

from .config import Settings
from .execution_costs import DepthSnapshot, MarketRules

logger = logging.getLogger(__name__)


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
            headers={"User-Agent": "crypto-paper-trader/0.16.17"},
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
        """Return up to ``limit`` candles with bounded historical pagination.

        MEXC accepts at most 1,000 rows per request. The latest page is requested
        without time bounds when the caller did not provide them. Every historical
        page then sends an explicit ``startTime`` and ``endTime`` window. This avoids
        the partial-history/stalled-cursor behavior observed on some Spot pairs when
        only ``endTime`` is supplied.
        """
        if period not in MEXC_INTERVALS:
            raise ValueError(f"Unsupported MEXC timeframe: {period}")
        if not 1 <= limit <= 50_000:
            raise ValueError("limit must be between 1 and 50000")
        if start_time_ms is not None and end_time_ms is not None and start_time_ms > end_time_ms:
            raise ValueError("start_time_ms must be less than or equal to end_time_ms")

        interval_ms = TIMEFRAME_SECONDS[period] * 1000
        cursor_end_ms = int(end_time_ms) if end_time_ms is not None else None
        use_unbounded_latest_page = start_time_ms is None and end_time_ms is None
        frames: list[pd.DataFrame] = []
        collected = 0
        page_number = 0
        empty_windows = 0
        max_pages = max(20, ((limit + 999) // 1000) * 20)

        while collected < limit and page_number < max_pages:
            remaining = limit - collected
            batch_limit = min(1000, max(1, remaining))
            page_number += 1

            if use_unbounded_latest_page and page_number == 1:
                page_start_ms = None
                page_end_ms = None
            else:
                if cursor_end_ms is None:
                    # The first bounded page starts immediately before the oldest row
                    # already collected. This branch is reached only after a valid page.
                    if not frames:
                        raise MEXCAPIError(
                            f"Unable to establish the historical cursor for {market} ({period})."
                        )
                    oldest = pd.Timestamp(
                        pd.concat(frames, ignore_index=True)["timestamp"].min()
                    )
                    cursor_end_ms = int(oldest.timestamp() * 1000) - 1
                page_end_ms = cursor_end_ms
                window_span_ms = interval_ms * batch_limit
                page_start_ms = max(0, page_end_ms - window_span_ms)
                if start_time_ms is not None:
                    page_start_ms = max(int(start_time_ms), page_start_ms)

            try:
                batch = await self.get_candle_page(
                    market=market,
                    period=period,
                    limit=batch_limit,
                    closed_only=closed_only,
                    start_time_ms=page_start_ms,
                    end_time_ms=page_end_ms,
                )
            except MEXCAPIError as exc:
                no_data = (
                    "no candles" in str(exc).lower()
                    or "no closed candles" in str(exc).lower()
                    or "no historical candle page" in str(exc).lower()
                )
                if not no_data:
                    if frames:
                        logger.warning(
                            "MEXC candle pagination stopped after %s page(s) for %s %s: %s",
                            page_number - 1,
                            market,
                            period,
                            exc,
                        )
                        break
                    raise

                if page_start_ms is None:
                    if frames:
                        break
                    raise
                empty_windows += 1
                if page_start_ms <= 0 or (start_time_ms is not None and page_start_ms <= start_time_ms):
                    break
                cursor_end_ms = page_start_ms - 1
                if empty_windows >= 12:
                    break
                continue

            empty_windows = 0
            frames.append(batch)
            merged = (
                pd.concat(frames, ignore_index=True)
                .sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"], keep="last")
            )
            merged.reset_index(drop=True, inplace=True)
            collected = len(merged)

            logger.debug(
                "MEXC candle page market=%s timeframe=%s page=%s rows=%s collected=%s/%s "
                "start_ms=%s end_ms=%s",
                market,
                period,
                page_number,
                len(batch),
                collected,
                limit,
                page_start_ms,
                page_end_ms,
            )

            if collected >= limit:
                break

            oldest_timestamp = pd.Timestamp(batch["timestamp"].min())
            oldest_ms = int(oldest_timestamp.timestamp() * 1000)
            if page_start_ms is None:
                cursor_end_ms = oldest_ms - 1
            else:
                # Advance by the complete requested window, even if MEXC returned a
                # partial page. This prevents sparse or repeated batches from stalling.
                cursor_end_ms = min(oldest_ms - 1, page_start_ms - 1)

            if cursor_end_ms <= 0:
                break
            if start_time_ms is not None and cursor_end_ms < start_time_ms:
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


    async def get_candle_page(
        self,
        market: str,
        period: str,
        *,
        limit: int = 1000,
        closed_only: bool = True,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> pd.DataFrame:
        """Fetch one historical page with a bounded-request fallback.

        Some MEXC Spot pairs return an empty bounded page even though older candles
        exist before ``endTime``. The fallback repeats the request with ``endTime``
        only and still applies the upper bound locally. This method never paginates;
        callers control the historical cursor explicitly.
        """
        if period not in MEXC_INTERVALS:
            raise ValueError(f"Unsupported MEXC timeframe: {period}")
        if not 1 <= limit <= 1000:
            raise ValueError("MEXC candle page limit must be between 1 and 1000")
        if start_time_ms is not None and end_time_ms is not None and start_time_ms > end_time_ms:
            raise ValueError("start_time_ms must be less than or equal to end_time_ms")

        attempts: list[tuple[int | None, int | None]] = [(start_time_ms, end_time_ms)]
        if start_time_ms is not None and end_time_ms is not None:
            attempts.append((None, end_time_ms))

        errors: list[str] = []
        for page_start, page_end in attempts:
            try:
                frame = await self._get_candle_batch(
                    market=market,
                    period=period,
                    limit=limit,
                    closed_only=closed_only,
                    start_time_ms=page_start,
                    end_time_ms=page_end,
                )
                if end_time_ms is not None:
                    upper = pd.to_datetime(int(end_time_ms), unit="ms", utc=True)
                    frame = frame.loc[frame["timestamp"] <= upper].copy()
                frame = (
                    frame.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"], keep="last")
                    .tail(limit)
                    .reset_index(drop=True)
                )
                if not frame.empty:
                    return frame
            except MEXCAPIError as exc:
                errors.append(str(exc))

        detail = "; ".join(dict.fromkeys(errors)) or "no rows returned"
        raise MEXCAPIError(
            f"MEXC returned no historical candle page for {market} ({period}): {detail}"
        )

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

        # Never trust the remote endpoint to honor pagination bounds perfectly.
        # Client-side filtering prevents repeated recent rows from contaminating an
        # older page when a deployment ignores one of the time parameters.
        if start_time_ms is not None:
            lower = pd.to_datetime(int(start_time_ms), unit="ms", utc=True)
            frame = frame.loc[frame["timestamp"] >= lower].copy()
        if end_time_ms is not None:
            upper = pd.to_datetime(int(end_time_ms), unit="ms", utc=True)
            frame = frame.loc[frame["timestamp"] <= upper].copy()
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
