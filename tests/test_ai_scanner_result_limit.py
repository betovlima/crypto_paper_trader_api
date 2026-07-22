from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import MethodType

from crypto_paper_trader_api.ai_opportunity_scanner import AIOpportunityScanner
from crypto_paper_trader_api.config import Settings


class _TenMarketClient:
    async def get_24h_tickers(self):
        return [
            {
                "symbol": f"COIN{index}USDT",
                "quoteVolume": str(1_000_000 - index),
                "lastPrice": "1",
            }
            for index in range(10)
        ]

    async def close(self):
        return None


def _candidate(market: str, scanned_at: datetime, score: float) -> dict[str, object]:
    return {
        "market": market,
        "score": score,
        "action": "HOLD",
        "market_price": 1.0,
        "entry_zone_low": 0.99,
        "entry_zone_high": 1.01,
        "trigger_price": 1.01,
        "stop_loss_price": None,
        "target_price": None,
        "regime": "RANGE",
        "confidence": 0.55,
        "upward_probability": 0.45,
        "expected_net_return": -0.001,
        "quote_volume_24h": 1_000_000.0,
        "spread_rate": 0.0001,
        "training_samples": 250,
        "model_version": "TEST",
        "reason": "test",
        "scanned_at": scanned_at,
    }


def test_scanner_defaults_to_ten_persisted_results() -> None:
    settings = Settings()
    assert settings.ai_scanner_universe_size == 10
    assert settings.ai_scanner_result_limit == 10


def test_scan_persists_all_ten_ranked_markets_by_default() -> None:
    scanner = AIOpportunityScanner(Settings())
    scanner.client = _TenMarketClient()
    persisted: list[dict[str, object]] = []

    async def fake_evaluate(
        self,
        market,
        quote_volume,
        scanned_at,
        market_index,
        total_markets,
        successful_markets,
        failed_markets,
    ):
        return _candidate(market, scanned_at, float(100 - market_index))

    def fake_persist(self, scan_id, selected):
        persisted.extend(selected)

    scanner._evaluate_market = MethodType(fake_evaluate, scanner)
    scanner._persist_scan = MethodType(fake_persist, scanner)
    scanner._save_state = MethodType(lambda self, **kwargs: None, scanner)

    asyncio.run(scanner.scan_once())

    assert len(persisted) == 10
    assert [row["market"] for row in persisted] == [
        f"COIN{index}USDT" for index in range(10)
    ]
    assert scanner.progress_snapshot()["classified_opportunities"] == 10
