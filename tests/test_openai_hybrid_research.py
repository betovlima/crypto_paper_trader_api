from crypto_paper_trader_api.adaptive_strategy_research import (
    OpenAIStrategyReviewer,
    WebStrategyResearcher,
)
from crypto_paper_trader_api.config import Settings


def test_research_schema_is_strict_and_rejects_extra_fields():
    schema = WebStrategyResearcher._research_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    strategy = schema["properties"]["strategies"]["items"]
    assert strategy["additionalProperties"] is False
    parameters = strategy["properties"]["parameters"]
    assert parameters["additionalProperties"] is False
    assert set(parameters["required"]) == set(parameters["properties"])


def test_openai_review_is_disabled_without_api_key():
    settings = Settings(
        adaptive_research_ai_review_enabled=True,
        openai_api_key=None,
    )
    reviewer = OpenAIStrategyReviewer(settings)

    assert reviewer.enabled is False
    result = reviewer.review("BTCUSDT", "STRONG_UPTREND", [])
    assert result.status == "NOT_USED"
    assert result.selected_code is None


def test_web_research_is_disabled_without_api_key():
    settings = Settings(
        adaptive_research_web_enabled=True,
        openai_api_key=None,
    )
    researcher = WebStrategyResearcher(settings)

    assert researcher.enabled is False
    strategies, summary, sources = researcher.research(
        "BTCUSDT", "STRONG_UPTREND", "1hour", "4hour"
    )
    assert strategies == []
    assert sources == ()
    assert "OPENAI_API_KEY" in summary
