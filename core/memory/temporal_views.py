"""
UAE v4 — Time-Travel Knowledge Views

Reconstructs the state of knowledge at any point in time using
the InstitutionalArchive and Claim revision history.

This enables:
  - "What did the doctrine say on 2024-01-01?"
  - "Which claims were VERIFIED when course X was published?"
  - "What was the state before the constitutional review?"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ClaimRevision, ClaimStatus, InstitutionalArchiveEntry,
    Source, SourceType,
)

logger = logging.getLogger(__name__)


@dataclass
class TemporalClaimState:
    """The reconstructed state of a claim at a specific point in time."""
    claim_id: str
    claim_number: Optional[str]
    statement: str
    status: str
    confidence_score: float
    source_id: str
    source_type: Optional[str]
    claim_classification: Optional[str]
    requires_constitutional_review: bool
    version: int
    as_of: datetime
    derived_from_revision: Optional[str] = None    # revision_id


@dataclass
class TemporalKnowledgeSnapshot:
    """A reconstructed knowledge snapshot at a given timestamp."""
    as_of: datetime
    node_id: Optional[str]
    total_claims: int
    verified_claims: List[TemporalClaimState] = field(default_factory=list)
    contested_claims: List[TemporalClaimState] = field(default_factory=list)
    doctrine_events: List[dict] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "node_id": self.node_id,
            "total_claims": self.total_claims,
            "verified_count": len(self.verified_claims),
            "contested_count": len(self.contested_claims),
            "doctrine_events_count": len(self.doctrine_events),
        }


class TemporalKnowledgeView:
    """
    Reconstructs knowledge state at arbitrary points in time.

    For each claim, the reconstruction uses ClaimRevision records to
    determine what the status was at the requested timestamp.

    Usage::

        view = TemporalKnowledgeView(session)
        snapshot = await view.snapshot_at(
            as_of=datetime(2024, 6, 1),
            node_id="node-a",
        )
        print(snapshot.summary)
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_claim_state_at(
        self,
        claim_id: str,
        as_of: datetime,
    ) -> Optional[TemporalClaimState]:
        """
        Reconstruct the state of a claim at a specific time.

        Works by finding the most recent ClaimRevision before `as_of`
        to determine what status the claim was in.

        Args:
            claim_id: The claim to reconstruct.
            as_of: Point in time to reconstruct.

        Returns:
            TemporalClaimState or None if claim didn't exist at that time.
        """
        # First get the base claim
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is None:
            return None

        # Claim must have been created by as_of
        if claim.created_at > as_of:
            return None

        # Find the most recent revision at or before as_of
        stmt = (
            select(ClaimRevision)
            .where(ClaimRevision.claim_id == claim_id)
            .where(ClaimRevision.timestamp <= as_of)
            .order_by(ClaimRevision.timestamp.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        revision = result.scalar_one_or_none()

        # Determine status at that point in time
        if revision:
            status_at = revision.updated_version
            revision_id = revision.revision_id
        else:
            # No revision yet — claim was in its initial state
            status_at = ClaimStatus.DRAFT.value
            revision_id = None

        # Get source type
        source_type = await self._get_source_type(claim.source_id)

        return TemporalClaimState(
            claim_id=claim.claim_id,
            claim_number=claim.claim_number,
            statement=claim.statement,
            status=status_at,
            confidence_score=claim.confidence_score,
            source_id=claim.source_id,
            source_type=source_type,
            claim_classification=(
                claim.claim_classification.value
                if claim.claim_classification else None
            ),
            requires_constitutional_review=claim.requires_constitutional_review,
            version=claim.version,
            as_of=as_of,
            derived_from_revision=revision_id,
        )

    async def snapshot_at(
        self,
        as_of: datetime,
        node_id: Optional[str] = None,
        include_doctrine_events: bool = True,
        limit: int = 500,
    ) -> TemporalKnowledgeSnapshot:
        """
        Reconstruct the full knowledge state at a given timestamp.

        Args:
            as_of: Point in time.
            node_id: Optionally filter to a specific academy node.
            include_doctrine_events: Whether to include archive events.
            limit: Maximum claims to reconstruct (for performance).

        Returns:
            TemporalKnowledgeSnapshot.
        """
        # Get all claims that existed at as_of
        stmt = select(Claim).where(Claim.created_at <= as_of)
        if node_id:
            stmt = stmt.where(Claim.origin_node_id == node_id)
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        claims = result.scalars().all()

        verified: List[TemporalClaimState] = []
        contested: List[TemporalClaimState] = []

        for claim in claims:
            state = await self.get_claim_state_at(claim.claim_id, as_of)
            if state is None:
                continue
            if state.status == ClaimStatus.VERIFIED.value:
                verified.append(state)
            elif state.status == ClaimStatus.CONTESTED.value:
                contested.append(state)

        # Doctrine events from archive up to as_of
        doctrine_events: List[dict] = []
        if include_doctrine_events:
            doctrine_events = await self._get_doctrine_events_until(as_of, node_id)

        return TemporalKnowledgeSnapshot(
            as_of=as_of,
            node_id=node_id,
            total_claims=len(claims),
            verified_claims=verified,
            contested_claims=contested,
            doctrine_events=doctrine_events,
        )

    async def get_doctrine_timeline(
        self,
        claim_id: str,
    ) -> List[dict]:
        """
        Return a chronological timeline of all doctrine-relevant events
        for a claim (from both ClaimRevision and InstitutionalArchive).
        """
        timeline: List[dict] = []

        # Revisions
        stmt = (
            select(ClaimRevision)
            .where(ClaimRevision.claim_id == claim_id)
            .order_by(ClaimRevision.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        for rev in result.scalars().all():
            timeline.append({
                "timestamp": rev.timestamp.isoformat(),
                "event_type": "status_revision",
                "from_status": rev.previous_version,
                "to_status": rev.updated_version,
                "changed_by": rev.changed_by,
                "reason": rev.change_reason,
            })

        # Archive events
        stmt = (
            select(InstitutionalArchiveEntry)
            .where(InstitutionalArchiveEntry.subject_id == claim_id)
            .order_by(InstitutionalArchiveEntry.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        for entry in result.scalars().all():
            timeline.append({
                "timestamp": entry.timestamp.isoformat(),
                "event_type": entry.event_type,
                "summary": entry.event_summary,
                "actor": entry.actor_id,
                "preceding_state": entry.preceding_state,
                "resulting_state": entry.resulting_state,
            })

        # Sort merged timeline by timestamp
        timeline.sort(key=lambda e: e["timestamp"])
        return timeline

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_source_type(self, source_id: str) -> Optional[str]:
        stmt = select(Source.source_type).where(Source.source_id == source_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def _get_doctrine_events_until(
        self,
        until: datetime,
        node_id: Optional[str],
    ) -> List[dict]:
        stmt = (
            select(InstitutionalArchiveEntry)
            .where(InstitutionalArchiveEntry.timestamp <= until)
            .where(InstitutionalArchiveEntry.event_type.in_([
                "constitutional_review_triggered",
                "governance_decision_recorded",
                "doctrine_conflict_detected",
                "source_reclassified",
            ]))
        )
        if node_id:
            stmt = stmt.where(InstitutionalArchiveEntry.node_id == node_id)
        stmt = stmt.order_by(InstitutionalArchiveEntry.timestamp.asc()).limit(200)
        result = await self.session.execute(stmt)

        events = []
        for entry in result.scalars().all():
            events.append({
                "entry_id": entry.entry_id,
                "timestamp": entry.timestamp.isoformat(),
                "event_type": entry.event_type,
                "subject_id": entry.subject_id,
                "subject_type": entry.subject_type,
                "summary": entry.event_summary,
                "actor": entry.actor_id,
            })
        return events
