from __future__ import annotations

from pathlib import Path

from pydantic_settings import SettingsConfigDict

import crypto_paper_trader_api.config as config_module
from crypto_paper_trader_api.config import PROJECT_ENV_FILE, Settings


def test_default_env_file_is_bound_to_api_project_root() -> None:
    expected = Path(config_module.__file__).resolve().parents[2] / ".env"
    assert Path(Settings.model_config["env_file"]) == PROJECT_ENV_FILE
    assert PROJECT_ENV_FILE == expected


def test_local_dotenv_overrides_stale_process_key(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-local-current-key-1234567890\n", encoding="utf-8")
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-stale-process-key-1234567890")

    class LocalSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=str(env_file),
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

    settings = LocalSettings()
    assert settings.openai_api_key == "sk-local-current-key-1234567890"


def test_railway_process_variable_keeps_precedence(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=sk-local-file-key-1234567890\n", encoding="utf-8")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-railway-variable-key-1234567890")

    class RailwaySettings(Settings):
        model_config = SettingsConfigDict(
            env_file=str(env_file),
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

    settings = RailwaySettings()
    assert settings.openai_api_key == "sk-railway-variable-key-1234567890"
    assert settings.openai_api_key_source == "RAILWAY_VARIABLE"


def test_secret_normalization_removes_accidental_bearer_and_quotes() -> None:
    settings = Settings(
        _env_file=None,
        openai_api_key='  "Bearer sk-normalized-key-1234567890"  ',
    )
    assert settings.openai_api_key == "sk-normalized-key-1234567890"
