from __future__ import annotations

CURRENT_HYBRID = "CURRENT_HYBRID"

# The persisted values are retained for compatibility with existing SQLite databases.
# Fees are no longer used as entry or exit vetoes in v0.8.0.
EMA_CROSSOVER_COST_AWARE = "EMA_CROSSOVER_COST_AWARE"
EMA_CROSSOVER = EMA_CROSSOVER_COST_AWARE
EMA9_SETUP_91 = "EMA9_SETUP_91"
EMA9_SETUP_91_COST_AWARE = "EMA9_SETUP_91_COST_AWARE"
LARRY_WILLIAMS_91 = EMA9_SETUP_91_COST_AWARE
BUY_AND_HOLD = "BUY_AND_HOLD"

ACTIVE_STRATEGY_CODES = (
    CURRENT_HYBRID,
    EMA_CROSSOVER,
    LARRY_WILLIAMS_91,
)

STRATEGY_DISPLAY_NAMES = {
    CURRENT_HYBRID: "Profile-Aware Hybrid",
    EMA_CROSSOVER: "EMA Crossover",
    EMA9_SETUP_91: "Larry Williams 9.1",
    LARRY_WILLIAMS_91: "Larry Williams 9.1",
    BUY_AND_HOLD: "Buy and Hold",
}

STRATEGY_DESCRIPTIONS = {
    CURRENT_HYBRID: (
        "Combines the selected profile's EMAs, RSI, ADX, relative volume and XGBoost "
        "direction probability. Exchange fees are recorded after execution and never veto "
        "a valid technical signal."
    ),
    EMA_CROSSOVER: (
        "Buys after a fresh fast-EMA crossover above the slow EMA, with trend, ADX, volume "
        "and RSI confirmation. Fees affect the reported net result, not the signal."
    ),
    LARRY_WILLIAMS_91: (
        "Detects a down-to-up turn in EMA 9, records the reversal candle and buys when the "
        "next market movement breaks that candle's high. The initial stop stays below the "
        "setup candle low."
    ),
}

EMA9_STRATEGY_CODES = {EMA9_SETUP_91, LARRY_WILLIAMS_91}
DIRECT_ENTRY_STRATEGY_CODES = {CURRENT_HYBRID, EMA_CROSSOVER}
DYNAMIC_RISK_STRATEGY_CODES = {CURRENT_HYBRID, EMA_CROSSOVER}
