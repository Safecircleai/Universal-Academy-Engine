"""
Universal Academy Engine — Source Registry Module

Manages all trusted knowledge sources: registration, validation, retrieval,
and listing.  Every piece of knowledge in the UAE must trace to a source
registered here.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import Source, TrustTier

logger = logging.getLogger(__name__)


class SourceRegistrationError(Exception):
    """Raised when a source cannot be registered."""


class SourceRegistry:
    """
    Manages the lifecycle of trusted source documents.

    All writes to the knowledge pipeline start here.  A document that has not
    been registered through this module cannot supply claims.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_source(
        self,
        *,
        title: str,
        publisher: str,
        trust_tier: TrustTier,
        content: bytes | None = None,
        file_path: str | None = None,
        edition: str | None = None,
        publication_date: datetime | None = None,
        license: str | None = None,
        source_url: str | None = None,
        language: str = "en",
        metadata: dict | None = None,
    ) -> Source:
        """
        Register a new trusted source document.

        Either ``content`` (raw bytes) or ``file_path`` must be supplied so
        the document hash can be computed.

        Returns the persisted :class:`Source` record.
        Raises :class:`SourceRegistrationError` if the document is already
        registered or if required fields are missing.
        """
        if content is None and file_path is None:
            raise SourceRegistrationError(
                "Either 'content' or 'file_path' must be provided to register a source."
            )

        raw_bytes = content or Path(file_path).read_bytes()
        doc_hash = self._compute_hash(raw_bytes)

        # Idempotency: detect duplicate by hash
        existing = await self._find_by_hash(doc_hash)
        if existing:
            logger.info("Source already registered: %s (hash=%s)", existing.source_id, doc_hash)
            return existing

        source = Source(
            title=title,
            publisher=publisher,
            trust_tier=trust_tier,
            document_hash=doc_hash,
            edition=edition,
            publication_date=publication_date,
            license=license,
            source_url=source_url,
            file_path=file_path,
            language=language,
            metadata_=metadata or {},
        )
        self.session.add(source)
        await self.session.flush()
        logger.info("Registered source %s: %r (tier=%s)", source.source_id, title, trust_tier)
        return source

    async def validate_source(self, source_id: str) -> dict:
        """
        Validate a registered source and return a validation report.

        Checks:
        - Record exists and is active
        - Hash is non-empty
        - Trust tier is set
        - Publisher and title are non-empty
        """
        source = await self._get_or_raise(source_id)
        issues: list[str] = []

        if not source.is_active:
            issues.append("Source is marked inactive.")
        if not source.document_hash:
            issues.append("Document hash is missing.")
        if not source.publisher.strip():
            issues.append("Publisher is empty.")
        if not source.title.strip():
            issues.append("Title is empty.")
        if source.trust_tier not in list(TrustTier):
            issues.append(f"Unrecognised trust tier: {source.trust_tier!r}.")

        return {
            "source_id": source_id,
            "valid": len(issues) == 0,
            "issues": issues,
        }

    async def retrieve_source(self, source_id: str) -> Source:
        """Return a :class:`Source` by its primary key."""
        return await self._get_or_raise(source_id)

    async def list_sources(
        self,
        *,
        trust_tier: TrustTier | None = None,
        publisher: str | None = None,
        is_active: bool | None = True,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Source]:
        """Return a filtered, paginated list of sources."""
        stmt = select(Source)
        if trust_tier is not None:
            stmt = stmt.where(Source.trust_tier == trust_tier)
        if publisher is not None:
            stmt = stmt.where(Source.publisher.ilike(f"%{publisher}%"))
        if is_active is not None:
            stmt = stmt.where(Source.is_active == is_active)
        stmt = stmt.order_by(Source.ingest_timestamp.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate_source(self, source_id: str) -> Source:
        """Mark a source as inactive (soft delete)."""
        source = await self._get_or_raise(source_id)
        stmt = (
            update(Source)
            .where(Source.source_id == source_id)
            .values(is_active=False)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        source.is_active = False
        logger.info("Deactivated source %s", source_id)
        return source

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def _find_by_hash(self, doc_hash: str) -> Optional[Source]:
        stmt = select(Source).where(Source.document_hash == doc_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_or_raise(self, source_id: str) -> Source:
        stmt = select(Source).where(Source.source_id == source_id)
        result = await self.session.execute(stmt)
        source = result.scalar_one_or_none()
        if source is None:
            raise SourceRegistrationError(f"Source not found: {source_id!r}")
        return source
