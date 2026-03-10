"""
UAE v3 — Integrity Auditor Worker

Monitors claim integrity:
  - Detects potential conflicts between claims
  - Flags claims that may be outdated (based on age/supersedence)
  - Proposes conflicts for human resolution (via ConflictFlag)
  - Does NOT auto-deprecate or auto-resolve conflicts

Governance boundary:
  - Worker proposes conflicts and outdated flags
  - Human review required before any claim status change
  - Audit trail created for every run via AgentRun record
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_worker import BaseWorker
from agents.llm_client import LLMClient
from agents.structured_outputs import IntegrityAuditOutput, parse_agent_output
from database.schemas.models import Claim, ClaimStatus

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a knowledge integrity specialist reviewing a set of educational claims.
Your task is to identify potential conflicts between claims and flag outdated content.

Return a JSON object matching this schema:
{
  "total_claims_checked": <int>,
  "proposed_conflicts": [
    {
      "claim_a_id": "<claim_id>",
      "claim_b_id": "<claim_id>",
      "conflict_description": "<specific description of the conflict>",
      "severity": "low" | "medium" | "high"
    }
  ],
  "outdated_claim_ids": ["<claim_id>", ...],
  "flagged_claim_ids": ["<claim_id>", ...],
  "summary": "<overall integrity assessment>",
  "requires_human_review": true
}

Rules:
- Only flag genuine semantic conflicts (not stylistic differences)
- Outdated: claim references superseded standards, expired dates, or deprecated practices
- Flagged: claims that need verification but may not conflict
- Do not flag if you are not confident — false positives undermine trust
- Always set requires_human_review=true"""


class IntegrityAuditorWorker(BaseWorker):
    """
    Monitors claim integrity and proposes conflicts for human resolution.
    Never auto-resolves or auto-deprecates claims.
    """

    name = "integrity_auditor_worker"

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_client: Optional[LLMClient] = None,
        node_id: Optional[str] = None,
        auto_deprecate_days: int = 730,
    ) -> None:
        super().__init__(session, llm_client=llm_client, node_id=node_id)
        self.auto_deprecate_days = auto_deprecate_days

    async def _run_work(self, payload: dict) -> dict:
        """
        Payload expected keys:
          claim_ids  — list of claim IDs to audit (optional, defaults to all verified)
          max_claims — max claims to analyse per run (default: 100)
          node_id    — node scope (optional)
        """
        claim_ids_input = payload.get("claim_ids", [])
        max_claims = payload.get("max_claims", 100)

        # Fetch claims to audit
        if claim_ids_input:
            stmt = (
                select(Claim)
                .where(Claim.claim_id.in_(claim_ids_input))
                .where(Claim.status == ClaimStatus.VERIFIED)
                .limit(max_claims)
            )
        else:
            stmt = (
                select(Claim)
                .where(Claim.status == ClaimStatus.VERIFIED)
                .limit(max_claims)
            )

        result = await self.session.execute(stmt)
        claims = list(result.scalars().all())

        if not claims:
            return self._route_for_review(
                {
                    "total_claims_checked": 0,
                    "proposed_conflicts": [],
                    "outdated_claim_ids": [],
                    "flagged_claim_ids": [],
                    "summary": "No verified claims to audit.",
                    "requires_human_review": True,
                },
                "integrity_audit",
            )

        # Pre-filter obviously outdated (age-based) without LLM
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.auto_deprecate_days)
        age_outdated = []
        for c in claims:
            created = c.created_at
            if created and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created and created < cutoff:
                age_outdated.append(c.claim_id)

        # Send to LLM for semantic conflict detection
        claim_summaries = "\n".join(
            f"[{c.claim_id}] {c.statement}"
            for c in claims[:50]  # Limit to first 50 for LLM context
        )

        user_message = f"""Audit these educational claims for conflicts and integrity issues.

Claims to review:
{claim_summaries}

Age-flagged claim IDs (older than {self.auto_deprecate_days} days): {age_outdated}

Total claims in batch: {len(claims)}

Return the integrity audit JSON."""

        response = await self._call_llm(
            messages=[{"role": "user", "content": user_message}],
            prompt_type="integrity_audit",
            system=_SYSTEM_PROMPT,
        )

        try:
            validated = parse_agent_output(response.content, IntegrityAuditOutput)
        except Exception as exc:
            logger.warning("Integrity auditor output validation failed: %s", exc)
            validated = IntegrityAuditOutput(
                total_claims_checked=len(claims),
                proposed_conflicts=[],
                outdated_claim_ids=age_outdated,
                flagged_claim_ids=[],
                summary=f"Audit run completed with validation error: {exc}. Manual review required.",
                requires_human_review=True,
            )

        proposal = validated.model_dump()
        # Merge age-based outdated with LLM-detected
        all_outdated = list(set(proposal["outdated_claim_ids"] + age_outdated))
        proposal["outdated_claim_ids"] = all_outdated

        return {
            **self._route_for_review(proposal, "integrity_audit"),
            "llm_audit": response.to_audit_record(),
        }
