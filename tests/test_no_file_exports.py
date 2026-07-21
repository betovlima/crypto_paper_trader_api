from __future__ import annotations

from crypto_paper_trader_api.app import app
from crypto_paper_trader_api.config import Settings


def test_file_export_routes_are_not_registered() -> None:
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/v1/experiments/{experiment_id}/export-bundle" not in paths
    assert "/api/v1/experiments/{experiment_id}/report-bundle" not in paths


def test_settings_has_no_report_directory_configuration() -> None:
    settings = Settings()

    assert "reports_dir" not in Settings.model_fields
    assert not hasattr(settings, "resolved_reports_dir")
