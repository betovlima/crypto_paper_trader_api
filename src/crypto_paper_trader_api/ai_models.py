from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .ai_database import AIBase


class AIMarketCandle(AIBase):
    __tablename__ = "ai_market_candles"
    __table_args__ = (
        UniqueConstraint("market", "timeframe", "candle_timestamp", name="uq_ai_candle"),
        Index("ix_ai_candle_lookup", "market", "timeframe", "candle_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    inserted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AIHistorySyncState(AIBase):
    __tablename__ = "ai_history_sync_state"
    __table_args__ = (
        UniqueConstraint("market", "timeframe", name="uq_ai_history_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    target_candles: Mapped[int] = mapped_column(Integer, nullable=False)
    stored_candles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    missing_intervals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
