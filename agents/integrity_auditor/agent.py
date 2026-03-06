"""
Integrity Auditor Agent

Responsibilities:
  1. Run periodic knowledge integrity scans
  2. Detect conflicts between claims
  3. Flag outdated claims for human review
  4. Generate integrity reports
  5. Trigger human review workflows for anomalies

Outputs:
  integrity_reports, revision_alerts, review_flags
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from core.governance.governance_manager import GovernanceManager
from core.verification.verification_engine import VerificationEngine

logger = logging.getLogger(__name__)


class IntegrityAuditorAgent(BaseAgent):
    """
    Continuously audits the claim ledger for conflicts, outdated knowledge,
    and governance violations.

    The Integrity Auditor is the last line of defence before AI-generated
    content reaches learners.  It surfaces issues for human review and never
    silently suppresses anomalies.
    """

    name = "integrity_auditor"

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.engine = VerificationEngine(session)

    async def _run(self, payload: dict) -> dict:
        """
        Payload keys:
          mode (str): "full" | "conflicts_only" | "outdated_only" | "escalate"
          max_age_days (int, optional): Override for outdated detection threshold
          escalate_high_confidence (bool, optional): Also escalate high-confidence claims
        """
        mode = payload.get("mode", "full")
        max_age_days = payload.get("max_age_days")
        escalate = payload.get("escalate_high_confidence", False)

        conflicts_found = 0
        outdated_found = 0
        flagged = 0
        escalated = 0
        report_id = None

        if mode == "full":
            report = await self.engine.run_full_audit()
            conflicts_found = report.conflicts_found
            outdated_found = report.outdated_claims
            flagged = report.flagged_for_review
            report_id = report.report_id

        elif mode == "conflicts_only":
            flags = await self.engine.detect_conflicts()
            conflicts_found = len(flags)
            for flag in flags:
                await self.engine.flag_claim_for_review(
                    flag.claim_a_id,
                    reason=f"Conflict with claim {flag.claim_b_id}: {flag.conflict_description}",
                )
                flagged += 1

        elif mode == "outdated_only":
            outdated = await self.engine.detect_outdated_claims(
                max_age_days=max_age_days
            )
            outdated_found = len(outdated)
            for claim in outdated:
                await self.engine.flag_claim_for_review(
                    claim.claim_id,
                    reason=f"Claim not updated in {max_age_days or 'threshold'} days.",
                )
                flagged += 1

        elif mode == "escalate":
            governance = GovernanceManager(self.session)
            high_conf = await governance.escalate_high_confidence_claims()
            escalated = len(high_conf)

        if escalate and mode != "escalate":
            governance = GovernanceManager(self.session)
            high_conf = await governance.escalate_high_confidence_claims()
            escalated = len(high_conf)

        logger.info(
            "Integrity audit (%s): %d conflicts, %d outdated, %d flagged, %d escalated",
            mode, conflicts_found, outdated_found, flagged, escalated,
        )

        return {
            "mode": mode,
            "conflicts_found": conflicts_found,
            "outdated_found": outdated_found,
            "flagged_for_review": flagged,
            "escalated_for_human_review": escalated,
            "report_id": report_id,
        }
