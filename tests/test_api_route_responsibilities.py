from __future__ import annotations

from crypto_paper_trader_api.app import app
from crypto_paper_trader_api.strategy_codes import AI_PATTERN_TRADER


def _route(path: str):
    return next(route for route in app.routes if getattr(route, "path", None) == path)


def test_routes_are_grouped_by_http_responsibility() -> None:
    assert _route("/health").tags == ["System"]
    assert _route("/api/v1/experiments").tags == ["Experiments"]
    assert _route("/api/v1/experiments/stop-running").tags == ["Experiments"]
    assert _route("/api/v1/experiments/running/header-summary").tags == ["Experiments"]
    assert _route("/api/v1/ai-opportunities/status").tags == ["AI Opportunity Scanner"]
    assert _route(
        "/api/v1/experiments/{experiment_id}/strategy-comparison"
    ).tags == ["Strategy Comparison"]
    assert _route(
        "/api/v1/experiments/{experiment_id}/strategy-decisions"
    ).tags == ["Strategy Data"]
    assert _route(
        "/api/v1/experiments/{experiment_id}/ai-pattern-trader/status"
    ).tags == ["AI Pattern Trader"]


def test_ai_scanner_is_independent_from_experiment_strategy_catalog() -> None:
    config_route = _route("/api/v1/config")
    payload = config_route.endpoint()
    assert AI_PATTERN_TRADER not in payload.active_strategy_codes
    assert payload.ai_scanner_enabled is True
