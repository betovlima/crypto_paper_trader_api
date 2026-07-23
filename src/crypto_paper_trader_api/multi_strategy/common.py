from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timezone

import pandas as pd

from ..adaptive_strategy_research import (
    AdaptiveStrategyResearchEngine,
    MarketRegimeAnalyzer,
    StrategySpecification,
)
from ..config import Settings
from ..execution_costs import ExecutionCosts
from ..ml_model import ModelPrediction
from ..models import StrategyAccount
from ..trading_profiles import TradingProfile, get_trading_profile

@dataclass(frozen=True)
class StrategyDecision:
    technical_signal: str
    model_signal: str
    final_signal: str
    technical_confirmations: int
    reason: str
    execution_reference_price: float | None = None
    setup_status: str | None = None
    potential_target_price: float | None = None
    potential_gross_return: float | None = None
    reward_risk_ratio: float | None = None
    stop_loss_override: float | None = None
    take_profit_override: float | None = None

    # Optional diagnostics emitted by the autonomous AI Pattern Trader.
    ai_mode: str | None = None
    ai_proposed_action: str | None = None
    ai_regime: str | None = None
    ai_pattern_cluster: int | None = None
    ai_confidence: float | None = None
    ai_upward_probability: float | None = None
    ai_neighbor_count: int | None = None
    ai_positive_neighbor_rate: float | None = None
    ai_expected_gross_return: float | None = None
    ai_expected_net_return: float | None = None
    ai_worst_adverse_return: float | None = None
    ai_model_version: str | None = None
    ai_training_samples: int | None = None
    ai_validation_accuracy: float | None = None
    ai_validation_mae: float | None = None
    ai_risk_status: str | None = None
    ai_risk_reason: str | None = None
    ai_horizon_candles: int | None = None
    ai_feature_summary: str | None = None

    # Optional diagnostics emitted by the Adaptive Strategy Selector.
    selector_selected_strategy: str | None = None
    selector_market_regime: str | None = None
    selector_confidence: float | None = None
    selector_expected_net_return: float | None = None
    selector_candidate_scores: str | None = None
    selector_model_version: str | None = None
    selector_active_strategy_name: str | None = None
    selector_strategy_origin: str | None = None
    selector_research_status: str | None = None
    selector_research_summary: str | None = None
    selector_validation_score: float | None = None
    selector_profit_factor: float | None = None
    selector_max_drawdown_pct: float | None = None
    selector_net_return: float | None = None
    selector_trade_count: int | None = None
    selector_next_research_at: datetime | None = None
    selector_strategy_spec_json: str | None = None
    selector_source_urls_json: str | None = None
    selector_ai_provider: str | None = None
    selector_ai_model: str | None = None
    selector_ai_review_status: str | None = None
    selector_ai_review_score: float | None = None
    selector_ai_review_summary: str | None = None

def _ema(row: pd.Series, period: int) -> float:
    return float(row[f"ema_{period}"])

def _candle_body_atr(row: pd.Series, atr: float) -> float:
    return abs(float(row["close"]) - float(row["open"])) / max(atr, 1e-12)

def _bullish_confirmation(row: pd.Series, atr: float, minimum_body_atr: float) -> bool:
    return (
        float(row["close"]) > float(row["open"])
        and _candle_body_atr(row, atr) >= minimum_body_atr
    )

def _not_overextended(
    close: float,
    reference_price: float,
    atr: float,
    maximum_extension_atr: float,
) -> bool:
    extension = close - reference_price
    return 0.0 <= extension <= max(atr, 1e-12) * maximum_extension_atr

def _market_context_values(row: pd.Series) -> tuple[float, float, float]:
    ignition = float(row.get("ignition_score", 0.0) or 0.0)
    exhaustion = float(row.get("exhaustion_score", 0.0) or 0.0)
    compression_ratio = float(row.get("compression_ratio", 1.0) or 1.0)
    compression_score = max(0.0, min(1.0, 1.0 - compression_ratio))
    return ignition, exhaustion, compression_score

def _context_entry_allowed(
    row: pd.Series,
    settings: Settings,
    *,
    require_ignition: bool = False,
) -> bool:
    ignition, exhaustion, _ = _market_context_values(row)
    if exhaustion > settings.exhaustion_max_entry_score:
        return False
    if (
        require_ignition
        and "ignition_score" in row.index
        and ignition < settings.ignition_min_score
    ):
        return False
    return True

def _risk_levels(
    close: float,
    atr: float,
    profile: TradingProfile,
) -> tuple[float, float, float]:
    """Return technical stop and target levels without using trading fees."""

    raw_stop_pct = profile.stop_atr_multiplier * atr / max(close, 1e-9)
    stop_pct = min(max(raw_stop_pct, profile.stop_loss_min_pct), profile.stop_loss_max_pct)
    stop = close * (1 - stop_pct)
    atr_target_pct = profile.take_profit_atr_multiplier * atr / max(close, 1e-9)
    target_pct = max(stop_pct * profile.reward_risk_ratio, atr_target_pct)
    target = close * (1 + target_pct)
    return stop, target, target_pct

__all__ = [
    "datetime",
    "timezone",
    "json",
    "pd",
    "AdaptiveStrategyResearchEngine",
    "MarketRegimeAnalyzer",
    "StrategySpecification",
    "Settings",
    "ExecutionCosts",
    "ModelPrediction",
    "StrategyAccount",
    "TradingProfile",
    "get_trading_profile",
    "StrategyDecision",
    "_ema",
    "_candle_body_atr",
    "_bullish_confirmation",
    "_not_overextended",
    "_market_context_values",
    "_context_entry_allowed",
    "_risk_levels",
]
