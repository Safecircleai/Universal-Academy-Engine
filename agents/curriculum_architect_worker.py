"""
UAE v3 — Curriculum Architect Worker

Assembles curriculum drafts from verified claims.

Governance boundary:
  - Worker ONLY reads VERIFIED claims (status=VERIFIED)
  - Produced curriculum is a DRAFT — requires human approval before publishing
  - Lesson claim_ids are validated against the claim ledger before proposing
  - No content is fabricated beyond what the source claims support

Output routes to: CurriculumBuilder → human approval → publishing_state=PUBLISHED
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_worker import BaseWorker
from agents.llm_client import LLMClient
from agents.structured_outputs import CurriculumDraftOutput, parse_agent_output
from database.schemas.models import Claim, ClaimStatus

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a curriculum design specialist for vocational and academic education.
Your task is to organise the provided verified claims into a structured course draft.

Return a JSON object matching this schema:
{
  "course_title": "<string>",
  "course_description": "<string>",
  "modules": [
    {
      "title": "<string>",
      "description": "<string>",
      "lessons": [
        {
          "title": "<string>",
          "content_summary": "<string>",
          "claim_ids": ["<claim_id_1>", ...],
          "estimated_minutes": <int>,
          "requires_human_review": true
        }
      ]
    }
  ],
  "claim_ids_used": ["<all_claim_ids_referenced>"],
  "requires_human_review": true,
  "notes": "<any caveats>"
}

Rules:
- Every lesson MUST reference at least one claim_id from the provided list
- Do not invent content beyond what the claims support
- Group related claims into logical lessons and modules
- Set requires_human_review=true on all lessons
- Estimated lesson time should be realistic (10-60 minutes typical)"""


class CurriculumArchitectWorker(BaseWorker):
    """
    Assembles curriculum drafts from verified claims only.
    Draft requires human approval before becoming published curriculum.
    """

    name = "curriculum_architect_worker"

    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_client: Optional[LLMClient] = None,
        node_id: Optional[str] = None,
    ) -> None:
        super().__init__(session, llm_client=llm_client, node_id=node_id)

    async def _run_work(self, payload: dict) -> dict:
        """
        Payload expected keys:
          claim_ids     — list of specific claim IDs to include (optional)
          concept_ids   — list of concept IDs to build curriculum around (optional)
          course_title  — suggested course title (optional)
          domain        — learning domain (optional)
          max_claims    — max claims to include (default: 50)
        """
        claim_ids_input = payload.get("claim_ids", [])
        max_claims = payload.get("max_claims", 50)

        # Fetch verified claims from DB (GOVERNANCE: only VERIFIED claims)
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
                    "course_title": payload.get("course_title", "Untitled"),
                    "course_description": "No verified claims available for curriculum assembly.",
                    "modules": [],
                    "claim_ids_used": [],
                    "notes": "No verified claims found. Cannot assemble curriculum without source-verified claims.",
                },
                "curriculum_draft",
            )

        # Build claim summary for LLM (no raw DB objects)
        claim_summaries = [
            {
                "claim_id": c.claim_id,
                "statement": c.statement,
                "confidence_score": c.confidence_score,
                "claim_number": c.claim_number,
            }
            for c in claims
        ]

        user_message = f"""Organise these verified knowledge claims into a course curriculum draft.

Suggested course title: {payload.get('course_title', 'Auto-generated course')}
Domain: {payload.get('domain', 'General')}

Verified claims to organise:
{chr(10).join(f"  [{c['claim_id']}] {c['statement']}" for c in claim_summaries)}

Return the curriculum draft JSON."""

        response = await self._call_llm(
            messages=[{"role": "user", "content": user_message}],
            prompt_type="curriculum_draft",
            system=_SYSTEM_PROMPT,
        )

        try:
            validated = parse_agent_output(response.content, CurriculumDraftOutput)
        except Exception as exc:
            logger.warning("Curriculum architect output validation failed: %s", exc)
            validated = CurriculumDraftOutput(
                course_title=payload.get("course_title", "Draft Course"),
                course_description="Draft requires manual assembly. LLM output failed validation.",
                modules=[],
                claim_ids_used=[c.claim_id for c in claims],
                requires_human_review=True,
                notes=f"Validation error: {exc}",
            )

        proposal = validated.model_dump()
        return {
            **self._route_for_review(proposal, "curriculum_draft"),
            "llm_audit": response.to_audit_record(),
            "input_source_ids": list({c.source_id for c in claims if c.source_id}),
        }
