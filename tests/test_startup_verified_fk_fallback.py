from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from crypto_paper_trader_api import database
from crypto_paper_trader_api.database import Base
from crypto_paper_trader_api.models import StrategyAccount
from crypto_paper_trader_api.services import startup_service
from crypto_paper_trader_api.worker import ACTIVE_STRATEGY_CODES, create_experiment_record


def test_verified_fk_bypass_commits_only_integrity_safe_accounts(tmp_path, monkeypatch) -> None:
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'verified-fallback.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)

    experiment = create_experiment_record(
        "BTCUSDT",
        "30min",
        "1hour",
        24,
        1000,
    )
    experiment_id = experiment.id
    with Session(test_engine) as session:
        session.add(experiment)
        session.commit()

    monkeypatch.setattr(database, "engine", test_engine)

    startup_service._synchronize_strategy_accounts_with_verified_fk_bypass()

    with Session(test_engine) as session:
        accounts = list(
            session.scalars(
                select(StrategyAccount).where(
                    StrategyAccount.experiment_id == experiment_id
                )
            )
        )
    assert {account.strategy_code for account in accounts} == set(ACTIVE_STRATEGY_CODES)

    with test_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def test_verified_fk_bypass_is_a_noop_without_experiments(tmp_path, monkeypatch) -> None:
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'empty-fallback.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    monkeypatch.setattr(database, "engine", test_engine)

    startup_service._synchronize_strategy_accounts_with_verified_fk_bypass()

    with Session(test_engine) as session:
        assert list(session.scalars(select(StrategyAccount))) == []
    with test_engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []


def test_verified_fk_bypass_does_not_block_on_unrelated_legacy_violation(
    tmp_path, monkeypatch
) -> None:
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy-unrelated-violation.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)

    experiment = create_experiment_record(
        "ETHUSDT",
        "30min",
        "1hour",
        24,
        1000,
    )
    experiment_id = experiment.id
    with Session(test_engine) as session:
        session.add(experiment)
        session.commit()

    raw = test_engine.raw_connection()
    cursor = raw.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("CREATE TABLE legacy_parent (id INTEGER PRIMARY KEY)")
        cursor.execute(
            "CREATE TABLE legacy_child ("
            "id INTEGER PRIMARY KEY, "
            "parent_id INTEGER REFERENCES legacy_parent(id)"
            ")"
        )
        cursor.execute("INSERT INTO legacy_child (id, parent_id) VALUES (1, 999)")
        raw.commit()
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()
        raw.close()

    monkeypatch.setattr(database, "engine", test_engine)

    startup_service._synchronize_strategy_accounts_with_verified_fk_bypass()

    with Session(test_engine) as session:
        accounts = list(
            session.scalars(
                select(StrategyAccount).where(
                    StrategyAccount.experiment_id == experiment_id
                )
            )
        )
    assert {account.strategy_code for account in accounts} == set(ACTIVE_STRATEGY_CODES)

    with test_engine.connect() as connection:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    assert any(row[0] == "legacy_child" for row in violations)
    assert not any(row[0] == "strategy_accounts" for row in violations)


def test_startup_falls_back_to_parent_row_copy_after_two_orm_fk_failures(
    tmp_path, monkeypatch
) -> None:
    import sqlite3

    from sqlalchemy.exc import IntegrityError

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'parent-row-fallback.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)

    experiment = create_experiment_record(
        "SOLUSDT",
        "30min",
        "1hour",
        24,
        1000,
    )
    experiment_id = experiment.id
    with Session(test_engine) as session:
        session.add(experiment)
        session.commit()

    monkeypatch.setattr(database, "engine", test_engine)

    failures = iter(
        [
            IntegrityError(
                "INSERT INTO strategy_accounts",
                {},
                sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
            ),
            IntegrityError(
                "INSERT INTO strategy_accounts",
                {},
                sqlite3.IntegrityError("FOREIGN KEY constraint failed"),
            ),
        ]
    )

    def fail_orm_sync() -> None:
        raise next(failures)

    monkeypatch.setattr(startup_service, "_synchronize_strategy_accounts_once", fail_orm_sync)

    startup_service.synchronize_strategy_accounts()

    with Session(test_engine) as session:
        accounts = list(
            session.scalars(
                select(StrategyAccount).where(
                    StrategyAccount.experiment_id == experiment_id
                )
            )
        )
    assert {account.strategy_code for account in accounts} == set(ACTIVE_STRATEGY_CODES)

    with test_engine.connect() as connection:
        assert connection.exec_driver_sql(
            'PRAGMA foreign_key_check("strategy_accounts")'
        ).fetchall() == []
