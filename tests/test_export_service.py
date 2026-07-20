from __future__ import annotations

from zipfile import ZipFile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.export_service import ExportService
from crypto_paper_trader_api.worker import create_experiment_record, ensure_strategy_accounts


def test_export_contains_strategy_files_and_no_html(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(data_dir=tmp_path, reports_dir=tmp_path / "reports")
    exporter = ExportService(settings)
    experiment = create_experiment_record("BTCUSDT", "30min", "1hour", 24, 1000, settings)
    experiment.last_price = 100

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        ensure_strategy_accounts(session, experiment)
        session.commit()

        archive_path = exporter.generate(session, experiment)

        assert archive_path.is_file()
        with ZipFile(archive_path) as archive:
            names = set(archive.namelist())
        assert "summary.json" in names
        assert "strategy_accounts.csv" in names
        assert "strategy_decisions.csv" in names
        assert "report.html" not in names
