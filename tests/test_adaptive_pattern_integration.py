from crypto_paper_trader_api.adaptive_intelligence import PatternConfirmationService
from crypto_paper_trader_api.multi_strategy import StrategyDecision


def _selector(signal: str) -> StrategyDecision:
    return StrategyDecision(signal, "RESEARCH_SELECTOR", signal, 1, "selector")


def _pattern(action: str, status: str) -> StrategyDecision:
    return StrategyDecision(
        action, action, action if status == "APPROVED" else "HOLD", 1, "pattern",
        ai_proposed_action=action, ai_risk_status=status, ai_confidence=0.8,
        ai_expected_net_return=0.01, ai_risk_reason="pattern risk",
    )


def test_selector_buy_requires_pattern_approval():
    result = PatternConfirmationService.combine(_selector("BUY"), _pattern("HOLD", "BLOCKED"))
    assert result.final_signal == "HOLD"
    assert result.setup_status == "WAITING_PATTERN_CONFIRMATION"
    assert "pattern_confirmation=BLOCKED" in result.reason


def test_selector_buy_executes_when_pattern_approves():
    result = PatternConfirmationService.combine(_selector("BUY"), _pattern("BUY", "APPROVED"))
    assert result.final_signal == "BUY"
    assert result.ai_confidence == 0.8
    assert "pattern_confirmation=APPROVED" in result.reason


def test_selector_exit_is_not_blocked_by_pattern():
    result = PatternConfirmationService.combine(_selector("SELL"), _pattern("HOLD", "BLOCKED"))
    assert result.final_signal == "SELL"
    assert "NOT_REQUIRED_FOR_EXIT" in result.reason
