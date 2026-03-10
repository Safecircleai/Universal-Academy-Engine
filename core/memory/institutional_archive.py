"""
UAE v4 — Institutional Memory Archive

Records all knowledge evolution events in an append-only archive.
No archive entries are ever deleted or modified by the application.

Event types (non-exhaustive):
  claim_status_transition         — any claim status change
  constitutional_review_triggered — claim routed to constitutional review
  governance_decision_recorded    — council decision stored
  source_reclassified             — source type changed
  doctrine_conflict_detected      — conflict detected during import/verify
  federation_import_doctrine      — doctrine-bearing claim imported from peer
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import InstitutionalArchiveEntry

logger = logging.getLogger(__name__)


class ArchiveError(Exception):
    """Raised when an archive operation fails."""


class InstitutionalArchive:
    """
    Write-once archive for knowledge evolution events.

    All writes go through ``record()``. There is no update or delete.
    The archive provides query methods for audit and temporal analysis.

    Usage::

        archive = InstitutionalArchive(session)
        entry = await archive.record(
            event_type="claim_status_transition",
            subject_id=claim_id,
            subject_type="claim",
            event_summary="Claim CLM000001 transitioned draft→constitutional_review_required",
            preceding_state={"status": "draft"},
            resulting_state={"status": "constitutional_review_required"},
            actor_id="reviewer@node",
        )
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        event_type: str,
        subject_id: str,
        subject_type: str,
        event_summary: str,
        *,
        node_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        evidence_payload: Optional[Dict[str, Any]] = None,
        preceding_state: Optional[Dict[str, Any]] = None,
        resulting_state: Optional[Dict[str, Any]] = None,
    ) -> InstitutionalArchiveEntry:
        """
        Record a knowledge evolution event.

        Args:
            event_type: Category identifier for the event.
            subject_id: Primary key of the entity being described.
            subject_type: Entity class (claim / source / course / node).
            event_summary: Human-readable narrative of the event.
            node_id: Academy node this event occurred on.
            actor_id: User or agent that triggered the event.
            evidence_payload: Supporting data (dicts, lists, etc.).
            preceding_state: Snapshot of entity state before the event.
            resulting_state: Snapshot of entity state after the event.

        Returns:
            Persisted InstitutionalArchiveEntry.
        """
        if not event_type or not event_type.strip():
            raise ArchiveError("event_type is required.")
        if not subject_id or not subject_id.strip():
            raise ArchiveError("subject_id is required.")
        if not event_summary or not event_summary.strip():
            raise ArchiveError("event_summary is required.")

        content_hash = self._hash_entry(
            event_type, subject_id, event_summary,
            preceding_state, resulting_state,
        )

        entry = InstitutionalArchiveEntry(
            event_type=event_type.strip(),
            subject_id=subject_id.strip(),
            subject_type=subject_type.strip(),
            node_id=node_id,
            actor_id=actor_id,
            event_summary=event_summary.strip(),
            evidence_payload=evidence_payload,
            preceding_state=preceding_state,
            resulting_state=resulting_state,
            content_hash=content_hash,
        )
        self.session.add(entry)
        await self.session.flush()

        logger.info(
            "Archive: %s on %s/%s by %s (entry %s)",
            event_type, subject_type, subject_id, actor_id or "system", entry.entry_id,
        )
        return entry

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_history(
        self,
        subject_id: str,
        subject_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[InstitutionalArchiveEntry]:
        """Return all archive entries for a subject, chronological order."""
        stmt = (
            select(InstitutionalArchiveEntry)
            .where(InstitutionalArchiveEntry.subject_id == subject_id)
        )
        if subject_type:
            stmt = stmt.where(InstitutionalArchiveEntry.subject_type == subject_type)
        stmt = stmt.order_by(InstitutionalArchiveEntry.timestamp.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_event_type(
        self,
        event_type: str,
        node_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[InstitutionalArchiveEntry]:
        """Return archive entries by event type with optional filters."""
        stmt = (
            select(InstitutionalArchiveEntry)
            .where(InstitutionalArchiveEntry.event_type == event_type)
        )
        if node_id:
            stmt = stmt.where(InstitutionalArchiveEntry.node_id == node_id)
        if since:
            stmt = stmt.where(InstitutionalArchiveEntry.timestamp >= since)
        stmt = stmt.order_by(InstitutionalArchiveEntry.timestamp.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_constitutional_review_trail(
        self,
        claim_id: str,
    ) -> List[InstitutionalArchiveEntry]:
        """Return the full constitutional review trail for a claim."""
        stmt = (
            select(InstitutionalArchiveEntry)
            .where(InstitutionalArchiveEntry.subject_id == claim_id)
            .where(InstitutionalArchiveEntry.event_type.in_([
                "constitutional_review_triggered",
                "governance_decision_recorded",
                "claim_status_transition",
                "doctrine_conflict_detected",
            ]))
            .order_by(InstitutionalArchiveEntry.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def verify_entry_integrity(self, entry_id: str) -> bool:
        """
        Verify the content hash of a stored archive entry.

        Returns True if the entry's content_hash matches the expected value
        based on its stored fields. Returns False if the entry has been tampered.
        """
        stmt = select(InstitutionalArchiveEntry).where(
            InstitutionalArchiveEntry.entry_id == entry_id
        )
        result = await self.session.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry is None:
            return False

        expected = self._hash_entry(
            entry.event_type,
            entry.subject_id,
            entry.event_summary,
            entry.preceding_state,
            entry.resulting_state,
        )
        return entry.content_hash == expected

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_entry(
        event_type: str,
        subject_id: str,
        event_summary: str,
        preceding_state: Optional[dict],
        resulting_state: Optional[dict],
    ) -> str:
        payload = json.dumps(
            {
                "event_type": event_type,
                "subject_id": subject_id,
                "event_summary": event_summary,
                "preceding_state": preceding_state,
                "resulting_state": resulting_state,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
