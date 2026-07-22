from __future__ import annotations

CURRENT_HYBRID = "CURRENT_HYBRID"

# Persisted values are retained for compatibility with existing SQLite databases.
# Fees are accounting-only and never veto technical signals.
EMA_CROSSOVER_COST_AWARE = "EMA_CROSSOVER_COST_AWARE"
EMA_CROSSOVER = EMA_CROSSOVER_COST_AWARE
EMA_PULLBACK = "EMA_PULLBACK"

EMA9_SETUP_91 = "EMA9_SETUP_91"
EMA9_SETUP_91_COST_AWARE = "EMA9_SETUP_91_COST_AWARE"

# The existing persisted Larry code remains the classic implementation so previous
# experiments keep their accounts and history after the upgrade.
LARRY_WILLIAMS_91_CLASSIC = EMA9_SETUP_91_COST_AWARE
LARRY_WILLIAMS_91 = LARRY_WILLIAMS_91_CLASSIC
LARRY_WILLIAMS_91_TREND_FOLLOWER = "EMA9_SETUP_91_TREND_FOLLOWER"
LARRY_VOLATILITY_BREAKOUT = "LARRY_VOLATILITY_BREAKOUT"
STORMER_FILHA_MAL_CRIADA = "STORMER_FILHA_MAL_CRIADA"

AI_PATTERN_TRADER = "AI_PATTERN_TRADER"
ADAPTIVE_STRATEGY_SELECTOR = "ADAPTIVE_STRATEGY_SELECTOR"
BUY_AND_HOLD = "BUY_AND_HOLD"

# The selector is shown first, but worker evaluation computes all candidate decisions
# before resolving the selector decision for the same closed candle.
ACTIVE_STRATEGY_CODES = (
    ADAPTIVE_STRATEGY_SELECTOR,
    CURRENT_HYBRID,
    EMA_CROSSOVER,
    EMA_PULLBACK,
    LARRY_WILLIAMS_91_CLASSIC,
    LARRY_WILLIAMS_91_TREND_FOLLOWER,
    LARRY_VOLATILITY_BREAKOUT,
    STORMER_FILHA_MAL_CRIADA,
)

STRATEGY_DISPLAY_NAMES = {
    ADAPTIVE_STRATEGY_SELECTOR: "Adaptive Strategy Selector",
    CURRENT_HYBRID: "Profile-Aware Hybrid",
    EMA_CROSSOVER: "EMA Crossover",
    EMA_PULLBACK: "EMA Pullback",
    EMA9_SETUP_91: "Larry Williams 9.1 Classic",
    LARRY_WILLIAMS_91_CLASSIC: "Larry Williams 9.1 Classic",
    LARRY_WILLIAMS_91_TREND_FOLLOWER: "Larry Williams 9.1 Trend Follower",
    LARRY_VOLATILITY_BREAKOUT: "Larry Volatility Breakout",
    STORMER_FILHA_MAL_CRIADA: "Stormer Filha Mal Criada",
    AI_PATTERN_TRADER: "AI Pattern Trader",
    BUY_AND_HOLD: "Buy and Hold",
}

STRATEGY_DESCRIPTIONS = {
    ADAPTIVE_STRATEGY_SELECTOR: (
        "Detects the current market regime, researches new executable strategy hypotheses, "
        "backtests them with trading costs, validates them with chronological walk-forward "
        "windows and activates only a generated strategy that passes risk and stability gates."
    ),
    CURRENT_HYBRID: (
        "Combines the selected profile's EMAs, RSI, ADX, relative volume and XGBoost "
        "direction probability. Exchange fees are recorded after execution and never veto "
        "a valid technical signal."
    ),
    EMA_CROSSOVER: (
        "Buys after a fresh fast-EMA crossover above the slow EMA, with trend, ADX, volume "
        "and RSI confirmation. Fees affect the reported net result, not the signal."
    ),
    EMA_PULLBACK: (
        "Trades a pullback inside an established bullish EMA structure. Price must return "
        "toward the fast or slow EMA and close back above the fast EMA with trend and volume "
        "confirmation."
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
    LARRY_VOLATILITY_BREAKOUT: (
        "Intraday volatility breakout inspired by Larry Williams. It compares the current "
        "price with an open-plus-range trigger, requires trend and volume confirmation, and "
        "uses ATR-based stop and target levels."
    ),
    STORMER_FILHA_MAL_CRIADA: (
        "Trend-following pullback setup based on a ribbon of seven aligned exponential moving "
        "averages (20, 25, 30, 35, 40, 45 and 50). It arms an entry above the pullback candle, "
        "places the initial stop below the next untouched EMA and targets three times the risk."
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
DIRECT_ENTRY_STRATEGY_CODES = {
    CURRENT_HYBRID,
    EMA_CROSSOVER,
    EMA_PULLBACK,
    LARRY_VOLATILITY_BREAKOUT,
    STORMER_FILHA_MAL_CRIADA,
    AI_PATTERN_TRADER,
    ADAPTIVE_STRATEGY_SELECTOR,
}
DYNAMIC_RISK_STRATEGY_CODES = {
    CURRENT_HYBRID,
    EMA_CROSSOVER,
    EMA_PULLBACK,
    LARRY_VOLATILITY_BREAKOUT,
    STORMER_FILHA_MAL_CRIADA,
    AI_PATTERN_TRADER,
    ADAPTIVE_STRATEGY_SELECTOR,
}

