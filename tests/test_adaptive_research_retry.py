from __future__ import annotations

import asyncio

import crypto_paper_trader_api.worker as worker_module
from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.worker import TraderWorker


def test_retry_research_requests_forced_refresh_and_configuration_reload(monkeypatch) -> None:
    worker = TraderWorker(Settings(openai_api_key="old-key"))
    captured: dict[str, object] = {}

    async def fake_refresh(**kwargs):
        captured.update(kwargs)
        return {"experiment_id": kwargs["experiment_id"]}

    monkeypatch.setattr(worker, "_refresh_waiting_selector_history", fake_refresh)

    try:
        result = asyncio.run(worker.retry_adaptive_selector_research("experiment-1"))
    finally:
        asyncio.run(worker.client.close())

    assert result["experiment_id"] == "experiment-1"
    assert captured == {
        "force": True,
        "force_research": True,
        "reload_openai_configuration": True,
        "experiment_id": "experiment-1",
    }


def test_reload_adaptive_research_configuration_rebuilds_selector(monkeypatch) -> None:
    worker = TraderWorker(Settings(openai_api_key="old-key"))
    refreshed = Settings(
        openai_api_key="new-key",
        adaptive_research_openai_model="gpt-5",
        selector_model_version="ADAPTIVE-RESEARCH-SELECTOR-v6-MANUAL-RESEARCH-RETRY",
    )
    monkeypatch.setattr(worker_module, "Settings", lambda: refreshed)

    try:
        result = worker._reload_adaptive_research_configuration()
    finally:
        asyncio.run(worker.client.close())

    assert result == {
        "openai_configuration_reloaded": True,
        "openai_configured": True,
        "openai_key_source": refreshed.openai_api_key_source,
    }
    assert worker.settings.openai_api_key == "new-key"
    assert worker.adaptive_selector.settings is worker.settings
    assert worker.adaptive_selector.engine.web.settings.openai_api_key == "new-key"
