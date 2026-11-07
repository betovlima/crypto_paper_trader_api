"""Build immutable strategy decision snapshots from prepared market and strategy state.

This module intentionally has no worker lifecycle, database-session, or order-execution logic.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .execution_costs import ExecutionCosts
from .ml_model import ModelPrediction
from .models import Experiment, StrategyAccount, StrategyDecisionSnapshot
from .strategy_codes import AI_PATTERN_TRADER, CURRENT_HYBRID
from .trading_profiles import get_trading_profile


def build_decision_snapshot(
    experiment: Experiment,
    account: StrategyAccount,
    candle_timestamp: datetime,
    execution_row: pd.Series,
    trend_row: pd.Series,
    prediction: ModelPrediction,
    costs: ExecutionCosts,
    required_gross_return: float,
    position_before: str,
    decision,
) -> StrategyDecisionSnapshot:
    profile = get_trading_profile(experiment.trading_profile)
    return StrategyDecisionSnapshot(
        experiment_id=experiment.id,
        strategy_account_id=account.id,
        strategy_code=account.strategy_code,
        candle_timestamp=candle_timestamp,
        market_price=float(execution_row["close"]),
        candle_high=float(execution_row["high"]),
        candle_low=float(execution_row["low"]),
        fast_ema_period=profile.fast_ema_period,
        slow_ema_period=profile.slow_ema_period,
        regime_ema_period=profile.regime_ema_period,
        fast_ema_value=float(execution_row[f"ema_{profile.fast_ema_period}"]),
        slow_ema_value=float(execution_row[f"ema_{profile.slow_ema_period}"]),
        regime_ema_value=float(execution_row[f"ema_{profile.regime_ema_period}"]),
        ema_9=float(execution_row["ema_9"]),
        ema_9_previous=account.ema_9_previous,
        ema_9_slope=account.ema_9_slope,
        ema_20=float(execution_row["ema_20"]),
        ema_50=float(execution_row["ema_50"]),
        ema_200=float(execution_row["ema_200"]),
        rsi_14=float(execution_row["rsi_14"]),
        atr_14=float(execution_row["atr_14"]),
        adx_14=float(execution_row["adx_14"]),
        average_volume_20=float(execution_row["average_volume_20"]),
        relative_volume=float(execution_row["relative_volume"]),
        volatility_20=float(execution_row["volatility_20"]),
        return_1=float(execution_row["return_1"]),
        return_3=float(execution_row["return_3"]),
        return_6=float(execution_row["return_6"]),
        range_ratio_20=float(execution_row.get("range_ratio_20", 0.0)),
        body_ratio=float(execution_row.get("body_ratio", 0.0)),
        close_location=float(execution_row.get("close_location", 0.0)),
        compression_ratio=float(execution_row.get("compression_ratio", 1.0)),
        trend_age_up=float(execution_row.get("trend_age_up", 0.0)),
        extension_ema20_atr=float(execution_row.get("extension_ema20_atr", 0.0)),
        ignition_score=float(execution_row.get("ignition_score", 0.0)),
        exhaustion_score=float(execution_row.get("exhaustion_score", 0.0)),
        expected_value_r=(
            (
                float(prediction.upward_probability)
                * float(decision.reward_risk_ratio or 0.0)
                - (1.0 - float(prediction.upward_probability))
            )
            if account.strategy_code == CURRENT_HYBRID
            else (
                float(decision.ai_upward_probability)
                * float(decision.reward_risk_ratio or 0.0)
                - (1.0 - float(decision.ai_upward_probability))
            )
            if account.strategy_code == AI_PATTERN_TRADER
            and decision.ai_upward_probability is not None
            else None
        ),
        trend_close=float(trend_row["close"]),
        trend_ema_20=float(trend_row["ema_20"]),
        trend_ema_50=float(trend_row["ema_50"]),
        trend_ema_200=float(trend_row["ema_200"]),
        trend_rsi_14=float(trend_row["rsi_14"]),
        trend_adx_14=float(trend_row["adx_14"]),
        upward_probability=(
            prediction.upward_probability
            if account.strategy_code == CURRENT_HYBRID
            else decision.ai_upward_probability
            if account.strategy_code == AI_PATTERN_TRADER
            else None
        ),
        downward_probability=(
            prediction.downward_probability
            if account.strategy_code == CURRENT_HYBRID
            else (1 - decision.ai_upward_probability)
            if account.strategy_code == AI_PATTERN_TRADER
            and decision.ai_upward_probability is not None
            else None
        ),
        expected_return=(
            prediction.expected_return
            if account.strategy_code == CURRENT_HYBRID
            else decision.ai_expected_net_return
            if account.strategy_code == AI_PATTERN_TRADER
            else None
        ),
        model_accuracy=(
            prediction.accuracy
            if account.strategy_code == CURRENT_HYBRID
            else decision.ai_validation_accuracy
            if account.strategy_code == AI_PATTERN_TRADER
            else None
        ),
        model_precision=(
            prediction.precision if account.strategy_code == CURRENT_HYBRID else None
        ),
        model_recall=(prediction.recall if account.strategy_code == CURRENT_HYBRID else None),
        model_roc_auc=(prediction.roc_auc if account.strategy_code == CURRENT_HYBRID else None),
        training_rows=(
            prediction.training_rows
            if account.strategy_code == CURRENT_HYBRID
            else int(decision.ai_training_samples or 0)
            if account.strategy_code == AI_PATTERN_TRADER
            else 0
        ),
        model_top_features=(
            prediction.top_features_json
            if account.strategy_code == CURRENT_HYBRID
            else decision.ai_feature_summary or "{}"
            if account.strategy_code == AI_PATTERN_TRADER
            else "[]"
        ),
        maker_fee_rate=costs.maker_fee_rate,
        taker_fee_rate=costs.taker_fee_rate,
        spread_rate=costs.spread_rate,
        slippage_rate=costs.slippage_rate,
        estimated_round_trip_cost_rate=costs.estimated_round_trip_rate,
        required_gross_return=required_gross_return,
        setup_status=decision.setup_status,
        setup_candle_high=account.setup_candle_high,
        setup_candle_low=account.setup_candle_low,
        entry_trigger_price=account.entry_trigger_price,
        initial_stop_price=account.initial_setup_stop_price,
        potential_target_price=decision.potential_target_price,
        potential_gross_return=decision.potential_gross_return,
        reward_risk_ratio=decision.reward_risk_ratio,
        stop_management_mode=account.stop_management_mode,
        active_stop_price=max(
            [
                value
                for value in (account.stop_loss_price, account.trailing_stop_price)
                if value is not None
            ],
            default=None,
        ),
        exit_trigger_price=account.exit_trigger_price,
        ai_mode=decision.ai_mode,
        ai_proposed_action=decision.ai_proposed_action,
        ai_regime=decision.ai_regime,
        ai_pattern_cluster=decision.ai_pattern_cluster,
        ai_confidence=decision.ai_confidence,
        ai_neighbor_count=decision.ai_neighbor_count,
        ai_positive_neighbor_rate=decision.ai_positive_neighbor_rate,
        ai_expected_gross_return=decision.ai_expected_gross_return,
        ai_expected_net_return=decision.ai_expected_net_return,
        ai_worst_adverse_return=decision.ai_worst_adverse_return,
        ai_model_version=decision.ai_model_version,
        ai_training_samples=decision.ai_training_samples,
        ai_validation_accuracy=decision.ai_validation_accuracy,
        ai_validation_mae=decision.ai_validation_mae,
        ai_risk_status=decision.ai_risk_status,
        ai_risk_reason=decision.ai_risk_reason,
        ai_horizon_candles=decision.ai_horizon_candles,
        ai_feature_summary=decision.ai_feature_summary,
        selector_selected_strategy=decision.selector_selected_strategy,
        selector_market_regime=decision.selector_market_regime,
        selector_confidence=decision.selector_confidence,
        selector_expected_net_return=decision.selector_expected_net_return,
        selector_candidate_scores=decision.selector_candidate_scores,
        selector_model_version=decision.selector_model_version,
        selector_active_strategy_name=decision.selector_active_strategy_name,
        selector_strategy_origin=decision.selector_strategy_origin,
        selector_research_status=decision.selector_research_status,
        selector_research_summary=decision.selector_research_summary,
        selector_validation_score=decision.selector_validation_score,
        selector_profit_factor=decision.selector_profit_factor,
        selector_max_drawdown_pct=decision.selector_max_drawdown_pct,
        selector_net_return=decision.selector_net_return,
        selector_trade_count=decision.selector_trade_count,
        selector_next_research_at=decision.selector_next_research_at,
        selector_strategy_spec_json=decision.selector_strategy_spec_json,
        selector_source_urls_json=decision.selector_source_urls_json,
        selector_ai_provider=decision.selector_ai_provider,
        selector_ai_model=decision.selector_ai_model,
        selector_ai_review_status=decision.selector_ai_review_status,
        selector_ai_review_score=decision.selector_ai_review_score,
        selector_ai_review_summary=decision.selector_ai_review_summary,
        technical_signal=decision.technical_signal,
        model_signal=decision.model_signal,
        final_signal=decision.final_signal,
        technical_confirmations=decision.technical_confirmations,
        decision_reason=decision.reason,
        position_before=position_before,
        action_executed=False,
        execution_reference_price=decision.execution_reference_price,
    )
