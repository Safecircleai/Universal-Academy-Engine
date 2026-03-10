"""
Universal Academy Engine — Claim Ledger Module

The Claim Ledger stores every atomic knowledge statement extracted from
verified sources.  Each claim is the indivisible unit of knowledge in the UAE
pipeline.

Governance invariant:
  A claim MUST be in ``verified`` status before it can be referenced by any
  lesson.  Lessons that attempt to reference draft or deprecated claims are
  rejected at write time.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ClaimRevision, ClaimStatus, Source, Concept
)

logger = logging.getLogger(__name__)


class ClaimLedgerError(Exception):
    """Raised when a claim operation violates governance rules."""


class ClaimLedger:
    """
    CRUD + governance operations for the claim ledger.

    All knowledge statements that enter the UAE knowledge pipeline pass
    through this class.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_claim(
        self,
        *,
        statement: str,
        source_id: str,
        concept_id: str | None = None,
        citation_location: str | None = None,
        confidence_score: float = 0.5,
        tags: list[str] | None = None,
    ) -> Claim:
        """
        Create a new claim in ``draft`` status.

        Args:
            statement: The human-readable knowledge statement.
            source_id: Primary key of the registered :class:`Source`.
            concept_id: Optional concept this claim belongs to.
            citation_location: Human-readable location, e.g. "p.42 §3.2".
            confidence_score: AI-assigned confidence in [0, 1].
            tags: Free-form keyword tags.

        Returns:
            The persisted :class:`Claim` record.
        """
        if not statement.strip():
            raise ClaimLedgerError("Claim statement cannot be empty.")

        # Verify the source exists
        await self._assert_source_exists(source_id)

        claim_number = await self._next_claim_number()
        claim = Claim(
            statement=statement.strip(),
            source_id=source_id,
            concept_id=concept_id,
            citation_location=citation_location,
            confidence_score=max(0.0, min(1.0, confidence_score)),
            status=ClaimStatus.DRAFT,
            tags=tags or [],
            claim_number=claim_number,
            version=1,
        )
        self.session.add(claim)
        await self.session.flush()
        logger.info("Created claim %s (%s) from source %s", claim.claim_number, claim.claim_id, source_id)
        return claim

    async def verify_claim(
        self,
        claim_id: str,
        *,
        reviewer: str = "system",
        notes: str | None = None,
    ) -> Claim:
        """
        Promote a claim from ``draft`` → ``verified``.

        Only ``draft`` claims may be verified.  A ``ClaimLedgerError`` is
        raised if the claim is in any other state.
        """
        claim = await self._get_or_raise(claim_id)
        if claim.status != ClaimStatus.DRAFT:
            raise ClaimLedgerError(
                f"Claim {claim_id!r} is in status {claim.status!r}; "
                f"only 'draft' claims can be verified."
            )

        await self._record_revision(
            claim,
            previous=claim.status.value,
            updated=ClaimStatus.VERIFIED.value,
            reason=f"Verified by {reviewer}. {notes or ''}".strip(),
            changed_by=reviewer,
        )
        claim.status = ClaimStatus.VERIFIED
        claim.version += 1
        await self.session.flush()
        logger.info("Verified claim %s by %s", claim.claim_number, reviewer)
        return claim

    async def update_claim_status(
        self,
        claim_id: str,
        new_status: ClaimStatus,
        *,
        reason: str = "",
        changed_by: str = "system",
    ) -> Claim:
        """
        Transition a claim to any valid status with a recorded reason.

        Allowed transitions:
        - draft       → verified | contested | deprecated
        - verified    → contested | deprecated
        - contested   → verified | deprecated
        - deprecated  → (no further transitions)
        """
        claim = await self._get_or_raise(claim_id)
        _assert_transition_valid(claim.status, new_status)

        await self._record_revision(
            claim,
            previous=claim.status.value,
            updated=new_status.value,
            reason=reason,
            changed_by=changed_by,
        )
        claim.status = new_status
        claim.version += 1
        await self.session.flush()
        logger.info(
            "Claim %s transitioned %s→%s by %s",
            claim.claim_number, claim.status, new_status, changed_by,
        )
        return claim

    async def retrieve_claim(self, claim_id: str) -> Claim:
        """Return a :class:`Claim` by its primary key."""
        return await self._get_or_raise(claim_id)

    async def list_claims(
        self,
        *,
        source_id: str | None = None,
        concept_id: str | None = None,
        status: ClaimStatus | None = None,
        min_confidence: float | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Claim]:
        """Filtered, paginated claim listing."""
        stmt = select(Claim)
        if source_id:
            stmt = stmt.where(Claim.source_id == source_id)
        if concept_id:
            stmt = stmt.where(Claim.concept_id == concept_id)
        if status:
            stmt = stmt.where(Claim.status == status)
        if min_confidence is not None:
            stmt = stmt.where(Claim.confidence_score >= min_confidence)
        stmt = stmt.order_by(Claim.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_claim_history(self, claim_id: str) -> List[ClaimRevision]:
        """Return all revision records for a claim in chronological order."""
        stmt = (
            select(ClaimRevision)
            .where(ClaimRevision.claim_id == claim_id)
            .order_by(ClaimRevision.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _assert_source_exists(self, source_id: str) -> None:
        stmt = select(Source.source_id).where(Source.source_id == source_id)
        result = await self.session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ClaimLedgerError(f"Source not found: {source_id!r}")

    async def _get_or_raise(self, claim_id: str) -> Claim:
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is None:
            raise ClaimLedgerError(f"Claim not found: {claim_id!r}")
        return claim

    async def _next_claim_number(self) -> str:
        stmt = select(func.count(Claim.claim_id))
        result = await self.session.execute(stmt)
        count = (result.scalar_one() or 0) + 1
        return f"CLM{count:06d}"

    async def _record_revision(
        self,
        claim: Claim,
        previous: str,
        updated: str,
        reason: str,
        changed_by: str,
    ) -> None:
        revision = ClaimRevision(
            claim_id=claim.claim_id,
            previous_version=previous,
            updated_version=updated,
            change_reason=reason,
            changed_by=changed_by,
        )
        self.session.add(revision)


# ---------------------------------------------------------------------------
# Transition validation
# ---------------------------------------------------------------------------

_ALLOWED_TRANSITIONS: dict[ClaimStatus, set[ClaimStatus]] = {
    ClaimStatus.DRAFT: {
        ClaimStatus.VERIFIED,
        ClaimStatus.CONTESTED,
        ClaimStatus.DEPRECATED,
        ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
    },
    ClaimStatus.VERIFIED: {
        ClaimStatus.CONTESTED,
        ClaimStatus.DEPRECATED,
        ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
    },
    ClaimStatus.CONTESTED: {
        ClaimStatus.VERIFIED,
        ClaimStatus.DEPRECATED,
        ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED,
    },
    ClaimStatus.CONSTITUTIONAL_REVIEW_REQUIRED: {
        ClaimStatus.CONSTITUTIONAL_REVIEW_IN_PROGRESS,
        ClaimStatus.DEPRECATED,
    },
    ClaimStatus.CONSTITUTIONAL_REVIEW_IN_PROGRESS: {
        ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED,
        ClaimStatus.DEPRECATED,
    },
    ClaimStatus.CONSTITUTIONAL_DECISION_RECORDED: {
        ClaimStatus.VERIFIED,
        ClaimStatus.DEPRECATED,
    },
    ClaimStatus.DEPRECATED: set(),
}


def _assert_transition_valid(current: ClaimStatus, new: ClaimStatus) -> None:
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise ClaimLedgerError(
            f"Invalid status transition: {current!r} → {new!r}. "
            f"Allowed: {[s.value for s in allowed]}"
        )
