from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from .ai_models import AIHistorySyncState, AIMarketCandle


class AICandleRepository:
    def upsert_frame(self, session: Session, market: str, timeframe: str, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0

        normalized = frame.copy()
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"],
            utc=True,
            errors="raise",
        )

        now = datetime.now(timezone.utc)
        rows = []
        for row in normalized.itertuples(index=False):
            ts = pd.Timestamp(row.timestamp).tz_convert("UTC").to_pydatetime()
            rows.append(
                {
                    "market": market,
                    "timeframe": timeframe,
                    "candle_timestamp": ts,
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume),
                    "value": float(getattr(row, "value", 0.0)),
                    "inserted_at": now,
                }
            )

        # SQLite commonly limits a statement to 999 bound variables. Keep batches small.
        for offset in range(0, len(rows), 80):
            batch = rows[offset : offset + 80]
            stmt = insert(AIMarketCandle).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["market", "timeframe", "candle_timestamp"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "value": stmt.excluded.value,
                },
            )
            session.execute(stmt)
        return len(rows)

    def load_frame(self, session: Session, market: str, timeframe: str, limit: int) -> pd.DataFrame:
        rows = (
            session.execute(
                select(AIMarketCandle)
                .where(
                    AIMarketCandle.market == market,
                    AIMarketCandle.timeframe == timeframe,
                )
                .order_by(AIMarketCandle.candle_timestamp.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        rows.reverse()
        return pd.DataFrame(
            [
                {
                    "market": row.market,
                    "timestamp": pd.to_datetime(row.candle_timestamp, utc=True),
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                    "value": row.value,
                }
                for row in rows
            ]
        )

    def coverage(self, session: Session, market: str, timeframe: str) -> dict[str, object]:
        count, first_ts, last_ts = session.execute(
            select(
                func.count(AIMarketCandle.id),
                func.min(AIMarketCandle.candle_timestamp),
                func.max(AIMarketCandle.candle_timestamp),
            ).where(
                AIMarketCandle.market == market,
                AIMarketCandle.timeframe == timeframe,
            )
        ).one()
        return {
            "stored_candles": int(count or 0),
            "first_candle_at": first_ts,
            "last_candle_at": last_ts,
        }

    def save_state(
        self,
        session: Session,
        market: str,
        timeframe: str,
        target: int,
        status: str,
        missing: int = 0,
        error: str | None = None,
    ) -> AIHistorySyncState:
        coverage = self.coverage(session, market, timeframe)
        state = session.scalar(
            select(AIHistorySyncState).where(
                AIHistorySyncState.market == market,
                AIHistorySyncState.timeframe == timeframe,
            )
        )
        if state is None:
            state = AIHistorySyncState(
                market=market,
                timeframe=timeframe,
                target_candles=target,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(state)
        state.target_candles = target
        state.stored_candles = int(coverage["stored_candles"])
        state.first_candle_at = coverage["first_candle_at"]
        state.last_candle_at = coverage["last_candle_at"]
        state.missing_intervals = missing
        state.status = status
        state.last_error = error
        state.updated_at = datetime.now(timezone.utc)
        return state
