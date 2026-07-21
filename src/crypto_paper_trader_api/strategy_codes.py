from __future__ import annotations

CURRENT_HYBRID = "CURRENT_HYBRID"

# Persisted values are retained for compatibility with existing SQLite databases.
# Fees are accounting-only and never veto technical signals.
EMA_CROSSOVER_COST_AWARE = "EMA_CROSSOVER_COST_AWARE"
EMA_CROSSOVER = EMA_CROSSOVER_COST_AWARE

EMA9_SETUP_91 = "EMA9_SETUP_91"
EMA9_SETUP_91_COST_AWARE = "EMA9_SETUP_91_COST_AWARE"

# The existing persisted Larry code becomes the classic implementation so all
# previous experiments keep their account and history after the upgrade.
LARRY_WILLIAMS_91_CLASSIC = EMA9_SETUP_91_COST_AWARE
LARRY_WILLIAMS_91 = LARRY_WILLIAMS_91_CLASSIC
LARRY_WILLIAMS_91_TREND_FOLLOWER = "EMA9_SETUP_91_TREND_FOLLOWER"

AI_PATTERN_TRADER = "AI_PATTERN_TRADER"
BUY_AND_HOLD = "BUY_AND_HOLD"

ACTIVE_STRATEGY_CODES = (
    CURRENT_HYBRID,
    EMA_CROSSOVER,
    LARRY_WILLIAMS_91_CLASSIC,
    LARRY_WILLIAMS_91_TREND_FOLLOWER,
    AI_PATTERN_TRADER,
)

STRATEGY_DISPLAY_NAMES = {
    CURRENT_HYBRID: "Profile-Aware Hybrid",
    EMA_CROSSOVER: "EMA Crossover",
    EMA9_SETUP_91: "Larry Williams 9.1 Classic",
    LARRY_WILLIAMS_91_CLASSIC: "Larry Williams 9.1 Classic",
    LARRY_WILLIAMS_91_TREND_FOLLOWER: "Larry Williams 9.1 Trend Follower",
    AI_PATTERN_TRADER: "AI Pattern Trader",
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
    LARRY_WILLIAMS_91_CLASSIC: (
        "Classic Setup 9.1: EMA 9 must turn strictly from down to up on a candle that crosses "
        "the average. Entry is above that candle's high and the initial stop is at its low. "
        "After entry, a down-turn candle arms an exit below its low."
    ),
    LARRY_WILLIAMS_91_TREND_FOLLOWER: (
        "Adapted Setup 9.1 with the same strict reversal entry. After entry, the protective "
        "stop follows the low of each newly closed candle, never moves down, and exits on the "
        "stop or a bearish EMA 9 reversal."
    ),
    AI_PATTERN_TRADER: (
        "Autonomous paper strategy that learns recurring OHLCV structures directly from "
        "chronological candle windows. It combines an Extra Trees return model, nearest-neighbour "
        "pattern memory, unsupervised clusters, regime detection and deterministic risk limits. "
        "It does not choose among the other strategies."
    ),
}

EMA9_STRATEGY_CODES = {
    EMA9_SETUP_91,
    LARRY_WILLIAMS_91_CLASSIC,
    LARRY_WILLIAMS_91_TREND_FOLLOWER,
}
EMA9_CLASSIC_STRATEGY_CODES = {EMA9_SETUP_91, LARRY_WILLIAMS_91_CLASSIC}
EMA9_TREND_FOLLOWER_STRATEGY_CODES = {LARRY_WILLIAMS_91_TREND_FOLLOWER}
DIRECT_ENTRY_STRATEGY_CODES = {CURRENT_HYBRID, EMA_CROSSOVER, AI_PATTERN_TRADER}
DYNAMIC_RISK_STRATEGY_CODES = {CURRENT_HYBRID, EMA_CROSSOVER, AI_PATTERN_TRADER}
