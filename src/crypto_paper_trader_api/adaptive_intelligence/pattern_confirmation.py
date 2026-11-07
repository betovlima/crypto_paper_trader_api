from __future__ import annotations

from dataclasses import replace

from ..multi_strategy.common import StrategyDecision


class PatternConfirmationService:
    """Fuse the adaptive selector signal with the local pattern model for one market.

    Entry decisions are conservative: a selector BUY is executed only when the
    local pattern model also approves BUY. Exit decisions are never blocked by
    the pattern model, so risk management remains deterministic.
    """

    @staticmethod
    def combine(
        selector_decision: StrategyDecision,
        pattern_decision: StrategyDecision | None,
    ) -> StrategyDecision:
        if pattern_decision is None:
            return selector_decision

        selector_signal = selector_decision.final_signal
        pattern_action = pattern_decision.ai_proposed_action or pattern_decision.final_signal
        pattern_status = pattern_decision.ai_risk_status or "UNKNOWN"

        final_signal = selector_signal
        setup_status = selector_decision.setup_status
        reason = selector_decision.reason

        if selector_signal == "BUY":
            approved = pattern_action == "BUY" and pattern_status == "APPROVED"
            if not approved:
                final_signal = "HOLD"
                setup_status = "WAITING_PATTERN_CONFIRMATION"
                reason += (
                    f"; pattern_confirmation=BLOCKED; pattern_action={pattern_action}; "
                    f"pattern_risk_status={pattern_status}; "
                    f"pattern_reason={pattern_decision.ai_risk_reason or pattern_decision.reason}"
                )
            else:
                reason += (
                    f"; pattern_confirmation=APPROVED; "
                    f"pattern_confidence={float(pattern_decision.ai_confidence or 0.0):.6f}; "
                    f"pattern_expected_net_return="
                    f"{float(pattern_decision.ai_expected_net_return or 0.0):.6f}"
                )
        elif selector_signal == "SELL":
            reason += "; pattern_confirmation=NOT_REQUIRED_FOR_EXIT"
        else:
            reason += (
                f"; pattern_observation={pattern_action}; "
                f"pattern_risk_status={pattern_status}"
            )

        return replace(
            selector_decision,
            final_signal=final_signal,
            setup_status=setup_status,
            reason=reason,
            ai_mode=pattern_decision.ai_mode,
            ai_proposed_action=pattern_action,
            ai_regime=pattern_decision.ai_regime,
            ai_pattern_cluster=pattern_decision.ai_pattern_cluster,
            ai_confidence=pattern_decision.ai_confidence,
            ai_upward_probability=pattern_decision.ai_upward_probability,
            ai_neighbor_count=pattern_decision.ai_neighbor_count,
            ai_positive_neighbor_rate=pattern_decision.ai_positive_neighbor_rate,
            ai_expected_gross_return=pattern_decision.ai_expected_gross_return,
            ai_expected_net_return=pattern_decision.ai_expected_net_return,
            ai_worst_adverse_return=pattern_decision.ai_worst_adverse_return,
            ai_model_version=pattern_decision.ai_model_version,
            ai_training_samples=pattern_decision.ai_training_samples,
            ai_validation_accuracy=pattern_decision.ai_validation_accuracy,
            ai_validation_mae=pattern_decision.ai_validation_mae,
            ai_risk_status=pattern_decision.ai_risk_status,
            ai_risk_reason=pattern_decision.ai_risk_reason,
            ai_horizon_candles=pattern_decision.ai_horizon_candles,
            ai_feature_summary=pattern_decision.ai_feature_summary,
        )
