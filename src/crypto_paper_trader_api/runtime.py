from __future__ import annotations

from .ai_opportunity_scanner import AIOpportunityScanner
from .config import get_settings
from .worker import TraderWorker

settings = get_settings()
worker = TraderWorker(settings)
ai_scanner = AIOpportunityScanner(settings)
