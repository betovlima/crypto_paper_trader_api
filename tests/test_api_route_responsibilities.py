from __future__ import annotations

from crypto_paper_trader_api.app import app
from crypto_paper_trader_api.api.routers.system import public_configuration
from crypto_paper_trader_api.strategy_codes import AI_PATTERN_TRADER


def _route_tags(path: str) -> set[tuple[str, ...]]:
    """Read the public OpenAPI contract rather than FastAPI's private route tree."""
    http_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    return {
        tuple(operation.get("tags", []))
        for method, operation in app.openapi()["paths"][path].items()
        if method.lower() in http_methods
    }


def test_routes_are_grouped_by_http_responsibility() -> None:
    assert _route_tags("/health") == {("System",)}
    assert _route_tags("/api/v1/experiments") == {("Experiments",)}
    assert _route_tags("/api/v1/experiments/stop-running") == {("Experiments",)}
    assert _route_tags("/api/v1/experiments/running/header-summary") == {("Experiments",)}
    assert _route_tags("/api/v1/ai-opportunities/status") == {("AI Opportunity Scanner",)}
    assert _route_tags(
        "/api/v1/experiments/{experiment_id}/strategy-comparison"
    ) == {("Strategy Comparison",)}
    assert _route_tags(
        "/api/v1/experiments/{experiment_id}/strategy-decisions"
    ) == {("Strategy Data",)}
    assert _route_tags(
        "/api/v1/experiments/{experiment_id}/ai-pattern-trader/status"
    ) == {("AI Pattern Trader",)}


def test_ai_scanner_is_independent_from_experiment_strategy_catalog() -> None:
    assert "/api/v1/config" in app.openapi()["paths"]
    payload = public_configuration()
    assert AI_PATTERN_TRADER not in payload.active_strategy_codes
    assert payload.ai_scanner_enabled is True
