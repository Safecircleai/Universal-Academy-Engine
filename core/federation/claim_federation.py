"""
Universal Academy Engine — Claim Federation Protocol (Part 1)

Implements the four core operations of claim federation:

  publish_claim()   — A node shares a local claim with the federation
  import_claim()    — A node adopts a claim from another node
  contest_claim()   — A node disputes a claim from another node
  adopt_claim()     — A contested claim is accepted after resolution

Federation governance invariants:
  - A node may only publish claims it originated.
  - Importing requires the source node to have published the claim.
  - Contested claims are allowed to coexist — they are distinguished
    by their ClaimCategory and carry full node provenance.
  - All federation events are logged in FederatedClaimRecord.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    AcademyNode, Claim, ClaimCategory, ClaimStatus,
    FederatedClaimRecord, NodeGovernancePolicy
)

logger = logging.getLogger(__name__)


class FederationError(Exception):
    """Raised when a federation operation violates protocol rules."""


class ClaimFederationProtocol:
    """
    Implements the UAE claim federation protocol.

    Each operation produces an immutable FederatedClaimRecord entry so
    the full provenance of every cross-node claim movement is preserved.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Core federation operations
    # ------------------------------------------------------------------

    async def publish_claim(
        self,
        claim_id: str,
        publishing_node_id: str,
        *,
        notes: str | None = None,
    ) -> FederatedClaimRecord:
        """
        Publish a local claim to the federation, making it available
        for other nodes to import.

        Rules:
          - Claim must be ``verified``.
          - Claim must originate in the publishing node.
          - Node policy must allow claim publication.
        """
        claim = await self._get_claim(claim_id)
        await self._assert_node_allows_publication(publishing_node_id)

        if claim.status != ClaimStatus.VERIFIED:
            raise FederationError(
                f"Only verified claims may be published. "
                f"Claim {claim.claim_number!r} is {claim.status.value!r}."
            )
        if claim.origin_node_id and claim.origin_node_id != publishing_node_id:
            raise FederationError(
                f"Node {publishing_node_id!r} cannot publish a claim that "
                f"originated in node {claim.origin_node_id!r}."
            )

        claim.claim_category = ClaimCategory.SHARED
        claim.publishing_node_id = publishing_node_id
        claim.claim_hash = _hash_claim(claim.statement)
        await self.session.flush()

        record = FederatedClaimRecord(
            claim_id=claim_id,
            action="publish",
            source_node_id=publishing_node_id,
            notes=notes,
            payload=_claim_snapshot(claim),
        )
        self.session.add(record)
        await self.session.flush()
        logger.info("Claim %s published to federation by node %s", claim.claim_number, publishing_node_id)
        return record

    async def import_claim(
        self,
        claim_id: str,
        importing_node_id: str,
        *,
        notes: str | None = None,
    ) -> tuple[Claim, FederatedClaimRecord]:
        """
        Import a federation-shared claim into the importing node's ledger.

        The original claim is NOT duplicated.  Instead the claim's category
        is updated to ``imported_claim`` in the importing node context, and
        a FederatedClaimRecord is created for audit.

        For true multi-node deployments, this would create a local copy.
        In the single-database model, we tag the claim and log the import.
        """
        claim = await self._get_claim(claim_id)
        await self._assert_node_allows_import(importing_node_id)

        if claim.claim_category not in (ClaimCategory.SHARED, ClaimCategory.IMPORTED):
            raise FederationError(
                f"Claim {claim.claim_number!r} is not published to the federation "
                f"(category={claim.claim_category.value!r}). Publish it first."
            )
        if claim.origin_node_id == importing_node_id:
            raise FederationError(
                f"Node {importing_node_id!r} already owns this claim — import is not needed."
            )

        record = FederatedClaimRecord(
            claim_id=claim_id,
            action="import",
            source_node_id=claim.publishing_node_id or claim.origin_node_id or importing_node_id,
            target_node_id=importing_node_id,
            notes=notes,
            payload=_claim_snapshot(claim),
        )
        self.session.add(record)
        await self.session.flush()
        logger.info(
            "Claim %s imported by node %s", claim.claim_number, importing_node_id
        )
        return claim, record

    async def contest_claim(
        self,
        claim_id: str,
        contesting_node_id: str,
        *,
        reason: str,
        notes: str | None = None,
    ) -> FederatedClaimRecord:
        """
        A node disputes a federated claim.

        The claim category is set to ``contested_claim``.  Both the original
        and the contesting node's position coexist — they are not deleted.
        A FederatedClaimRecord documents the dispute.

        The conflict must be resolved through the Verification Engine's
        human review workflow.
        """
        claim = await self._get_claim(claim_id)

        if claim.claim_category not in (ClaimCategory.SHARED, ClaimCategory.IMPORTED):
            raise FederationError(
                f"Only shared or imported claims may be contested. "
                f"Claim {claim.claim_number!r} is {claim.claim_category.value!r}."
            )

        claim.claim_category = ClaimCategory.CONTESTED
        await self.session.flush()

        record = FederatedClaimRecord(
            claim_id=claim_id,
            action="contest",
            source_node_id=contesting_node_id,
            notes=f"REASON: {reason}. {notes or ''}".strip(),
            payload={**_claim_snapshot(claim), "contest_reason": reason},
        )
        self.session.add(record)
        await self.session.flush()
        logger.info(
            "Claim %s contested by node %s: %s", claim.claim_number, contesting_node_id, reason
        )
        return record

    async def adopt_claim(
        self,
        claim_id: str,
        adopting_node_id: str,
        *,
        resolution_notes: str | None = None,
    ) -> FederatedClaimRecord:
        """
        A contesting node accepts the claim after dispute resolution.

        The claim's category reverts to ``imported_claim`` in the adopting
        node's context, and the dispute is formally closed.
        """
        claim = await self._get_claim(claim_id)

        if claim.claim_category != ClaimCategory.CONTESTED:
            raise FederationError(
                f"Only contested claims may be adopted. "
                f"Claim {claim.claim_number!r} is {claim.claim_category.value!r}."
            )

        claim.claim_category = ClaimCategory.IMPORTED
        await self.session.flush()

        record = FederatedClaimRecord(
            claim_id=claim_id,
            action="adopt",
            source_node_id=adopting_node_id,
            notes=resolution_notes,
            payload=_claim_snapshot(claim),
        )
        self.session.add(record)
        await self.session.flush()
        logger.info("Claim %s adopted by node %s", claim.claim_number, adopting_node_id)
        return record

    # ------------------------------------------------------------------
    # Federation query helpers
    # ------------------------------------------------------------------

    async def list_federation_events(
        self,
        *,
        claim_id: str | None = None,
        node_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> List[FederatedClaimRecord]:
        stmt = select(FederatedClaimRecord)
        if claim_id:
            stmt = stmt.where(FederatedClaimRecord.claim_id == claim_id)
        if node_id:
            stmt = stmt.where(
                (FederatedClaimRecord.source_node_id == node_id) |
                (FederatedClaimRecord.target_node_id == node_id)
            )
        if action:
            stmt = stmt.where(FederatedClaimRecord.action == action)
        stmt = stmt.order_by(FederatedClaimRecord.timestamp.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_published_claims(self, limit: int = 200) -> List[Claim]:
        """Return all claims currently shared with the federation."""
        stmt = (
            select(Claim)
            .where(Claim.claim_category == ClaimCategory.SHARED)
            .where(Claim.status == ClaimStatus.VERIFIED)
            .order_by(Claim.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_contested_claims(self, limit: int = 100) -> List[Claim]:
        """Return all claims currently under inter-node dispute."""
        stmt = (
            select(Claim)
            .where(Claim.claim_category == ClaimCategory.CONTESTED)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_claim(self, claim_id: str) -> Claim:
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is None:
            raise FederationError(f"Claim not found: {claim_id!r}")
        return claim

    async def _assert_node_allows_publication(self, node_id: str) -> None:
        stmt = select(NodeGovernancePolicy).where(NodeGovernancePolicy.node_id == node_id)
        result = await self.session.execute(stmt)
        policy = result.scalar_one_or_none()
        if policy and not policy.allow_claim_publication:
            raise FederationError(
                f"Node {node_id!r} governance policy does not permit claim publication."
            )

    async def _assert_node_allows_import(self, node_id: str) -> None:
        stmt = select(NodeGovernancePolicy).where(NodeGovernancePolicy.node_id == node_id)
        result = await self.session.execute(stmt)
        policy = result.scalar_one_or_none()
        if policy and not policy.allow_imported_claims:
            raise FederationError(
                f"Node {node_id!r} governance policy does not permit importing claims."
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_claim(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _claim_snapshot(claim: Claim) -> dict:
    """Serialisable snapshot of a claim at the time of a federation event."""
    return {
        "claim_id": claim.claim_id,
        "claim_number": claim.claim_number,
        "statement": claim.statement,
        "claim_hash": claim.claim_hash,
        "status": claim.status.value if claim.status else None,
        "claim_category": claim.claim_category.value if claim.claim_category else None,
        "confidence_score": claim.confidence_score,
        "version": claim.version,
        "source_id": claim.source_id,
        "origin_node_id": claim.origin_node_id,
        "snapshot_at": datetime.utcnow().isoformat(),
    }
