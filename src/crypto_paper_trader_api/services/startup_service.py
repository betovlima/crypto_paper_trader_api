from __future__ import annotations

from sqlalchemy import select

from ..database import SessionLocal
from ..models import Experiment
from ..worker import ensure_strategy_accounts


def synchronize_strategy_accounts() -> None:
    """Create newly introduced strategy accounts for existing experiments at startup.

    This is an explicit startup migration. Read-only GET endpoints never create or update
    accounts, which keeps HTTP responsibilities predictable and auditable.
    """

    with SessionLocal() as session:
        experiments = list(session.scalars(select(Experiment)))
        for experiment in experiments:
            ensure_strategy_accounts(session, experiment)
        if experiments:
            session.commit()
