from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    market: Mapped[str] = mapped_column(String(32), index=True)
    trading_profile: Mapped[str] = mapped_column(String(32), default="BALANCED_INTRADAY")
    execution_timeframe: Mapped[str] = mapped_column(String(16))
    trend_timeframe: Mapped[str] = mapped_column(String(16))
    duration_hours: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24), index=True, default="PENDING")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    scheduled_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_processed_candle_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_market_update_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recovery_status: Mapped[str] = mapped_column(String(24), default="IDLE")
    recovery_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovery_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_candle_count: Mapped[int] = mapped_column(Integer, default=0)
    recovered_trade_count: Mapped[int] = mapped_column(Integer, default=0)
    recovery_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    initial_capital: Mapped[float] = mapped_column(Float)
    cash_balance: Mapped[float] = mapped_column(Float)
    asset_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    average_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_market_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_fee_paid: Mapped[float] = mapped_column(Float, default=0.0)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    initial_risk_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    break_even_activated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_market_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    highest_price_since_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    vip_level: Mapped[str] = mapped_column(String(16), default="VIP0")
    maker_fee_rate: Mapped[float] = mapped_column(Float, default=0.002)
    taker_fee_rate: Mapped[float] = mapped_column(Float, default=0.002)
    fee_source: Mapped[str] = mapped_column(String(64), default="CONFIG_VIP0")
    min_market_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    base_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quote_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_spread_rate: Mapped[float] = mapped_column(Float, default=0.0)
    average_spread_rate: Mapped[float] = mapped_column(Float, default=0.0)
    spread_observations: Mapped[int] = mapped_column(Integer, default=0)

    total_fees: Mapped[float] = mapped_column(Float, default=0.0)
    total_spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    final_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_and_hold_current_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_and_hold_final_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_equity: Mapped[float] = mapped_column(Float)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_market_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    model_name: Mapped[str] = mapped_column(String(64), default="XGBoost")
    model_version: Mapped[str] = mapped_column(String(32), default="1.1")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    decisions: Mapped[list[DecisionSnapshot]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    trades: Mapped[list[SimulatedTrade]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    equity_snapshots: Mapped[list[EquitySnapshot]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    candles: Mapped[list[Candle]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )
    market_snapshots: Mapped[list[MarketSnapshot]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )

    @property
    def has_open_position(self) -> bool:
        return self.asset_quantity > 0

    @property
    def current_equity(self) -> float:
        if self.last_price is None:
            return self.cash_balance
        return self.cash_balance + self.asset_quantity * self.last_price

    @property
    def total_transaction_costs(self) -> float:
        return self.total_fees + self.total_spread_cost + self.total_slippage_cost

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "market": self.market,
            "trading_profile": self.trading_profile,
            "execution_timeframe": self.execution_timeframe,
            "trend_timeframe": self.trend_timeframe,
            "duration_hours": self.duration_hours,
            "status": self.status,
            "started_at": self.started_at,
            "scheduled_end_at": self.scheduled_end_at,
            "finished_at": self.finished_at,
            "last_processed_candle_at": self.last_processed_candle_at,
            "last_market_update_at": self.last_market_update_at,
            "next_analysis_at": self.next_analysis_at,
            "last_cycle_at": self.last_cycle_at,
            "recovery_status": self.recovery_status,
            "recovery_started_at": self.recovery_started_at,
            "recovery_completed_at": self.recovery_completed_at,
            "recovered_candle_count": self.recovered_candle_count,
            "recovered_trade_count": self.recovered_trade_count,
            "recovery_message": self.recovery_message,
            "initial_capital": self.initial_capital,
            "cash_balance": self.cash_balance,
            "asset_quantity": self.asset_quantity,
            "average_entry_price": self.average_entry_price,
            "entry_market_price": self.entry_market_price,
            "entry_execution_price": self.entry_execution_price,
            "entry_fee_paid": self.entry_fee_paid,
            "entry_time": self.entry_time,
            "last_price": self.last_price,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "last_atr_14": self.last_atr_14,
            "last_market_event": self.last_market_event,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "trailing_stop_price": self.trailing_stop_price,
            "break_even_activated": self.break_even_activated,
            "vip_level": self.vip_level,
            "maker_fee_rate": self.maker_fee_rate,
            "taker_fee_rate": self.taker_fee_rate,
            "fee_source": self.fee_source,
            "min_market_amount": self.min_market_amount,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "last_spread_rate": self.last_spread_rate,
            "average_spread_rate": self.average_spread_rate,
            "total_fees": self.total_fees,
            "total_spread_cost": self.total_spread_cost,
            "total_slippage_cost": self.total_slippage_cost,
            "total_transaction_costs": self.total_transaction_costs,
            "realized_pnl": self.realized_pnl,
            "final_capital": self.final_capital,
            "buy_and_hold_current_capital": self.buy_and_hold_current_capital,
            "buy_and_hold_final_capital": self.buy_and_hold_final_capital,
            "max_drawdown_pct": self.max_drawdown_pct,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "error_message": self.error_message,
        }


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "market", "timeframe", "timestamp", name="uq_candle_experiment"
        ),
        Index("ix_candles_experiment_time", "experiment_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    market: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(16))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=True)

    experiment: Mapped[Experiment] = relationship(back_populates="candles")


class DecisionSnapshot(Base):
    __tablename__ = "decision_snapshots"
    __table_args__ = (
        UniqueConstraint("experiment_id", "candle_timestamp", name="uq_decision_candle"),
        Index("ix_decision_experiment_time", "experiment_id", "candle_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    market_price: Mapped[float] = mapped_column(Float)
    candle_high: Mapped[float] = mapped_column(Float)
    candle_low: Mapped[float] = mapped_column(Float)

    ema_20: Mapped[float] = mapped_column(Float)
    ema_50: Mapped[float] = mapped_column(Float)
    ema_200: Mapped[float] = mapped_column(Float)
    rsi_14: Mapped[float] = mapped_column(Float)
    atr_14: Mapped[float] = mapped_column(Float)
    adx_14: Mapped[float] = mapped_column(Float)
    average_volume_20: Mapped[float] = mapped_column(Float)
    relative_volume: Mapped[float] = mapped_column(Float)
    volatility_20: Mapped[float] = mapped_column(Float)
    return_1: Mapped[float] = mapped_column(Float)
    return_3: Mapped[float] = mapped_column(Float)
    return_6: Mapped[float] = mapped_column(Float)

    trend_close: Mapped[float] = mapped_column(Float)
    trend_ema_20: Mapped[float] = mapped_column(Float)
    trend_ema_50: Mapped[float] = mapped_column(Float)
    trend_ema_200: Mapped[float] = mapped_column(Float)
    trend_rsi_14: Mapped[float] = mapped_column(Float)
    trend_adx_14: Mapped[float] = mapped_column(Float)

    upward_probability: Mapped[float] = mapped_column(Float)
    downward_probability: Mapped[float] = mapped_column(Float)
    expected_return: Mapped[float] = mapped_column(Float)
    model_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_rows: Mapped[int] = mapped_column(Integer, default=0)
    model_top_features: Mapped[str] = mapped_column(Text, default="")

    maker_fee_rate: Mapped[float] = mapped_column(Float)
    taker_fee_rate: Mapped[float] = mapped_column(Float)
    spread_rate: Mapped[float] = mapped_column(Float)
    slippage_rate: Mapped[float] = mapped_column(Float)
    estimated_round_trip_cost_rate: Mapped[float] = mapped_column(Float)
    required_gross_return: Mapped[float] = mapped_column(Float)
    active_stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    technical_signal: Mapped[str] = mapped_column(String(16))
    model_signal: Mapped[str] = mapped_column(String(16))
    final_signal: Mapped[str] = mapped_column(String(16))
    technical_confirmations: Mapped[int] = mapped_column(Integer)
    decision_reason: Mapped[str] = mapped_column(Text)
    position_before: Mapped[str] = mapped_column(String(16))
    action_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    experiment: Mapped[Experiment] = relationship(back_populates="decisions")

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class SimulatedTrade(Base):
    __tablename__ = "simulated_trades"
    __table_args__ = (Index("ix_trades_experiment_time", "experiment_id", "executed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("decision_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    side: Mapped[str] = mapped_column(String(8))
    order_role: Mapped[str] = mapped_column(String(16), default="TAKER")
    market_price: Mapped[float] = mapped_column(Float)
    execution_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    gross_notional: Mapped[float] = mapped_column(Float)
    fee_rate: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    spread_rate: Mapped[float] = mapped_column(Float)
    spread_cost: Mapped[float] = mapped_column(Float)
    slippage_rate: Mapped[float] = mapped_column(Float)
    slippage_cost: Mapped[float] = mapped_column(Float)
    total_transaction_cost: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl_before_exit_costs: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_after: Mapped[float] = mapped_column(Float)
    asset_quantity_after: Mapped[float] = mapped_column(Float)
    equity_after: Mapped[float] = mapped_column(Float)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text)

    experiment: Mapped[Experiment] = relationship(back_populates="trades")

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (Index("ix_equity_experiment_time", "experiment_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    market_price: Mapped[float] = mapped_column(Float)
    cash_balance: Mapped[float] = mapped_column(Float)
    asset_quantity: Mapped[float] = mapped_column(Float)
    position_value: Mapped[float] = mapped_column(Float)
    total_equity: Mapped[float] = mapped_column(Float)
    drawdown_pct: Mapped[float] = mapped_column(Float)
    has_position: Mapped[bool] = mapped_column(Boolean)

    experiment: Mapped[Experiment] = relationship(back_populates="equity_snapshots")

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (Index("ix_market_snapshot_experiment_time", "experiment_id", "observed_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    market_price: Mapped[float] = mapped_column(Float)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_rate: Mapped[float] = mapped_column(Float, default=0.0)
    cash_balance: Mapped[float] = mapped_column(Float)
    asset_quantity: Mapped[float] = mapped_column(Float)
    position_value: Mapped[float] = mapped_column(Float)
    total_equity: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    has_position: Mapped[bool] = mapped_column(Boolean)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_stop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_take_profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), default="PRICE_UPDATE")
    status_message: Mapped[str] = mapped_column(Text, default="Market updated")
    last_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    experiment: Mapped[Experiment] = relationship(back_populates="market_snapshots")

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class StrategyAccount(Base):
    """Independent simulated portfolio and state for one strategy."""

    __tablename__ = "strategy_accounts"
    __table_args__ = (
        UniqueConstraint("experiment_id", "strategy_code", name="uq_strategy_account"),
        Index("ix_strategy_accounts_experiment", "experiment_id", "strategy_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    strategy_code: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE")

    initial_capital: Mapped[float] = mapped_column(Float)
    cash_balance: Mapped[float] = mapped_column(Float)
    asset_quantity: Mapped[float] = mapped_column(Float, default=0.0)
    average_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_market_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_fee_paid: Mapped[float] = mapped_column(Float, default=0.0)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    initial_risk_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    highest_price_since_entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    break_even_activated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)

    total_fees: Mapped[float] = mapped_column(Float, default=0.0)
    total_spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    final_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_equity: Mapped[float] = mapped_column(Float)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    consecutive_losses: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_signals: Mapped[int] = mapped_column(Integer, default=0)
    last_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_status_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    ema_9: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_9_previous: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_9_slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_9_direction: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    setup_status: Mapped[str] = mapped_column(String(24), default="IDLE")
    setup_candle_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    setup_candle_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_candle_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_setup_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_setup_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_setup_event_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def has_open_position(self) -> bool:
        return float(self.asset_quantity or 0.0) > 0

    @property
    def total_transaction_costs(self) -> float:
        return (
            float(self.total_fees or 0.0)
            + float(self.total_spread_cost or 0.0)
            + float(self.total_slippage_cost or 0.0)
        )

    def current_equity(self, market_price: float | None) -> float:
        cash = float(self.cash_balance or 0.0)
        if market_price is None:
            return cash
        return cash + float(self.asset_quantity or 0.0) * market_price

    def to_public_dict(self, market_price: float | None = None) -> dict[str, Any]:
        equity = (
            self.final_capital
            if self.final_capital is not None
            else self.current_equity(market_price)
        )
        net_return = (
            equity / self.initial_capital - 1
            if self.initial_capital > 0 and equity is not None
            else 0.0
        )
        return {
            "id": self.id,
            "experiment_id": self.experiment_id,
            "strategy_code": self.strategy_code,
            "display_name": self.display_name,
            "status": self.status,
            "initial_capital": self.initial_capital,
            "cash_balance": self.cash_balance,
            "asset_quantity": self.asset_quantity,
            "average_entry_price": self.average_entry_price,
            "entry_market_price": self.entry_market_price,
            "entry_execution_price": self.entry_execution_price,
            "entry_fee_paid": self.entry_fee_paid,
            "entry_time": self.entry_time,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "trailing_stop_price": self.trailing_stop_price,
            "break_even_activated": self.break_even_activated,
            "last_atr_14": self.last_atr_14,
            "total_fees": self.total_fees,
            "total_spread_cost": self.total_spread_cost,
            "total_slippage_cost": self.total_slippage_cost,
            "total_transaction_costs": self.total_transaction_costs,
            "realized_pnl": self.realized_pnl,
            "current_equity": equity,
            "final_capital": self.final_capital,
            "net_return": net_return,
            "max_drawdown_pct": self.max_drawdown_pct,
            "consecutive_losses": self.consecutive_losses,
            "cooldown_until": self.cooldown_until,
            "rejected_signals": self.rejected_signals,
            "has_open_position": self.has_open_position,
            "last_event": self.last_event,
            "last_status_message": self.last_status_message,
            "ema_9": self.ema_9,
            "ema_9_previous": self.ema_9_previous,
            "ema_9_slope": self.ema_9_slope,
            "ema_9_direction": self.ema_9_direction,
            "setup_status": self.setup_status,
            "setup_candle_timestamp": self.setup_candle_timestamp,
            "setup_candle_high": self.setup_candle_high,
            "setup_candle_low": self.setup_candle_low,
            "entry_trigger_price": self.entry_trigger_price,
            "initial_setup_stop_price": self.initial_setup_stop_price,
            "setup_target_price": self.setup_target_price,
            "setup_cancel_reason": self.setup_cancel_reason,
            "last_setup_event": self.last_setup_event,
            "last_setup_event_reason": self.last_setup_event_reason,
        }


class StrategyDecisionSnapshot(Base):
    __tablename__ = "strategy_decision_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "strategy_code", "candle_timestamp", name="uq_strategy_decision"
        ),
        Index(
            "ix_strategy_decisions_experiment_time",
            "experiment_id",
            "strategy_code",
            "candle_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    strategy_account_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_accounts.id", ondelete="CASCADE")
    )
    strategy_code: Mapped[str] = mapped_column(String(64))
    candle_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    market_price: Mapped[float] = mapped_column(Float)
    candle_high: Mapped[float] = mapped_column(Float)
    candle_low: Mapped[float] = mapped_column(Float)

    fast_ema_period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slow_ema_period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regime_ema_period: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fast_ema_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    slow_ema_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime_ema_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    ema_9: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_9_previous: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_9_slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_200: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    adx_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_volume_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatility_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_3: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_6: Mapped[float | None] = mapped_column(Float, nullable=True)

    trend_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_ema_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_ema_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_ema_200: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    trend_adx_14: Mapped[float | None] = mapped_column(Float, nullable=True)

    upward_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    downward_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_roc_auc: Mapped[float | None] = mapped_column(Float, nullable=True)
    training_rows: Mapped[int] = mapped_column(Integer, default=0)
    model_top_features: Mapped[str] = mapped_column(Text, default="")

    maker_fee_rate: Mapped[float] = mapped_column(Float)
    taker_fee_rate: Mapped[float] = mapped_column(Float)
    spread_rate: Mapped[float] = mapped_column(Float)
    slippage_rate: Mapped[float] = mapped_column(Float)
    estimated_round_trip_cost_rate: Mapped[float] = mapped_column(Float)
    required_gross_return: Mapped[float] = mapped_column(Float)

    setup_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    setup_candle_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    setup_candle_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_gross_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    reward_risk_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    technical_signal: Mapped[str] = mapped_column(String(24))
    model_signal: Mapped[str] = mapped_column(String(24))
    final_signal: Mapped[str] = mapped_column(String(24))
    technical_confirmations: Mapped[int] = mapped_column(Integer, default=0)
    decision_reason: Mapped[str] = mapped_column(Text)
    position_before: Mapped[str] = mapped_column(String(16))
    action_executed: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class StrategySimulatedTrade(Base):
    __tablename__ = "strategy_simulated_trades"
    __table_args__ = (
        Index(
            "ix_strategy_trades_experiment_time",
            "experiment_id",
            "strategy_code",
            "executed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    strategy_account_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_accounts.id", ondelete="CASCADE")
    )
    strategy_code: Mapped[str] = mapped_column(String(64))
    decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_decision_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    side: Mapped[str] = mapped_column(String(8))
    order_role: Mapped[str] = mapped_column(String(16), default="TAKER")
    market_price: Mapped[float] = mapped_column(Float)
    execution_price: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    gross_notional: Mapped[float] = mapped_column(Float)
    fee_rate: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    spread_rate: Mapped[float] = mapped_column(Float)
    spread_cost: Mapped[float] = mapped_column(Float)
    slippage_rate: Mapped[float] = mapped_column(Float)
    slippage_cost: Mapped[float] = mapped_column(Float)
    total_transaction_cost: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_pnl_before_exit_costs: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_after: Mapped[float] = mapped_column(Float)
    asset_quantity_after: Mapped[float] = mapped_column(Float)
    equity_after: Mapped[float] = mapped_column(Float)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    is_recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class StrategyEquitySnapshot(Base):
    __tablename__ = "strategy_equity_snapshots"
    __table_args__ = (
        Index(
            "ix_strategy_equity_experiment_time",
            "experiment_id",
            "strategy_code",
            "timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    strategy_account_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_accounts.id", ondelete="CASCADE")
    )
    strategy_code: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    market_price: Mapped[float] = mapped_column(Float)
    cash_balance: Mapped[float] = mapped_column(Float)
    asset_quantity: Mapped[float] = mapped_column(Float)
    position_value: Mapped[float] = mapped_column(Float)
    total_equity: Mapped[float] = mapped_column(Float)
    drawdown_pct: Mapped[float] = mapped_column(Float)
    has_position: Mapped[bool] = mapped_column(Boolean)

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


class StrategyMarketSnapshot(Base):
    __tablename__ = "strategy_market_snapshots"
    __table_args__ = (
        Index(
            "ix_strategy_market_experiment_time",
            "experiment_id",
            "strategy_code",
            "observed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"))
    strategy_account_id: Mapped[int] = mapped_column(
        ForeignKey("strategy_accounts.id", ondelete="CASCADE")
    )
    strategy_code: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    market_price: Mapped[float] = mapped_column(Float)
    best_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    best_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_rate: Mapped[float] = mapped_column(Float, default=0.0)
    cash_balance: Mapped[float] = mapped_column(Float)
    asset_quantity: Mapped[float] = mapped_column(Float)
    position_value: Mapped[float] = mapped_column(Float)
    total_equity: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    drawdown_pct: Mapped[float] = mapped_column(Float, default=0.0)
    has_position: Mapped[bool] = mapped_column(Boolean)
    stop_loss_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trailing_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_stop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_take_profit_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), default="PRICE_UPDATE")
    status_message: Mapped[str] = mapped_column(Text, default="Market data updated.")
    last_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_analysis_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_dict(self) -> dict[str, Any]:
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}
