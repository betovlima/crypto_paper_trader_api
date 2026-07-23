from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.adaptive_strategy_research import StrategyTemplateLibrary

def test_transition_generates_multiple_controlled_candidates():
    candidates=StrategyTemplateLibrary().candidates("TRANSITION")
    assert len(candidates)>=15
    assert any(c.origin=="SYSTEM_VARIANT" for c in candidates)

def test_default_candidate_limit_allows_broader_research():
    assert Settings().adaptive_research_max_candidates==15
