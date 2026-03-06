"""
Universal Academy Engine — Base Agent

All UAE agents inherit from this base class, which provides:
  - Governance lifecycle hooks (start / complete run)
  - Structured logging
  - Error handling with run status propagation
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.governance import GovernanceManager
from database.schemas.models import AgentRun

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """
    Abstract base for all UAE pipeline agents.

    Subclasses implement ``_run(payload)`` and call ``run(payload)`` from the
    outside.  The base class handles the governance lifecycle and error
    propagation automatically.
    """

    name: str = "base_agent"

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.governance = GovernanceManager(session)

    async def run(self, payload: dict) -> dict:
        """
        Public entry point.  Wraps ``_run`` with governance bookkeeping.
        """
        run: AgentRun = await self.governance.start_agent_run(
            self.name, payload
        )
        try:
            result = await self._run(payload)
            await self.governance.complete_agent_run(
                run.run_id, output_summary=result
            )
            return result
        except Exception as exc:
            await self.governance.complete_agent_run(
                run.run_id, error_message=str(exc)
            )
            logger.exception("Agent %s failed: %s", self.name, exc)
            raise

    @abstractmethod
    async def _run(self, payload: dict) -> dict:
        """Agent-specific logic.  Must return a JSON-serialisable dict."""
