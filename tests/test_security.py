from __future__ import annotations

import pytest
from fastapi import HTTPException

from crypto_paper_trader_api.config import get_settings
from crypto_paper_trader_api.security import require_admin_key


def _reload_settings(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ADMIN_API_KEY", value)
    get_settings.cache_clear()


def test_admin_key_accepts_configured_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_settings(monkeypatch, "test-secret")
    require_admin_key("test-secret")


def test_admin_key_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_settings(monkeypatch, "test-secret")
    with pytest.raises(HTTPException) as error:
        require_admin_key("wrong-secret")
    assert error.value.status_code == 401


def test_admin_key_fails_closed_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_settings(monkeypatch, None)
    with pytest.raises(HTTPException) as error:
        require_admin_key(None)
    assert error.value.status_code == 503
