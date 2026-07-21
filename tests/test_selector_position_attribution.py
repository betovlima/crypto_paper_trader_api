from __future__ import annotations

from datetime import datetime, timezone

from crypto_paper_trader_api.models import StrategyAccount


def test_adaptive_selector_public_payload_keeps_open_position_attribution() -> None:
    opened_at = datetime(2026, 7, 21, 18, 30, tzinfo=timezone.utc)
    account = StrategyAccount(
        experiment_id="test",
        strategy_code="ADAPTIVE_STRATEGY_SELECTOR",
        display_name="Adaptive Strategy Selector",
        initial_capital=1000.0,
        cash_balance=0.0,
        asset_quantity=1.0,
        max_equity=1000.0,
        entry_time=opened_at,
        selector_selected_strategy="CURRENT_HYBRID",
    )

    payload = account.to_public_dict(100.0)

    assert payload["selector_position_strategy_code"] == "CURRENT_HYBRID"
    assert payload["selector_position_opened_at"] == opened_at


def test_flat_selector_does_not_expose_candidate_as_position_strategy() -> None:
    account = StrategyAccount(
        experiment_id="test",
        strategy_code="ADAPTIVE_STRATEGY_SELECTOR",
        display_name="Adaptive Strategy Selector",
        initial_capital=1000.0,
        cash_balance=1000.0,
        asset_quantity=0.0,
        max_equity=1000.0,
        selector_selected_strategy="GEN_TEST",
    )

    payload = account.to_public_dict(100.0)

    assert payload["selector_position_strategy_code"] is None
