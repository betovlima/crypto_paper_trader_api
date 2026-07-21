"""Backward-compatible imports for deployments that still reference coinex_client.

Version 0.13.0 migrated the public market-data provider from CoinEx to MEXC. New code
should import :mod:`crypto_paper_trader_api.mexc_client` directly.
"""

from .mexc_client import (  # noqa: F401
    MEXCAPIError as CoinExAPIError,
    MEXCPublicClient as CoinExPublicClient,
    MEXC_INTERVALS,
    TIMEFRAME_SECONDS,
)

__all__ = [
    "CoinExAPIError",
    "CoinExPublicClient",
    "MEXC_INTERVALS",
    "TIMEFRAME_SECONDS",
]
