from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from types import MethodType

from crypto_paper_trader_api.ai_opportunity_models import AIOpportunitySnapshot
from crypto_paper_trader_api.ai_opportunity_scanner import AIOpportunityScanner
from crypto_paper_trader_api.config import Settings


class _FakeClient:
    async def get_24h_tickers(self):
        return [
            {"symbol": "BTCUSDT", "quoteVolume": "1000000", "lastPrice": "60000"},
            {"symbol": "ETHUSDT", "quoteVolume": "900000", "lastPrice": "3000"},
        ]

    async def close(self):
        return None


def _candidate(market: str, scanned_at: datetime) -> dict[str, object]:
    return {
        "market": market,
        "score": 50.0,
        "action": "WATCH",
        "market_price": 1.0,
        "entry_zone_low": 0.99,
        "entry_zone_high": 1.01,
        "trigger_price": 1.01,
        "stop_loss_price": 0.98,
        "target_price": 1.03,
        "regime": "RANGE",
        "confidence": 0.6,
        "upward_probability": 0.55,
        "expected_net_return": 0.001,
        "quote_volume_24h": 1000000.0,
        "spread_rate": 0.0001,
        "training_samples": 800,
        "model_version": "TEST",
        "reason": "test",
        "scanned_at": scanned_at,
    }


def test_scan_progress_reaches_ready_without_blocking_persistence() -> None:
    scanner = AIOpportunityScanner(Settings(ai_scanner_universe_size=3))
    scanner.client = _FakeClient()

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
        self._set_progress(
            status="TRAINING_MODELS",
            progress_percent=self._market_progress(market_index - 1, total_markets, 0.5),
            current_step=4,
            current_market=market,
            current_market_index=market_index,
            total_markets=total_markets,
            training_window=800,
        )
        await asyncio.sleep(0)
        return _candidate(market, scanned_at)

    scanner._evaluate_market = MethodType(fake_evaluate, scanner)
    scanner._save_state = MethodType(lambda self, **kwargs: None, scanner)
    scanner._persist_scan = MethodType(lambda self, scan_id, selected: None, scanner)

    asyncio.run(scanner.scan_once())
    progress = scanner.progress_snapshot()

    assert progress["status"] == "READY"
    assert progress["progress_percent"] == 100
    assert progress["analyzed_markets"] == 2
    assert progress["classified_opportunities"] == 2
    assert progress["current_market"] is None
    assert progress["last_activity_at"] is not None


def test_training_heartbeat_refreshes_last_activity() -> None:
    scanner = AIOpportunityScanner(Settings())
    scanner._set_progress(status="TRAINING_MODELS")
    before = scanner.progress_snapshot()["last_activity_at"]

    result = asyncio.run(
        scanner._run_in_thread_with_heartbeat(
            lambda: (time.sleep(0.05), "done")[1],
            heartbeat_seconds=0.01,
        )
    )
    after = scanner.progress_snapshot()["last_activity_at"]

    assert result == "done"
    assert after is not None
    assert before is not None
    assert after >= before


def test_market_progress_is_bounded_and_monotonic() -> None:
    values = [
        AIOpportunityScanner._market_progress(index, 10, 0.0)
        for index in range(0, 11)
    ]

    assert values[0] == 15
    assert values[-1] == 90
    assert values == sorted(values)


def test_snapshot_payload_excludes_transient_scanner_diagnostics() -> None:
    candidate = _candidate("BTCUSDT", datetime.now(timezone.utc))
    candidate.update(
        {
            "downloaded_execution_candles": 499,
            "downloaded_trend_candles": 499,
            "required_training_samples": 250,
            "missing_training_samples": 0,
            "selected_training_window": 295,
            "validation_accuracy": 0.54,
            "validation_mae": 0.01,
            "risk_status": "OBSERVATION",
            "risk_reason": "Diagnostic-only field.",
        }
    )

    payload = AIOpportunityScanner._snapshot_payload(candidate)

    assert payload["market"] == "BTCUSDT"
    assert payload["training_samples"] == 800
    assert "downloaded_execution_candles" not in payload
    assert "downloaded_trend_candles" not in payload
    assert "required_training_samples" not in payload
    assert "missing_training_samples" not in payload
    assert "selected_training_window" not in payload
    assert "validation_accuracy" not in payload
    assert "validation_mae" not in payload
    assert "risk_status" not in payload
    assert "risk_reason" not in payload

    snapshot = AIOpportunitySnapshot(
        scan_id="00000000-0000-0000-0000-000000000001",
        rank=1,
        **payload,
    )
    assert snapshot.market == "BTCUSDT"
