"""
UAE v3 — Source Sentinel Worker

Validates incoming source documents:
  - Detects trust tier based on publisher and metadata
  - Flags sources that lack required metadata
  - Computes content address for deduplication
  - Proposes whether human review is required
  - Does NOT auto-approve sources

Governance boundary: The worker proposes trust_tier and validity.
A human reviewer (or admin) must confirm before the source is used
to extract claims.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_worker import BaseWorker
from agents.llm_client import LLMClient
from agents.structured_outputs import SourceValidationOutput, parse_agent_output
from core.storage.content_addressing import compute_cid

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a source validation specialist for an educational knowledge system.
Assess the provided source metadata and return a JSON object matching this schema:
{
  "source_id": "<string>",
  "is_valid": <bool>,
  "trust_tier": "TIER1" | "TIER2" | "TIER3",
  "validation_notes": "<string>",
  "detected_language": "<ISO-639-1>",
  "estimated_page_count": <int or null>,
  "requires_human_review": true
}

Trust tier guidelines:
  TIER1: Official primary technical documentation, government publications, peer-reviewed standards
  TIER2: Accredited training materials, publisher textbooks
  TIER3: Supplemental, community, or unverified sources

Always set requires_human_review=true. You propose; humans decide."""


class SourceSentinelWorker(BaseWorker):
    """
    Source validation worker.
    Proposes trust tier and validity for human confirmation.
    """

    name = "source_sentinel_worker"

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
          source_id   — internal source ID
          title       — document title
          publisher   — publisher name
          trust_tier  — current tier (may be overridden)
          file_path   — local path (optional)
          source_url  — URL (optional)
          metadata    — additional metadata dict (optional)
        """
        source_id = payload.get("source_id", "unknown")
        title = payload.get("title", "")
        publisher = payload.get("publisher", "")

        # Compute CID for deduplication if file_path is given
        content_cid = None
        file_path = payload.get("file_path")
        if file_path:
            try:
                from pathlib import Path
                content_cid = compute_cid(Path(file_path).read_bytes())
            except Exception as exc:
                logger.warning("Could not compute CID for %s: %s", file_path, exc)

        # Build LLM prompt
        user_message = f"""Validate this source document:

Source ID: {source_id}
Title: {title}
Publisher: {publisher}
Current Trust Tier: {payload.get('trust_tier', 'unknown')}
Source URL: {payload.get('source_url', 'N/A')}
Additional metadata: {payload.get('metadata', {})}

Assess and return the JSON validation result."""

        response = await self._call_llm(
            messages=[{"role": "user", "content": user_message}],
            prompt_type="source_validation",
            system=_SYSTEM_PROMPT,
        )

        # Parse and validate structured output
        try:
            validated = parse_agent_output(response.content, SourceValidationOutput)
        except Exception as exc:
            logger.warning("Source sentinel output validation failed: %s — using safe defaults", exc)
            validated = SourceValidationOutput(
                source_id=source_id,
                is_valid=False,
                trust_tier=payload.get("trust_tier", "TIER3"),
                validation_notes=f"LLM output validation failed: {exc}. Manual review required.",
                requires_human_review=True,
            )

        proposal = validated.model_dump()
        if content_cid:
            proposal["content_cid"] = content_cid

        return {
            **self._route_for_review(proposal, "source_validation"),
            "llm_audit": response.to_audit_record(),
        }
