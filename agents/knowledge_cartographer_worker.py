"""
UAE v3 — Knowledge Cartographer Worker

Extracts proposed claims from source text passages.

Governance boundary:
  - Worker proposes claims; DOES NOT set status=VERIFIED
  - All proposals require human review before entering the ledger as verified
  - Confidence scores are LLM-estimated and must not be accepted uncritically
  - Each proposed claim must reference a source_id for provenance

Output routes to: governance manager → human review → claim ledger
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_worker import BaseWorker
from agents.llm_client import LLMClient
from agents.structured_outputs import KnowledgeExtractionOutput, parse_agent_output

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a knowledge extraction specialist for an educational content system.
Your task is to extract atomic, verifiable knowledge claims from the provided source text.

Return a JSON object matching this schema:
{
  "source_id": "<string>",
  "proposed_claims": [
    {
      "statement": "<concise, specific factual claim>",
      "source_id": "<string>",
      "confidence_score": <0.0-1.0>,
      "concept_name": "<concept name or null>",
      "page_range": "<e.g. 'p.42-43' or null>",
      "supporting_quote": "<exact relevant quote or null>",
      "requires_human_review": true
    }
  ],
  "proposed_concepts": ["<concept1>", "<concept2>"],
  "extraction_notes": "<any caveats or ambiguities>",
  "requires_human_review": true
}

Rules:
- Each claim must be atomic (one specific fact)
- Do not generalise or synthesise beyond what the source explicitly states
- Confidence score reflects how clearly the source supports this specific claim
- Always set requires_human_review=true
- Do not invent claims not supported by the text"""


class KnowledgeCartographerWorker(BaseWorker):
    """
    Extracts proposed knowledge claims from source text.
    All proposals require human review before becoming verified claims.
    """

    name = "knowledge_cartographer_worker"

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
          source_id     — source being extracted from
          text_content  — text passage to analyse
          concept_hints — optional list of concept names to look for
          max_claims    — max claims to propose (default: 10)
        """
        source_id = payload.get("source_id", "unknown")
        text = payload.get("text_content", "")
        concept_hints = payload.get("concept_hints", [])
        max_claims = payload.get("max_claims", 10)

        if not text:
            return self._route_for_review(
                {"source_id": source_id, "proposed_claims": [], "extraction_notes": "No text provided."},
                "knowledge_extraction",
            )

        hints_str = f"\nFocus on these concepts if present: {', '.join(concept_hints)}" if concept_hints else ""
        user_message = f"""Extract knowledge claims from this source text.
Source ID: {source_id}
Maximum claims to propose: {max_claims}{hints_str}

--- SOURCE TEXT ---
{text[:8000]}
--- END TEXT ---

Return the JSON extraction result."""

        response = await self._call_llm(
            messages=[{"role": "user", "content": user_message}],
            prompt_type="knowledge_extraction",
            system=_SYSTEM_PROMPT,
        )

        try:
            validated = parse_agent_output(response.content, KnowledgeExtractionOutput)
        except Exception as exc:
            logger.warning("Cartographer output validation failed: %s", exc)
            validated = KnowledgeExtractionOutput(
                source_id=source_id,
                proposed_claims=[],
                extraction_notes=f"Output validation failed: {exc}. No claims proposed.",
                requires_human_review=True,
            )

        proposal = validated.model_dump()
        return {
            **self._route_for_review(proposal, "knowledge_extraction"),
            "llm_audit": response.to_audit_record(),
            "input_source_ids": [source_id],
        }
