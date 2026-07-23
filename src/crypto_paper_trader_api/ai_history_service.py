from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .ai_candle_repository import AICandleRepository
from .ai_database import AISessionLocal, init_ai_database
from .config import Settings
from .mexc_client import MEXCAPIError, MEXCPublicClient, TIMEFRAME_SECONDS

logger = logging.getLogger(__name__)


class AIHistoryService:
    """Build a persistent, paginated and observable history for AI models.

    The service owns the historical cursor. It does not depend on a new closed candle:
    callers may invoke it from the normal strategy cycle, the background retry loop or
    an administrative retry endpoint. Every attempt persists diagnostics in SQLite.
    """

    def __init__(self, settings: Settings, client: MEXCPublicClient) -> None:
        self.settings = settings
        self.client = client
        init_ai_database()
        self.repository = AICandleRepository()

    async def synchronize(
        self,
        market: str,
        timeframe: str,
        latest: pd.DataFrame,
        minimum_candles: int | None = None,
    ) -> pd.DataFrame:
        latest = self._normalize_timestamp_column(latest)
        target = max(
            self.settings.ai_history_target_candles,
            int(minimum_candles or 0),
        )
        attempt_started_at = datetime.now(timezone.utc)
        retry_at = attempt_started_at + timedelta(
            seconds=self.settings.ai_history_backfill_retry_seconds
        )

        with AISessionLocal() as session:
            before = self.repository.coverage(session, market, timeframe)
            self.repository.upsert_frame(session, market, timeframe, latest)
            session.commit()

        pages_attempted = 0
        pages_succeeded = 0
        empty_windows = 0
        last_error: str | None = None
        exhausted = False
        interval_ms = TIMEFRAME_SECONDS[timeframe] * 1000
        base_window_candles = int(self.settings.ai_history_backfill_window_candles)

        while pages_attempted < self.settings.ai_history_backfill_batches_per_cycle:
            with AISessionLocal() as session:
                coverage = self.repository.coverage(session, market, timeframe)

            stored = int(coverage["stored_candles"])
            first_value = coverage["first_candle_at"]
            if stored >= target or first_value is None:
                break

            first = self._as_utc_timestamp(first_value)
            page_end_ms = int((first - pd.Timedelta(milliseconds=1)).timestamp() * 1000)

            # Start with a full 1,000-candle window even when only a few rows remain.
            # Sparse pairs may have long inactive periods, so every empty window doubles
            # the lookback span. This avoids the old fixed 12-window/partial-history stall.
            expansion = min(empty_windows, 8)
            window_candles = base_window_candles * (2**expansion)
            page_start_ms = max(0, page_end_ms - interval_ms * window_candles)
            pages_attempted += 1

            try:
                batch = await self.client.get_candle_page(
                    market,
                    timeframe,
                    limit=1000,
                    closed_only=True,
                    start_time_ms=page_start_ms,
                    end_time_ms=page_end_ms,
                )
                batch = self._normalize_timestamp_column(batch)
                batch = batch.loc[batch["timestamp"] < first].copy()
                batch = (
                    batch.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"], keep="last")
                    .reset_index(drop=True)
                )
            except MEXCAPIError as exc:
                batch = pd.DataFrame()
                last_error = self._safe_error(exc)
            except Exception as exc:  # pragma: no cover - defensive boundary
                logger.exception("Unexpected AI history backfill failure for %s %s", market, timeframe)
                last_error = self._safe_error(exc)
                break

            if batch.empty:
                empty_windows += 1
                logger.info(
                    "AI history empty window market=%s timeframe=%s attempt=%s start_ms=%s end_ms=%s",
                    market,
                    timeframe,
                    pages_attempted,
                    page_start_ms,
                    page_end_ms,
                )
                if page_start_ms <= 0:
                    exhausted = True
                    break
                if empty_windows >= self.settings.ai_history_backfill_max_empty_windows:
                    exhausted = True
                    break

                # Persist a synthetic cursor marker only through diagnostics. The next
                # request expands from the same oldest stored candle, covering a wider
                # historical range without inserting fake market data.
                continue

            empty_windows = 0
            pages_succeeded += 1
            last_error = None
            with AISessionLocal() as session:
                previous_count = int(
                    self.repository.coverage(session, market, timeframe)["stored_candles"]
                )
                self.repository.upsert_frame(session, market, timeframe, batch)
                session.commit()
                new_count = int(
                    self.repository.coverage(session, market, timeframe)["stored_candles"]
                )

            logger.info(
                "AI history page market=%s timeframe=%s rows=%s new=%s stored=%s/%s",
                market,
                timeframe,
                len(batch),
                max(0, new_count - previous_count),
                new_count,
                target,
            )

            # A repeated page must not spin forever. The next attempt will use the
            # background retry schedule and a fresh MEXC request.
            if new_count <= previous_count:
                last_error = "MEXC_HISTORY_PAGE_REPEATED_NO_NEW_CANDLES"
                break

        with AISessionLocal() as session:
            frame = self.repository.load_frame(session, market, timeframe, target)
            frame = self._normalize_timestamp_column(frame)
            missing = self._count_missing(frame, timeframe)
            after = self.repository.coverage(session, market, timeframe)
            candles_added = max(
                0,
                int(after["stored_candles"]) - int(before["stored_candles"]),
            )

            if len(frame) >= target:
                status = "READY"
                next_retry_at = None
                state_error = None
            elif last_error:
                status = "PARTIAL"
                next_retry_at = retry_at
                state_error = last_error
            elif exhausted:
                status = "EXHAUSTED"
                next_retry_at = retry_at
                state_error = "MEXC_RETURNED_NO_OLDER_CANDLES_IN_SEARCH_RANGE"
            else:
                status = "BUILDING"
                next_retry_at = retry_at
                state_error = None

            self.repository.save_state(
                session,
                market,
                timeframe,
                target,
                status,
                missing=missing,
                error=state_error,
                pages_attempted=pages_attempted,
                pages_succeeded=pages_succeeded,
                candles_added=candles_added,
                empty_windows=empty_windows,
                last_attempt_at=attempt_started_at,
                next_retry_at=next_retry_at,
            )
            session.commit()
        return frame

    def diagnostics(self, market: str, timeframe: str) -> dict[str, Any]:
        with AISessionLocal() as session:
            return self.repository.state_snapshot(session, market, timeframe)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = f"{type(exc).__name__}: {exc}".replace("\n", " ").strip()
        return text[:500]

    @staticmethod
    def _as_utc_timestamp(value: object) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            raise ValueError("Candle timestamp cannot be null.")
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")

    @staticmethod
    def _normalize_timestamp_column(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()
        if "timestamp" not in frame.columns:
            raise ValueError("Candle frame must contain a timestamp column.")

        normalized = frame.copy()
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"],
            utc=True,
            errors="raise",
        )
        return normalized

    @staticmethod
    def _count_missing(frame: pd.DataFrame, timeframe: str) -> int:
        if len(frame) < 2:
            return 0
        expected = TIMEFRAME_SECONDS[timeframe]
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        gaps = timestamps.sort_values().diff().dt.total_seconds().dropna()
        return int(sum(max(0, round(seconds / expected) - 1) for seconds in gaps))
