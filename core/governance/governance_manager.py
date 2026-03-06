"""
Universal Academy Engine — Governance Manager

Implements human-AI governance workflows.  AI agents propose; humans review
and override.  This module is the enforcement layer that ensures no AI
decision becomes permanent without appropriate human oversight.

Principles enforced:
  1. AI-generated content is always labelled.
  2. High-confidence claims (> threshold) require human sign-off.
  3. Human reviewers can override any AI decision.
  4. All governance actions are immutably logged.
"""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.schemas.models import (
    AgentRun, AgentRunStatus, Claim, ClaimStatus,
    ReviewStatus, VerificationLog
)

logger = logging.getLogger(__name__)


class GovernanceManager:
    """
    Central governance controller for the UAE.

    Provides:
    - Agent run lifecycle management
    - High-confidence claim escalation
    - Human override of AI decisions
    - Audit trail querying
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Agent run lifecycle
    # ------------------------------------------------------------------

    async def start_agent_run(self, agent_name: str, input_payload: dict) -> AgentRun:
        """Record the start of an agent execution."""
        from datetime import datetime
        run = AgentRun(
            agent_name=agent_name,
            input_payload=input_payload,
            status=AgentRunStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        self.session.add(run)
        await self.session.flush()
        logger.info("Agent run started: %s (%s)", agent_name, run.run_id)
        return run

    async def complete_agent_run(
        self,
        run_id: str,
        *,
        output_summary: dict | None = None,
        error_message: str | None = None,
    ) -> AgentRun:
        """Mark an agent run as completed or failed."""
        from datetime import datetime
        stmt = select(AgentRun).where(AgentRun.run_id == run_id)
        result = await self.session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            raise ValueError(f"AgentRun not found: {run_id!r}")

        run.completed_at = datetime.utcnow()
        run.output_summary = output_summary or {}
        if error_message:
            run.status = AgentRunStatus.FAILED
            run.error_message = error_message
        else:
            run.status = AgentRunStatus.COMPLETED
        await self.session.flush()
        logger.info("Agent run %s finished with status %s", run_id, run.status)
        return run

    async def list_agent_runs(
        self,
        *,
        agent_name: str | None = None,
        status: AgentRunStatus | None = None,
        limit: int = 50,
    ) -> List[AgentRun]:
        stmt = select(AgentRun)
        if agent_name:
            stmt = stmt.where(AgentRun.agent_name == agent_name)
        if status:
            stmt = stmt.where(AgentRun.status == status)
        stmt = stmt.order_by(AgentRun.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # High-confidence escalation
    # ------------------------------------------------------------------

    async def escalate_high_confidence_claims(self) -> List[Claim]:
        """
        Find verified claims with confidence above the governance threshold
        that lack a human review record and flag them for mandatory review.
        """
        threshold = settings.require_human_review_above_confidence
        stmt = select(Claim).where(
            Claim.status == ClaimStatus.VERIFIED,
            Claim.confidence_score >= threshold,
        )
        result = await self.session.execute(stmt)
        high_conf_claims = result.scalars().all()

        escalated = []
        for claim in high_conf_claims:
            # Check if a human review already exists
            log_stmt = select(VerificationLog).where(
                VerificationLog.claim_id == claim.claim_id,
                VerificationLog.is_ai_review == False,
            )
            log_result = await self.session.execute(log_stmt)
            human_log = log_result.scalar_one_or_none()

            if human_log is None:
                review_log = VerificationLog(
                    claim_id=claim.claim_id,
                    verification_result="needs_human_review",
                    reviewer="governance_manager",
                    is_ai_review=True,
                    notes=(
                        f"Claim confidence {claim.confidence_score:.2f} exceeds "
                        f"human review threshold {threshold:.2f}.  "
                        "Mandatory human sign-off required before this claim "
                        "may be used in published curriculum."
                    ),
                    review_status=ReviewStatus.ESCALATED,
                )
                self.session.add(review_log)
                escalated.append(claim)

        if escalated:
            await self.session.flush()
            logger.info("Escalated %d high-confidence claim(s) for human review.", len(escalated))

        return escalated

    # ------------------------------------------------------------------
    # Human override
    # ------------------------------------------------------------------

    async def human_override_claim(
        self,
        claim_id: str,
        new_status: ClaimStatus,
        *,
        reviewer: str,
        reason: str,
    ) -> Claim:
        """
        Allows a human reviewer to override the AI-assigned status of a claim.

        This is the ultimate governance escape hatch: humans always win.
        """
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is None:
            raise ValueError(f"Claim not found: {claim_id!r}")

        old_status = claim.status
        claim.status = new_status
        claim.version += 1

        # Log the override
        from database.schemas.models import ClaimRevision
        revision = ClaimRevision(
            claim_id=claim_id,
            previous_version=old_status.value,
            updated_version=new_status.value,
            change_reason=f"[HUMAN OVERRIDE] {reason}",
            changed_by=reviewer,
        )
        self.session.add(revision)

        override_log = VerificationLog(
            claim_id=claim_id,
            verification_result="human_override",
            reviewer=reviewer,
            is_ai_review=False,
            notes=f"Human override: {old_status.value} → {new_status.value}. {reason}",
            review_status=ReviewStatus.APPROVED,
        )
        self.session.add(override_log)
        await self.session.flush()
        logger.info(
            "Human override by %r on claim %r: %s → %s",
            reviewer, claim_id, old_status.value, new_status.value,
        )
        return claim

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    async def get_claim_audit_trail(self, claim_id: str) -> dict:
        """Return the full governance history for a claim."""
        from database.schemas.models import ClaimRevision
        rev_stmt = select(ClaimRevision).where(ClaimRevision.claim_id == claim_id).order_by(ClaimRevision.timestamp)
        rev_result = await self.session.execute(rev_stmt)
        revisions = rev_result.scalars().all()

        log_stmt = select(VerificationLog).where(VerificationLog.claim_id == claim_id).order_by(VerificationLog.timestamp)
        log_result = await self.session.execute(log_stmt)
        logs = log_result.scalars().all()

        return {
            "claim_id": claim_id,
            "revisions": [
                {
                    "revision_id": r.revision_id,
                    "from": r.previous_version,
                    "to": r.updated_version,
                    "reason": r.change_reason,
                    "changed_by": r.changed_by,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in revisions
            ],
            "verification_logs": [
                {
                    "log_id": l.log_id,
                    "result": l.verification_result,
                    "reviewer": l.reviewer,
                    "is_ai": l.is_ai_review,
                    "status": l.review_status.value,
                    "timestamp": l.timestamp.isoformat(),
                }
                for l in logs
            ],
        }
