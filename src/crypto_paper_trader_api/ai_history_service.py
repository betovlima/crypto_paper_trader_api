from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd

from .ai_candle_repository import AICandleRepository
from .ai_database import AISessionLocal, init_ai_database
from .coinex_client import CoinExPublicClient, TIMEFRAME_SECONDS
from .config import Settings

logger = logging.getLogger(__name__)


class AIHistoryService:
    """Builds a persistent, paginated and gap-aware history exclusively for AI."""

    def __init__(self, settings: Settings, client: CoinExPublicClient) -> None:
        self.settings = settings
        self.client = client
        init_ai_database()
        self.repository = AICandleRepository()

    async def synchronize(self, market: str, timeframe: str, latest: pd.DataFrame) -> pd.DataFrame:
        target = self.settings.ai_history_target_candles
        with AISessionLocal() as session:
            self.repository.upsert_frame(session, market, timeframe, latest)
            session.commit()

        calls = 0
        while calls < self.settings.ai_history_backfill_batches_per_cycle:
            with AISessionLocal() as session:
                coverage = self.repository.coverage(session, market, timeframe)
            if int(coverage["stored_candles"]) >= target or coverage["first_candle_at"] is None:
                break
            first = pd.Timestamp(coverage["first_candle_at"])
            end_ms = int((first - pd.Timedelta(milliseconds=1)).timestamp() * 1000)
            try:
                batch = await self.client.get_candles(
                    market,
                    timeframe,
                    limit=min(1000, target - int(coverage["stored_candles"])),
                    closed_only=True,
                    end_time_ms=end_ms,
                )
            except Exception as exc:
                logger.warning("AI history backfill stopped for %s %s: %s", market, timeframe, exc)
                with AISessionLocal() as session:
                    self.repository.save_state(session, market, timeframe, target, "PARTIAL", error=str(exc))
                    session.commit()
                break
            if batch.empty or batch["timestamp"].min() >= first:
                break
            with AISessionLocal() as session:
                self.repository.upsert_frame(session, market, timeframe, batch)
                session.commit()
            calls += 1

        with AISessionLocal() as session:
            frame = self.repository.load_frame(session, market, timeframe, target)
            missing = self._count_missing(frame, timeframe)
            status = "READY" if len(frame) >= min(target, self.settings.ai_pattern_min_training_rows) else "BUILDING"
            self.repository.save_state(session, market, timeframe, target, status, missing=missing)
            session.commit()
        return frame

    @staticmethod
    def _count_missing(frame: pd.DataFrame, timeframe: str) -> int:
        if len(frame) < 2:
            return 0
        expected = TIMEFRAME_SECONDS[timeframe]
        gaps = frame["timestamp"].sort_values().diff().dt.total_seconds().dropna()
        return int(sum(max(0, round(seconds / expected) - 1) for seconds in gaps))
