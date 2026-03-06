"""
Source Sentinel Agent

Responsibilities:
  1. Accept document uploads (path or raw bytes)
  2. Extract text from documents
  3. Register sources in the Source Registry with appropriate trust tier
  4. Classify trust tier based on publisher / metadata heuristics
  5. Return source records and extracted text metadata

Outputs:
  source_records, extracted_text_metadata, metadata
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from core.ingestion.source_registry import SourceRegistry
from core.ingestion.text_extractor import TextExtractor
from database.schemas.models import TrustTier

logger = logging.getLogger(__name__)

# Publisher → trust tier heuristics
_TIER1_PUBLISHERS = {
    "oem", "manufacturer", "nhtsa", "fmcsa", "dot", "sae international",
    "ansi", "iso", "nfpa", "nec", "ieee",
}
_TIER2_PUBLISHERS = {
    "ase", "natef", "atd", "nccer", "comptia", "pmbok", "accredited",
}


class SourceSentinelAgent(BaseAgent):
    """
    Ingests source documents and registers them in the knowledge pipeline.
    """

    name = "source_sentinel"

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.registry = SourceRegistry(session)
        self.extractor = TextExtractor(session)

    async def _run(self, payload: dict) -> dict:
        """
        Payload keys:
          title (str): Document title
          publisher (str): Publisher name
          file_path (str, optional): Path to file on disk
          content (bytes, optional): Raw document bytes
          fmt (str, optional): File format when using content — "pdf", "txt", "docx"
          edition (str, optional)
          publication_date (str, optional): ISO date string
          license (str, optional)
          source_url (str, optional)
          trust_tier (str, optional): Override auto-classification
        """
        title = payload.get("title", "Untitled Document")
        publisher = payload.get("publisher", "Unknown")
        file_path = payload.get("file_path")
        content = payload.get("content")
        fmt = payload.get("fmt", "txt")

        # Auto-classify trust tier
        trust_tier = self._classify_tier(
            publisher=publisher,
            override=payload.get("trust_tier"),
        )

        # Parse publication_date
        pub_date = None
        if payload.get("publication_date"):
            from datetime import datetime
            try:
                pub_date = datetime.fromisoformat(payload["publication_date"])
            except ValueError:
                pass

        # Register source
        source = await self.registry.register_source(
            title=title,
            publisher=publisher,
            trust_tier=trust_tier,
            content=content,
            file_path=file_path,
            edition=payload.get("edition"),
            publication_date=pub_date,
            license=payload.get("license"),
            source_url=payload.get("source_url"),
            metadata=payload.get("metadata", {}),
        )

        # Extract text
        extracted = []
        if file_path:
            extracted = await self.extractor.extract_from_file(source, file_path)
        elif content:
            extracted = await self.extractor.extract_from_bytes(source, content, fmt)

        return {
            "source_id": source.source_id,
            "title": source.title,
            "publisher": source.publisher,
            "trust_tier": source.trust_tier.value,
            "document_hash": source.document_hash,
            "text_blocks_extracted": len(extracted),
            "ingest_timestamp": source.ingest_timestamp.isoformat(),
        }

    # ------------------------------------------------------------------
    # Trust tier classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_tier(publisher: str, override: str | None) -> TrustTier:
        if override:
            try:
                return TrustTier(override)
            except ValueError:
                pass

        publisher_lower = publisher.lower()

        for keyword in _TIER1_PUBLISHERS:
            if keyword in publisher_lower:
                return TrustTier.TIER1

        for keyword in _TIER2_PUBLISHERS:
            if keyword in publisher_lower:
                return TrustTier.TIER2

        return TrustTier.TIER3
