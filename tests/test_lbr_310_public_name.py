from crypto_paper_trader_api.strategy_codes import (
    LBR_310_ANTI_CONTEXT,
    STRATEGY_DESCRIPTIONS,
    STRATEGY_DISPLAY_NAMES,
)


def test_lbr_310_uses_concise_public_name() -> None:
    assert STRATEGY_DISPLAY_NAMES[LBR_310_ANTI_CONTEXT] == "Trend Resumption with LBR 3/10"


def test_lbr_310_description_separates_original_setup_from_crypto_filter() -> None:
    description = STRATEGY_DESCRIPTIONS[LBR_310_ANTI_CONTEXT]
    assert "original 3/10 Anti setup" in description
    assert "application context filter" in description
