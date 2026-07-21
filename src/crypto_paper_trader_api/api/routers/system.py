from __future__ import annotations

from fastapi import APIRouter

from ...runtime import settings, worker
from ...schemas import HealthResponse, PublicConfiguration
from ...strategy_codes import (
    ACTIVE_STRATEGY_CODES,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_DISPLAY_NAMES,
)
from ...trading_profiles import list_trading_profiles

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    database_path = settings.resolved_data_dir / "crypto_paper_trader_api.db"
    return HealthResponse(
        database=settings.resolved_database_url,
        data_dir=str(settings.resolved_data_dir),
        database_exists=database_path.exists(),
        worker_running=worker.is_running,
        persistent_storage_configured=settings.persistent_storage_configured,
        storage_warning=settings.storage_warning,
    )


@router.get("/api/v1/config", response_model=PublicConfiguration)
def public_configuration() -> PublicConfiguration:
    return PublicConfiguration(
        fees_affect_signals=False,
        downtime_recovery_enabled=True,
        active_strategy_codes=list(ACTIVE_STRATEGY_CODES),
        trading_profiles=list_trading_profiles(),
        strategy_catalog=[
            {
                "code": code,
                "display_name": STRATEGY_DISPLAY_NAMES[code],
                "description": STRATEGY_DESCRIPTIONS[code],
            }
            for code in ACTIVE_STRATEGY_CODES
        ],
        default_market=settings.default_market,
        default_execution_timeframe=settings.default_execution_timeframe,
        default_trend_timeframe=settings.default_trend_timeframe,
        default_duration_hours=settings.default_duration_hours,
        default_initial_capital=settings.default_initial_capital,
        vip_level=settings.vip_level,
        maker_fee_rate=settings.effective_default_maker_fee_rate,
        taker_fee_rate=settings.effective_default_taker_fee_rate,
        cet_fee_discount_enabled=settings.cet_fee_discount_enabled,
        fallback_spread_rate=settings.fallback_spread_rate,
        slippage_rate=settings.slippage_rate,
        estimated_round_trip_cost_rate=settings.round_trip_cost_rate,
        position_allocation=settings.position_allocation,
        buy_probability_threshold=settings.buy_probability_threshold,
        sell_probability_threshold=settings.sell_probability_threshold,
        min_technical_confirmations=settings.min_technical_confirmations,
        stop_atr_multiplier=settings.stop_atr_multiplier,
        stop_loss_min_pct=settings.stop_loss_min_pct,
        stop_loss_max_pct=settings.stop_loss_max_pct,
        reward_risk_ratio=settings.reward_risk_ratio,
        take_profit_atr_multiplier=settings.take_profit_atr_multiplier,
        trailing_atr_multiplier=settings.trailing_atr_multiplier,
        trailing_activation_r=settings.trailing_activation_r,
        break_even_activation_r=settings.break_even_activation_r,
        max_holding_hours=settings.max_holding_hours,
        max_daily_loss_pct=settings.max_daily_loss_pct,
        ema9_period=settings.ema9_period,
        ai_pattern_mode=settings.ai_pattern_mode,
        ai_pattern_horizon_candles=settings.ai_pattern_horizon_candles,
        ai_pattern_buy_probability_threshold=settings.ai_pattern_buy_probability_threshold,
        ai_pattern_sell_probability_threshold=settings.ai_pattern_sell_probability_threshold,
        ai_pattern_min_expected_net_return=settings.ai_pattern_min_expected_net_return,
        ai_pattern_min_confidence=settings.ai_pattern_min_confidence,
        ai_pattern_max_spread_rate=settings.ai_pattern_max_spread_rate,
        ai_pattern_model_version="AI-PATTERN-v1",
    )
