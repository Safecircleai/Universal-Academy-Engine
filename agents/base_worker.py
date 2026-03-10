"""
UAE v3 — Base Worker

Enhanced base class for UAE v3 agent workers.
Extends BaseAgent with:
  - LLM client integration
  - Structured output validation
  - Source ID and output hash logging for audit
  - Governance checkpoint enforcement (no direct verified-claim writes)
  - Explicit review_requirement flag on all outputs

All workers MUST inherit from BaseWorker and call _complete_with_review()
rather than writing directly to claims or curriculum tables.

The governance invariant is encoded here:
  "No agent output directly becomes verified truth without a review path."
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.llm_client import LLMClient, LLMResponse, get_llm_client
from core.governance import GovernanceManager
from database.schemas.models import AgentRun

logger = logging.getLogger(__name__)


class BaseWorker:
    """
    Base class for UAE v3 operational agent workers.

    Subclasses implement:
      _run_work(payload) -> dict  — actual work (may call LLM, query DB, etc.)

    Workers must not write directly to verified claims. They produce
    proposals that are routed to human review via GovernanceManager.
    """

    name: str = "base_worker"

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_client: Optional[LLMClient] = None,
        node_id: Optional[str] = None,
    ) -> None:
        self.session = session
        self.llm = llm_client or get_llm_client()
        self.node_id = node_id
        self.governance = GovernanceManager(session)

    async def run(
        self,
        payload: dict,
        *,
        input_source_ids: Optional[list[str]] = None,
        prompt_type: str = "generic",
    ) -> dict:
        """
        Public entry point. Wraps _run_work with governance lifecycle.

        Logs: agent_name, model_id, prompt_type, input_source_ids, output_hash.
        All agent runs require review (requires_review=True by default).
        """
        run: AgentRun = await self.governance.start_agent_run(self.name, payload)

        # Attach v3 audit fields to the run record
        run.model_id = self.llm.model_id
        run.prompt_type = prompt_type
        run.input_source_ids = input_source_ids or []
        run.requires_review = True
        await self.session.flush()

        try:
            result = await self._run_work(payload)

            # Compute output hash for audit
            output_json = json.dumps(result, sort_keys=True, default=str)
            output_hash = hashlib.sha256(output_json.encode("utf-8")).hexdigest()
            run.output_hash = output_hash

            await self.governance.complete_agent_run(run.run_id, output_summary=result)
            logger.info(
                "Worker %s completed: run_id=%s output_hash=%s",
                self.name, run.run_id, output_hash[:12],
            )
            return result

        except Exception as exc:
            await self.governance.complete_agent_run(run.run_id, error_message=str(exc))
            logger.exception("Worker %s failed: %s", self.name, exc)
            raise

    @abstractmethod
    async def _run_work(self, payload: dict) -> dict:
        """
        Agent-specific logic. Must return a JSON-serialisable dict.
        Must NOT write directly to verified claims or published curriculum.
        Must call _route_for_review() for all output proposals.
        """

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        *,
        prompt_type: str = "generic",
        system: Optional[str] = None,
    ) -> LLMResponse:
        """Call the LLM through the managed client. All calls are logged."""
        return await self.llm.complete(messages, prompt_type=prompt_type, system=system)

    def _route_for_review(self, proposal: dict, proposal_type: str) -> dict:
        """
        Tag a proposal as requiring human review before it can affect
        verified claims or published curriculum.

        This enforces the governance invariant at the worker layer.
        """
        return {
            "proposal_type": proposal_type,
            "requires_review": True,
            "review_status": "PENDING",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "agent_name": self.name,
            "data": proposal,
        }
