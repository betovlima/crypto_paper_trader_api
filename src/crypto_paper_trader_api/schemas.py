from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .strategy_codes import ACTIVE_STRATEGY_CODES
from .trading_profiles import DEFAULT_TRADING_PROFILE, TRADING_PROFILES

SUPPORTED_TIMEFRAMES = {
    "1min",
    "5min",
    "15min",
    "30min",
    "1hour",
    "4hour",
    "1day",
    "1week",
}


class ExperimentCreate(BaseModel):
    market: str = Field(default="BTCUSDT", min_length=3, max_length=32)
    duration_hours: float = Field(default=24.0, gt=0, le=168)
    initial_capital: float = Field(default=1000.0, gt=0)
    trading_profile: str = DEFAULT_TRADING_PROFILE
    execution_timeframe: str = "30min"
    trend_timeframe: str = "1hour"

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

    @model_validator(mode="after")
    def validate_timeframe_relationship(self) -> "ExperimentCreate":
        timeframe_seconds = {
            "1min": 60,
            "5min": 300,
            "15min": 900,
            "30min": 1800,
            "1hour": 3600,
            "4hour": 14400,
            "1day": 86400,
            "1week": 604800,
        }
        if timeframe_seconds[self.execution_timeframe] < 1800:
            raise ValueError("The minimum intraday decision timeframe is 30 minutes.")
        if timeframe_seconds[self.trend_timeframe] < timeframe_seconds[self.execution_timeframe]:
            raise ValueError(
                "The trend timeframe must be equal to or greater than the decision timeframe."
            )
        return self


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


class RunningExperimentStrategySummary(BaseModel):
    total: int
    active_positions: int
    armed_entries: int
    waiting: int


class RunningExperimentHeaderSummary(BaseModel):
    visible: bool
    experiment_id: str | None = None
    status: str | None = None
    status_tone: str = "idle"
    market: str | None = None
    market_label: str | None = None
    decision_timeframe: str | None = None
    decision_timeframe_label: str | None = None
    trend_timeframe: str | None = None
    trend_timeframe_label: str | None = None
    next_analysis_at: datetime | None = None
    next_analysis_countdown_seconds: int | None = None
    next_analysis_countdown_label: str | None = None
    last_market_update_at: datetime | None = None
    last_market_update_label: str | None = None
    strategy_summary: RunningExperimentStrategySummary | None = None


class StrategyComparisonItem(BaseModel):
    strategy_code: str
    display_name: str
    description: str
    latest_decision: dict[str, Any] | None


class StrategyComparisonResponse(BaseModel):
    experiment_id: str
    market: str
    updated_at: datetime | None
    strategies: list[StrategyComparisonItem]


class StrategyComparisonHistoryItem(BaseModel):
    strategy_code: str
    display_name: str
    decisions: list[dict[str, Any]]


class StrategyComparisonHistoryResponse(BaseModel):
    experiment_id: str
    market: str
    limit_per_strategy: int
    strategies: list[StrategyComparisonHistoryItem]


class AIPatternPerformanceResponse(BaseModel):
    prediction_count: int
    resolved_count: int
    direction_accuracy: float | None
    average_realized_net_return: float | None
    average_reward: float | None


class AIPatternStatusResponse(BaseModel):
    experiment_id: str
    market: str
    mode: str
    model_version: str
    account: dict[str, Any] | None
    latest_decision: dict[str, Any] | None
    performance: AIPatternPerformanceResponse
    history: dict[str, Any] | None = None


class StopRunningExperimentRequest(BaseModel):
    close_open_positions: bool = True


class StopRunningExperimentResponse(BaseModel):
    status: Literal["STOPPED"] = "STOPPED"
    experiment_id: str
    previous_status: str
    stopped_at: datetime
    closed_positions: int
    remaining_open_positions: int
    data_preserved: Literal[True] = True
    ai_scanner_running: bool


class AIOpportunityMarketDiagnostic(BaseModel):
    market: str
    status: str
    action: str | None = None
    downloaded_execution_candles: int = 0
    downloaded_trend_candles: int = 0
    training_samples: int = 0
    required_training_samples: int = 0
    missing_training_samples: int = 0
    selected_training_window: int | None = None
    validation_accuracy: float | None = None
    validation_mae: float | None = None
    regime: str | None = None
    confidence: float | None = None
    upward_probability: float | None = None
    expected_net_return: float | None = None
    score: float | None = None
    risk_reason: str | None = None
    model_version: str | None = None


