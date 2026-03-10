"""
UAE v4 — Constitutional Conflict Detector

Identifies when a new claim conflicts with existing doctrine in ways that
require constitutional review. Works with the PrecedenceEngine to detect:

  1. Direct semantic conflicts (classification = conflicts_with)
  2. Precedence violations (lower source overriding higher)
  3. Immutable core challenges
  4. Cross-node doctrine contradictions during federation import
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ClaimClassification, ClaimStatus, Source, SourceType
)
from core.doctrine.precedence_engine import PrecedenceEngine, PrecedenceCheckResult

logger = logging.getLogger(__name__)


@dataclass
class DoctrineConflict:
    """Describes a single doctrine conflict detected for a claim."""
    conflict_id: str                          # generated identifier
    incoming_claim_id: str
    conflicting_claim_id: Optional[str]       # None for structural conflicts
    conflict_type: str                        # precedence_violation / semantic_conflict / immutable_core / cross_node
    severity: str                             # critical / major / minor
    description: str
    requires_constitutional_review: bool
    precedence_result: Optional[PrecedenceCheckResult] = None
    metadata: dict = field(default_factory=dict)


class ConflictDetector:
    """
    Detects doctrine conflicts for incoming claims.

    Usage::

        detector = ConflictDetector(session)
        conflicts = await detector.detect(
            claim_id="claim-uuid",
            incoming_source_type=SourceType.CURRICULUM,
            classification=ClaimClassification.CONFLICTS_WITH,
            statement="...",
        )
        if any(c.requires_constitutional_review for c in conflicts):
            # trigger constitutional review
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._engine = PrecedenceEngine()

    async def detect(
        self,
        claim_id: str,
        incoming_source_type: SourceType,
        classification: Optional[ClaimClassification],
        statement: str,
        incumbent_claim_ids: Optional[List[str]] = None,
    ) -> List[DoctrineConflict]:
        """
        Run all conflict detection checks for a claim.

        Args:
            claim_id: The claim being evaluated (must already exist in DB).
            incoming_source_type: Source type of the claim's source document.
            classification: Semantic classification of the claim.
            statement: The claim statement text.
            incumbent_claim_ids: Explicit list of claim IDs this claim interacts
                with. If None, the detector looks for semantically related claims.

        Returns:
            List of detected DoctrineConflict objects. Empty list = no conflicts.
        """
        conflicts: List[DoctrineConflict] = []
        conflict_counter = 0

        def _make_id() -> str:
            nonlocal conflict_counter
            conflict_counter += 1
            return f"conflict-{claim_id[:8]}-{conflict_counter:03d}"

        # 1. Check immutable core challenge
        if incoming_source_type != SourceType.IMMUTABLE_CORE and classification in (
            ClaimClassification.SUPERSEDES,
            ClaimClassification.CONFLICTS_WITH,
            ClaimClassification.DEPRECATED_BY,
        ):
            # Look for immutable core claims this might challenge
            immutable_claims = await self._fetch_claims_by_source_type(
                SourceType.IMMUTABLE_CORE
            )
            for ic in immutable_claims:
                result = self._engine.check(
                    incoming_source_type=incoming_source_type,
                    classification=classification,
                    incumbent_source_type=SourceType.IMMUTABLE_CORE,
                )
                if result.requires_constitutional_review:
                    conflicts.append(DoctrineConflict(
                        conflict_id=_make_id(),
                        incoming_claim_id=claim_id,
                        conflicting_claim_id=ic.claim_id,
                        conflict_type="immutable_core",
                        severity="critical",
                        description=(
                            f"Claim attempts to {classification.value} an immutable core claim. "
                            f"This requires governance council approval."
                        ),
                        requires_constitutional_review=True,
                        precedence_result=result,
                    ))

        # 2. Check explicit incumbent claims
        incumbents_to_check = incumbent_claim_ids or []
        for incumbent_id in incumbents_to_check:
            incumbent_source_type = await self._get_claim_source_type(incumbent_id)
            if incumbent_source_type is None:
                continue
            result = self._engine.check(
                incoming_source_type=incoming_source_type,
                classification=classification,
                incumbent_source_type=incumbent_source_type,
            )
            if result.requires_constitutional_review:
                severity = "critical" if incumbent_source_type in (
                    SourceType.IMMUTABLE_CORE, SourceType.CONSTITUTIONAL_DOCTRINE
                ) else "major"
                conflicts.append(DoctrineConflict(
                    conflict_id=_make_id(),
                    incoming_claim_id=claim_id,
                    conflicting_claim_id=incumbent_id,
                    conflict_type="precedence_violation",
                    severity=severity,
                    description=result.reason,
                    requires_constitutional_review=True,
                    precedence_result=result,
                ))

        # 3. Direct conflicts_with classification always triggers review
        if classification == ClaimClassification.CONFLICTS_WITH and not conflicts:
            result = self._engine.check(
                incoming_source_type=incoming_source_type,
                classification=classification,
            )
            conflicts.append(DoctrineConflict(
                conflict_id=_make_id(),
                incoming_claim_id=claim_id,
                conflicting_claim_id=None,
                conflict_type="semantic_conflict",
                severity="major",
                description=(
                    "Claim classified as conflicts_with existing doctrine. "
                    "Constitutional review is mandatory for all conflict claims."
                ),
                requires_constitutional_review=True,
                precedence_result=result,
            ))

        logger.info(
            "Conflict detection for claim %s: %d conflict(s) found, "
            "%d requiring constitutional review",
            claim_id,
            len(conflicts),
            sum(1 for c in conflicts if c.requires_constitutional_review),
        )
        return conflicts

    async def check_federation_import(
        self,
        incoming_claim_id: str,
        incoming_source_type: SourceType,
        classification: Optional[ClaimClassification],
        origin_node_id: str,
        local_node_id: str,
    ) -> List[DoctrineConflict]:
        """
        Run conflict detection for a federation import.

        Cross-node imports receive an additional cross_node check: if the
        importing node's doctrine hierarchy is more restrictive, a minor
        conflict is flagged for human awareness.
        """
        conflicts = await self.detect(
            claim_id=incoming_claim_id,
            incoming_source_type=incoming_source_type,
            classification=classification,
            statement="",  # statement not needed for cross-node check
        )

        # Additional cross-node annotation
        if classification in (
            ClaimClassification.SUPERSEDES,
            ClaimClassification.CONFLICTS_WITH,
        ):
            conflicts.append(DoctrineConflict(
                conflict_id=f"xnode-{incoming_claim_id[:8]}",
                incoming_claim_id=incoming_claim_id,
                conflicting_claim_id=None,
                conflict_type="cross_node",
                severity="minor",
                description=(
                    f"Federation import from node {origin_node_id!r} carries "
                    f"doctrine-altering classification {classification.value!r}. "
                    f"Local node {local_node_id!r} precedence rules apply."
                ),
                requires_constitutional_review=True,
                metadata={"origin_node_id": origin_node_id, "local_node_id": local_node_id},
            ))

        return conflicts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_claims_by_source_type(self, source_type: SourceType) -> List[Claim]:
        stmt = (
            select(Claim)
            .join(Source, Claim.source_id == Source.source_id)
            .where(Source.source_type == source_type)
            .where(Claim.status == ClaimStatus.VERIFIED)
            .limit(50)  # safety cap — we only need to know if any exist
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _get_claim_source_type(self, claim_id: str) -> Optional[SourceType]:
        stmt = (
            select(Source.source_type)
            .join(Claim, Claim.source_id == Source.source_id)
            .where(Claim.claim_id == claim_id)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        return row
