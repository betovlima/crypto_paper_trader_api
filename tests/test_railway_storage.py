from pathlib import Path

from crypto_paper_trader_api.config import Settings


def test_railway_volume_mount_is_preferred(monkeypatch, tmp_path: Path) -> None:
    mount_path = tmp_path / "railway-volume"
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(mount_path))
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    settings = Settings(data_dir=tmp_path / "ephemeral-data")

    assert settings.resolved_data_dir == mount_path.resolve()
    assert settings.persistent_storage_configured is True
    assert settings.storage_warning is None
    assert settings.resolved_database_url.endswith(
        "/railway-volume/crypto_paper_trader_api.db"
    )


def test_railway_without_volume_reports_persistence_warning(monkeypatch) -> None:
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    settings = Settings(app_env="production")

    assert settings.resolved_data_dir == Path("/data")
    assert settings.persistent_storage_configured is False
    assert settings.storage_warning is not None
    assert "lost on every deploy" in settings.storage_warning


def test_railway_without_volume_fails_fast(monkeypatch) -> None:
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    settings = Settings(app_env="production")

    try:
        settings.validate_persistent_storage()
    except RuntimeError as exc:
        assert "persistent volume is required" in str(exc)
    else:
        raise AssertionError("Railway startup must fail without a persistent volume")


def test_railway_volume_ignores_conflicting_database_url(monkeypatch, tmp_path: Path) -> None:
    mount_path = tmp_path / "railway-volume"
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", str(mount_path))
    monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

    settings = Settings(database_url="sqlite:///./data/wrong.db")

    assert settings.resolved_database_url == (
        f"sqlite:///{mount_path.resolve().as_posix()}/crypto_paper_trader_api.db"
    )