class AIOpportunityScannerStatus(BaseModel):
    enabled: bool
    running: bool
    status: str
    universe_size: int
    scanned_markets: int
    opportunity_count: int
    last_scan_started_at: datetime | None
    last_scan_completed_at: datetime | None
    next_scan_at: datetime | None
    progress_percent: int = 0
    current_step: int = 0
    total_steps: int = 5
    current_market: str | None = None
    current_market_index: int = 0
    total_markets: int = 0
    analyzed_markets: int = 0
    failed_markets: int = 0
    classified_opportunities: int = 0
    eligible_markets: int = 0
    learning_markets: int = 0
    training_window: int | None = None
    scan_started_at: datetime | None = None
    last_activity_at: datetime | None = None
    last_error: str | None
    market_diagnostics: list[AIOpportunityMarketDiagnostic] = []


class AIOpportunityItem(BaseModel):
    market: str
    rank: int
    score: float
    action: str
    market_price: float
    entry_zone_low: float | None
    entry_zone_high: float | None
    trigger_price: float | None
    stop_loss_price: float | None
    target_price: float | None
    regime: str | None
    confidence: float | None
    upward_probability: float | None
    expected_net_return: float | None
    quote_volume_24h: float
    spread_rate: float
    training_samples: int
    model_version: str
    reason: str
    scanned_at: datetime


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["PAPER_ONLY"] = "PAPER_ONLY"
    database: str
    data_dir: str
    database_exists: bool
    worker_running: bool
    ai_scanner_running: bool
    persistent_storage_configured: bool
    storage_warning: str | None = None


class PublicConfiguration(BaseModel):
    mode: Literal["PAPER_ONLY"] = "PAPER_ONLY"
    exchange: str = "MEXC"
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
    mx_fee_discount_enabled: bool
    fallback_spread_rate: float
    slippage_rate: float
    estimated_round_trip_cost_rate: float
    position_allocation: float
    buy_probability_threshold: float
    sell_probability_threshold: float
    min_technical_confirmations: int
    market_context_lookback: int
    market_context_compression_window: int
    ignition_min_score: float
    exhaustion_max_entry_score: float
    breakout_require_ignition: bool
    crossover_block_exhaustion: bool
    expectancy_min_trades: int
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
    ai_pattern_mode: str
    ai_pattern_horizon_candles: int
    ai_pattern_buy_probability_threshold: float
    ai_pattern_sell_probability_threshold: float
    ai_pattern_min_expected_net_return: float
    ai_pattern_min_confidence: float
    ai_pattern_max_spread_rate: float
    ai_pattern_model_version: str = "AI-PATTERN-v4-MARKET-CONTEXT"
    ai_scanner_enabled: bool
    ai_scanner_interval_seconds: int
    ai_scanner_universe_size: int
    ai_scanner_result_limit: int
    ai_scanner_execution_timeframe: str
    ai_scanner_trend_timeframe: str
    selector_min_confidence: float
    selector_min_expected_net_return: float
    selector_min_reward_risk_ratio: float
    selector_model_version: str
    adaptive_research_interval_hours: float
    adaptive_research_retry_minutes: int
    adaptive_research_min_candles: int
    adaptive_research_validation_rows: int
    adaptive_research_walk_forward_folds: int
    adaptive_research_min_trades: int
    adaptive_research_min_profit_factor: float
    adaptive_research_max_drawdown_pct: float
    adaptive_research_min_stability: float
    adaptive_research_min_validation_score: float


class PaginationMetadata(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_previous: bool
    has_next: bool


class ExperimentHistoryResponse(BaseModel):
    items: list[ExperimentResponse]
    pagination: PaginationMetadata


class StrategyTradeHistorySummary(BaseModel):
    total_trades: int
    buy_count: int
    sell_count: int
    profitable_exits: int
    losing_exits: int
    break_even_exits: int
    total_transaction_cost: float
    total_realized_pnl: float
    win_rate: float | None


class StrategyTradeHistoryResponse(BaseModel):
    items: list[dict[str, Any]]
    pagination: PaginationMetadata
    summary: StrategyTradeHistorySummary


class AdaptiveHistoryRetryResponse(BaseModel):
    experiment_id: str
    status: str
    message: str


class AdaptiveResearchRetryResponse(BaseModel):
    experiment_id: str
    status: str
    message: str
    research_provider: str = "LOCAL"

