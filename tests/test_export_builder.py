from __future__ import annotations

from zipfile import ZipFile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.export_builder import ExportBuilder
from crypto_paper_trader_api.worker import create_experiment_record, ensure_strategy_accounts


def test_export_is_built_in_memory_without_server_files(tmp_path) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = Settings(data_dir=tmp_path)
    builder = ExportBuilder()
    experiment = create_experiment_record(
        "BTCUSDT", "30min", "1hour", 24, 1000, settings
    )
    experiment.last_price = 100

    with Session(engine) as session:
        session.add(experiment)
        session.flush()
        ensure_strategy_accounts(session, experiment)
        session.commit()

        bundle = builder.build_bundle(session, experiment)
        with ZipFile(bundle) as archive:
            names = set(archive.namelist())

    assert "summary.json" in names
    assert "strategy_accounts.csv" in names
    assert "strategy_decisions.csv" in names
    assert "report.html" not in names
    assert list(tmp_path.iterdir()) == []
