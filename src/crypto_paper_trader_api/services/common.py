from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..models import Experiment


def get_experiment_or_404(session: Session, experiment_id: str) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Experiment not found.",
        )
    return experiment
