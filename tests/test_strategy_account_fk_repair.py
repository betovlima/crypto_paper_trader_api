from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from crypto_paper_trader_api import database
from crypto_paper_trader_api.config import Settings
from crypto_paper_trader_api.models import Experiment, StrategyAccount
from crypto_paper_trader_api.worker import create_experiment_record, ensure_strategy_accounts


def test_repairs_legacy_strategy_account_parent_foreign_key(tmp_path, monkeypatch) -> None:
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}",
        connect_args={"check_same_thread": False},
    )

    experiment_sql = str(CreateTable(Experiment.__table__).compile(dialect=test_engine.dialect))
    strategy_sql = str(
        CreateTable(StrategyAccount.__table__).compile(dialect=test_engine.dialect)
    ).replace(
        "REFERENCES experiments (id)",
        "REFERENCES experiments_legacy (id)",
    )

    with test_engine.begin() as connection:
        connection.exec_driver_sql(experiment_sql)
        connection.exec_driver_sql(
            "CREATE TABLE experiments_legacy (id VARCHAR(36) PRIMARY KEY)"
        )
        connection.exec_driver_sql(strategy_sql)

    monkeypatch.setattr(database, "engine", test_engine)

    assert database.repair_strategy_accounts_schema() is True

    with test_engine.connect() as connection:
        foreign_keys = connection.exec_driver_sql(
            'PRAGMA foreign_key_list("strategy_accounts")'
        ).fetchall()
    experiment_links = [row for row in foreign_keys if row[3] == "experiment_id"]
    assert len(experiment_links) == 1
    assert experiment_links[0][2] == "experiments"
    assert experiment_links[0][4] == "id"

    experiment = create_experiment_record(
        "BTCUSDT",
        "30min",
        "1hour",
        24,
        1000,
        Settings(),
    )
    with Session(test_engine) as session:
        session.add(experiment)
        session.flush()
        accounts = ensure_strategy_accounts(session, experiment)
        session.commit()

    assert accounts
    with test_engine.connect() as connection:
        assert connection.exec_driver_sql(
            'PRAGMA foreign_key_check("strategy_accounts")'
        ).fetchall() == []
