from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .ai_database import AIBase


class AIOpportunitySnapshot(AIBase):
    __tablename__ = "ai_opportunity_snapshots"
    __table_args__ = (
        UniqueConstraint("scan_id", "market", name="uq_ai_opportunity_scan_market"),
        Index("ix_ai_opportunity_latest", "scanned_at", "rank"),
        Index("ix_ai_opportunity_market_time", "market", "scanned_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[str] = mapped_column(String(36), nullable=False)
    market: Mapped[str] = mapped_column(String(32), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    market_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_zone_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_zone_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    upward_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_net_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_volume_24h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spread_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    training_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "rank": self.rank,
            "score": self.score,
            "action": self.action,
            "market_price": self.market_price,
            "entry_zone_low": self.entry_zone_low,
            "entry_zone_high": self.entry_zone_high,
            "trigger_price": self.trigger_price,
            "stop_loss_price": self.stop_loss_price,
            "target_price": self.target_price,
            "regime": self.regime,
            "confidence": self.confidence,
            "upward_probability": self.upward_probability,
            "expected_net_return": self.expected_net_return,
            "quote_volume_24h": self.quote_volume_24h,
            "spread_rate": self.spread_rate,
            "training_samples": self.training_samples,
            "model_version": self.model_version,
            "reason": self.reason,
            "scanned_at": self.scanned_at,
        }


class AIOpportunityScannerState(AIBase):
    __tablename__ = "ai_opportunity_scanner_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="STARTING")
    universe_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scanned_markets: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opportunity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_scan_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_scan_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_public_dict(self, running: bool) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "running": running,
            "status": self.status,
            "universe_size": self.universe_size,
            "scanned_markets": self.scanned_markets,
            "opportunity_count": self.opportunity_count,
            "last_scan_started_at": self.last_scan_started_at,
            "last_scan_completed_at": self.last_scan_completed_at,
            "next_scan_at": self.next_scan_at,
            "last_error": self.last_error,
        }
