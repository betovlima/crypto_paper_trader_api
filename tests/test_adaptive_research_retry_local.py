from crypto_paper_trader_api.app import app


def test_retry_research_route_is_registered() -> None:
    paths = {route.path for route in app.routes}
    assert (
        "/api/v1/experiments/{experiment_id}/adaptive-selector/retry-research"
        in paths
    )
