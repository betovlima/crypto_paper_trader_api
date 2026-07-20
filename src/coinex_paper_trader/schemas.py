from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .strategy_codes import ACTIVE_STRATEGY_CODES
from .trading_profiles import DEFAULT_TRADING_PROFILE, TRADING_PROFILES

SUPPORTED_TIMEFRAMES = {
    "1min",
    "3min",
    "5min",
    "15min",
    "30min",
    "1hour",
    "2hour",
    "4hour",
    "6hour",
    "12hour",
    "1day",
}


class ExperimentCreate(BaseModel):
    market: str = Field(default="BTCUSDT", min_length=3, max_length=32)
    duration_hours: float = Field(default=24.0, gt=0, le=168)
    initial_capital: float = Field(default=1000.0, gt=0)
    trading_profile: str = DEFAULT_TRADING_PROFILE
    execution_timeframe: str = "1hour"
    trend_timeframe: str = "4hour"

    @field_validator("market")
    @classmethod
    def normalize_market(cls, value: str) -> str:
        cleaned = value.strip().upper()
        if not cleaned.isalnum():
            raise ValueError("Market must contain only letters and numbers.")
        return cleaned


    @field_validator("trading_profile")
    @classmethod
    def validate_trading_profile(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in TRADING_PROFILES:
            raise ValueError(f"Unsupported trading profile: {value}")
        return normalized

    @field_validator("execution_timeframe", "trend_timeframe")
    @classmethod
    def validate_timeframe(cls, value: str) -> str:
        if value not in SUPPORTED_TIMEFRAMES:
            raise ValueError(f"Unsupported timeframe: {value}")
        return value


class ExperimentResponse(BaseModel):
    id: str
    market: str
    trading_profile: str
    execution_timeframe: str
    trend_timeframe: str
    duration_hours: float
    status: str
    started_at: datetime
    scheduled_end_at: datetime
    finished_at: datetime | None
    last_processed_candle_at: datetime | None
    last_market_update_at: datetime | None
    next_analysis_at: datetime | None
    last_cycle_at: datetime | None
    recovery_status: str
    recovery_started_at: datetime | None
    recovery_completed_at: datetime | None
    recovered_candle_count: int
    recovered_trade_count: int
    recovery_message: str | None
    initial_capital: float
    cash_balance: float
    asset_quantity: float
    average_entry_price: float | None
    entry_market_price: float | None
    entry_execution_price: float | None
    entry_fee_paid: float
    entry_time: datetime | None
    last_price: float | None
    best_bid: float | None
    best_ask: float | None
    last_atr_14: float | None
    last_market_event: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    trailing_stop_price: float | None
    break_even_activated: bool
    vip_level: str
    maker_fee_rate: float
    taker_fee_rate: float
    fee_source: str
    min_market_amount: float | None
    base_currency: str | None
    quote_currency: str | None
    last_spread_rate: float
    average_spread_rate: float
    total_fees: float
    total_spread_cost: float
    total_slippage_cost: float
    total_transaction_costs: float
    realized_pnl: float
    final_capital: float | None
    buy_and_hold_current_capital: float | None
    buy_and_hold_final_capital: float | None
    max_drawdown_pct: float
    model_name: str
    model_version: str
    error_message: str | None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["PAPER_ONLY"] = "PAPER_ONLY"
    database: str
    worker_running: bool


class PublicConfiguration(BaseModel):
    mode: Literal["PAPER_ONLY"] = "PAPER_ONLY"
    exchange: str = "CoinEx"
    market_type: str = "Spot"
    fees_affect_signals: bool = False
    downtime_recovery_enabled: bool = True
    active_strategy_codes: list[str] = list(ACTIVE_STRATEGY_CODES)
    trading_profiles: list[dict[str, Any]]
    strategy_catalog: list[dict[str, str]]
    default_market: str
    default_execution_timeframe: str
    default_trend_timeframe: str
    default_duration_hours: float
    default_initial_capital: float
    vip_level: str
    maker_fee_rate: float
    taker_fee_rate: float
    cet_fee_discount_enabled: bool
    fallback_spread_rate: float
    slippage_rate: float
    estimated_round_trip_cost_rate: float
    position_allocation: float
    buy_probability_threshold: float
    sell_probability_threshold: float
    min_technical_confirmations: int
    stop_atr_multiplier: float
    stop_loss_min_pct: float
    stop_loss_max_pct: float
    reward_risk_ratio: float
    take_profit_atr_multiplier: float
    trailing_atr_multiplier: float
    trailing_activation_r: float
    break_even_activation_r: float
    max_holding_hours: float
    max_daily_loss_pct: float
    ema9_period: int
