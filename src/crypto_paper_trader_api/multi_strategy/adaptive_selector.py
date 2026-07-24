from __future__ import annotations

from .common import *  # noqa: F403
from ..adaptive_intelligence import PatternConfirmationService

class AdaptiveStrategySelector:
    """Researches, validates and executes a generated strategy for the selected market."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.engine = AdaptiveStrategyResearchEngine(settings)

    @staticmethod
    def detect_regime(current_row: pd.Series, trend_row: pd.Series) -> str:
        return MarketRegimeAnalyzer.detect(current_row, trend_row)

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _needs_research(
        self,
        account: StrategyAccount,
        regime: str,
        now: datetime,
    ) -> bool:
        current_spec = StrategySpecification.from_json(account.selector_strategy_spec_json)
        if current_spec is None:
            return True
        if account.selector_market_regime != regime:
            return True
        next_research = self._as_utc(account.selector_next_research_at)
        return next_research is None or now >= next_research

    def decide(
        self,
        account: StrategyAccount,
        current_row: pd.Series,
        trend_row: pd.Series,
        costs: ExecutionCosts,
        research_frame: pd.DataFrame,
        current_index: int,
        market: str,
        execution_timeframe: str,
        trend_timeframe: str,
        now: datetime,
        pattern_decision: StrategyDecision | None = None,
    ) -> StrategyDecision:
        regime = self.detect_regime(current_row, trend_row)
        close = float(current_row["close"])
        active_spec = StrategySpecification.from_json(account.selector_strategy_spec_json)

        # An open paper position always remains attached to the strategy that opened it.
        # Research can replace the active strategy only after the position is flat.
        if not account.has_open_position and self._needs_research(account, regime, now):
            outcome = self.engine.research(
                market=market,
                regime=regime,
                execution_timeframe=execution_timeframe,
                trend_timeframe=trend_timeframe,
                frame=research_frame,
                costs=costs,
                now=now,
            )
            account.selector_market_regime = outcome.regime
            account.selector_research_status = outcome.research_status
            account.selector_research_summary = outcome.research_summary
            account.selector_candidate_scores = outcome.candidate_scores_json
            account.selector_source_urls_json = outcome.source_urls_json
            account.selector_next_research_at = outcome.next_research_at
            account.selector_model_version = self.settings.selector_model_version
            account.selector_last_error = outcome.error_message
            account.selector_ai_provider = outcome.ai_provider
            account.selector_ai_model = outcome.ai_model
            account.selector_ai_review_status = outcome.ai_review_status
            account.selector_ai_review_score = outcome.ai_review_score
            account.selector_ai_review_summary = outcome.ai_review_summary

            if outcome.specification is None or outcome.metrics is None:
                if active_spec is not None:
                    account.selector_research_status = "CHAMPION_SUSPENDED"
                    account.selector_research_summary = outcome.research_summary + " The previously validated champion was preserved but is suspended until the market context becomes compatible again."
                return StrategyDecision(
                    "HOLD", "RESEARCH_SELECTOR", "HOLD", 0,
                    outcome.research_summary,
                    selector_market_regime=regime,
                    selector_candidate_scores=outcome.candidate_scores_json,
                    selector_model_version=self.settings.selector_model_version,
                    selector_research_status=outcome.research_status,
                    selector_research_summary=outcome.research_summary,
                    selector_next_research_at=outcome.next_research_at,
                    selector_source_urls_json=outcome.source_urls_json,
                    selector_ai_provider=outcome.ai_provider,
                    selector_ai_model=outcome.ai_model,
                    selector_ai_review_status=outcome.ai_review_status,
                    selector_ai_review_score=outcome.ai_review_score,
                    selector_ai_review_summary=outcome.ai_review_summary,
                )

            active_spec = outcome.specification
            metrics = outcome.metrics
            account.selector_selected_strategy = active_spec.code
            account.selector_active_strategy_name = active_spec.name
            account.selector_strategy_origin = active_spec.origin
            account.selector_strategy_spec_json = active_spec.to_json()
            account.selector_validation_score = metrics.score
            account.selector_profit_factor = metrics.profit_factor
            account.selector_max_drawdown_pct = metrics.max_drawdown_pct
            account.selector_net_return = metrics.net_return
            account.selector_trade_count = metrics.trade_count
            account.selector_confidence = min(max(metrics.score / 100.0, 0.0), 1.0)
            account.selector_expected_net_return = metrics.net_return

        if active_spec is None:
            reason = account.selector_research_summary or (
                "No generated strategy has passed the validation requirements yet."
            )
            return StrategyDecision(
                "HOLD", "RESEARCH_SELECTOR", "HOLD", 0, reason,
                selector_market_regime=regime,
                selector_candidate_scores=account.selector_candidate_scores,
                selector_model_version=self.settings.selector_model_version,
                selector_research_status=account.selector_research_status or "WAITING_FOR_VALID_STRATEGY",
                selector_research_summary=reason,
                selector_next_research_at=account.selector_next_research_at,
                selector_source_urls_json=account.selector_source_urls_json,
                selector_ai_provider=account.selector_ai_provider,
                selector_ai_model=account.selector_ai_model,
                selector_ai_review_status=account.selector_ai_review_status,
                selector_ai_review_score=account.selector_ai_review_score,
                selector_ai_review_summary=account.selector_ai_review_summary,
            )

        live = self.engine.executor.live_decision(
            spec=active_spec,
            account=account,
            frame=research_frame,
            current_index=current_index,
            regime=regime,
        )
        signal = str(live["signal"])
        reason = (
            f"generated_strategy={active_spec.code}; name={active_spec.name}; "
            f"origin={active_spec.origin}; regime={regime}; rule={live['reason']}; "
            f"validation_score={float(account.selector_validation_score or 0):.2f}"
        )
        selector_decision = StrategyDecision(
            signal,
            "RESEARCH_SELECTOR",
            signal,
            0,
            reason,
            live.get("execution_reference_price") or close,
            potential_target_price=live.get("take_profit"),
            potential_gross_return=live.get("potential_gross_return"),
            reward_risk_ratio=live.get("reward_risk_ratio"),
            stop_loss_override=live.get("stop_loss"),
            take_profit_override=live.get("take_profit"),
            selector_selected_strategy=active_spec.code,
            selector_market_regime=regime,
            selector_confidence=account.selector_confidence,
            selector_expected_net_return=account.selector_expected_net_return,
            selector_candidate_scores=account.selector_candidate_scores,
            selector_model_version=self.settings.selector_model_version,
            selector_active_strategy_name=active_spec.name,
            selector_strategy_origin=active_spec.origin,
            selector_research_status=account.selector_research_status or "ACTIVE",
            selector_research_summary=account.selector_research_summary,
            selector_validation_score=account.selector_validation_score,
            selector_profit_factor=account.selector_profit_factor,
            selector_max_drawdown_pct=account.selector_max_drawdown_pct,
            selector_net_return=account.selector_net_return,
            selector_trade_count=account.selector_trade_count,
            selector_next_research_at=account.selector_next_research_at,
            selector_strategy_spec_json=active_spec.to_json(),
            selector_source_urls_json=account.selector_source_urls_json,
            selector_ai_provider=account.selector_ai_provider,
            selector_ai_model=account.selector_ai_model,
            selector_ai_review_status=account.selector_ai_review_status,
            selector_ai_review_score=account.selector_ai_review_score,
            selector_ai_review_summary=account.selector_ai_review_summary,
        )
        return PatternConfirmationService.combine(selector_decision, pattern_decision)
