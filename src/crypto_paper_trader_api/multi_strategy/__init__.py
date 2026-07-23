"""Strategy implementations grouped by trading demand.

The public imports remain compatible with the previous single ``multi_strategy.py`` module.
"""

from .common import StrategyDecision
from .hybrid import HybridComparisonStrategy
from .ema_crossover import EmaCrossoverStrategy
from .ema_pullback import EmaPullbackStrategy
from .stormer import StormerFilhaMalCriadaStrategy
from .larry_breakout import LarryVolatilityBreakoutStrategy
from .lbr_310 import Lbr310AntiContextStrategy
from .adaptive_selector import AdaptiveStrategySelector
from .ema9_setup import Ema9Setup91Strategy

__all__ = [
    "StrategyDecision",
    "HybridComparisonStrategy",
    "EmaCrossoverStrategy",
    "EmaPullbackStrategy",
    "StormerFilhaMalCriadaStrategy",
    "LarryVolatilityBreakoutStrategy",
    "Lbr310AntiContextStrategy",
    "AdaptiveStrategySelector",
    "Ema9Setup91Strategy",
]

# Backward-compatible name used by existing databases, workers and clients.
EmaCrossoverCostAwareStrategy = EmaCrossoverStrategy
__all__.append("EmaCrossoverCostAwareStrategy")
