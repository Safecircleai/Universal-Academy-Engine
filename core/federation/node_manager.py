"""
Universal Academy Engine — Node Manager (Part 1)

Manages the lifecycle of AcademyNode records: registration, policy
configuration, federation membership, and node-scoped queries.

Each node is an independent educational authority that shares a common
knowledge pipeline but governs its own claims, curriculum, and verification
standards.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    AcademyNode, NodeGovernancePolicy, NodeType, TrustTier
)

logger = logging.getLogger(__name__)


class NodeManagerError(Exception):
    """Raised when a node operation violates federation rules."""


class NodeManager:
    """CRUD and lifecycle operations for AcademyNode records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Node lifecycle
    # ------------------------------------------------------------------

    async def register_node(
        self,
        *,
        node_name: str,
        node_type: NodeType,
        description: str | None = None,
        contact_email: str | None = None,
        website_url: str | None = None,
        public_key_pem: str | None = None,
        did: str | None = None,
        metadata: dict | None = None,
    ) -> AcademyNode:
        """
        Register a new academy node in the federation.

        A default governance policy is created automatically.  Customise
        it via ``update_governance_policy()``.
        """
        existing = await self._find_by_name(node_name)
        if existing:
            raise NodeManagerError(
                f"A node named {node_name!r} is already registered (id={existing.node_id})."
            )

        node = AcademyNode(
            node_name=node_name,
            node_type=node_type,
            description=description,
            contact_email=contact_email,
            website_url=website_url,
            public_key_pem=public_key_pem,
            did=did,
            metadata_=metadata or {},
        )
        self.session.add(node)
        await self.session.flush()

        # Auto-create a default governance policy
        policy = NodeGovernancePolicy(node_id=node.node_id)
        self.session.add(policy)
        await self.session.flush()

        logger.info("Registered node %r (%s, id=%s)", node_name, node_type.value, node.node_id)
        return node

    async def retrieve_node(self, node_id: str) -> AcademyNode:
        stmt = select(AcademyNode).where(AcademyNode.node_id == node_id)
        result = await self.session.execute(stmt)
        node = result.scalar_one_or_none()
        if node is None:
            raise NodeManagerError(f"Node not found: {node_id!r}")
        return node

    async def find_node_by_name(self, name: str) -> Optional[AcademyNode]:
        return await self._find_by_name(name)

    async def list_nodes(
        self,
        *,
        node_type: NodeType | None = None,
        federation_members_only: bool = False,
        limit: int = 100,
    ) -> List[AcademyNode]:
        stmt = select(AcademyNode).where(AcademyNode.is_active == True)
        if node_type:
            stmt = stmt.where(AcademyNode.node_type == node_type)
        if federation_members_only:
            stmt = stmt.where(AcademyNode.is_federation_member == True)
        stmt = stmt.order_by(AcademyNode.node_name).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def admit_to_federation(self, node_id: str) -> AcademyNode:
        """Mark a node as a full federation member."""
        from datetime import datetime
        node = await self.retrieve_node(node_id)
        node.is_federation_member = True
        node.joined_federation_at = datetime.utcnow()
        await self.session.flush()
        logger.info("Node %s admitted to federation.", node_id)
        return node

    async def deactivate_node(self, node_id: str) -> AcademyNode:
        node = await self.retrieve_node(node_id)
        node.is_active = False
        node.is_federation_member = False
        await self.session.flush()
        logger.info("Node %s deactivated.", node_id)
        return node

    # ------------------------------------------------------------------
    # Governance policy
    # ------------------------------------------------------------------

    async def get_governance_policy(self, node_id: str) -> NodeGovernancePolicy:
        stmt = select(NodeGovernancePolicy).where(NodeGovernancePolicy.node_id == node_id)
        result = await self.session.execute(stmt)
        policy = result.scalar_one_or_none()
        if policy is None:
            raise NodeManagerError(f"No governance policy found for node {node_id!r}")
        return policy

    async def update_governance_policy(
        self,
        node_id: str,
        *,
        minimum_source_tier: TrustTier | None = None,
        required_reviewers: int | None = None,
        reviewer_roles: list[str] | None = None,
        verification_threshold: float | None = None,
        require_approval_to_publish: bool | None = None,
        allow_imported_claims: bool | None = None,
        allow_claim_publication: bool | None = None,
        auto_deprecate_after_days: int | None = None,
        require_human_review_above_confidence: float | None = None,
        notes: str | None = None,
    ) -> NodeGovernancePolicy:
        policy = await self.get_governance_policy(node_id)

        if minimum_source_tier is not None:
            policy.minimum_source_tier = minimum_source_tier
        if required_reviewers is not None:
            policy.required_reviewers = max(1, required_reviewers)
        if reviewer_roles is not None:
            policy.reviewer_roles = reviewer_roles
        if verification_threshold is not None:
            policy.verification_threshold = max(0.0, min(1.0, verification_threshold))
        if require_approval_to_publish is not None:
            policy.require_approval_to_publish = require_approval_to_publish
        if allow_imported_claims is not None:
            policy.allow_imported_claims = allow_imported_claims
        if allow_claim_publication is not None:
            policy.allow_claim_publication = allow_claim_publication
        if auto_deprecate_after_days is not None:
            policy.auto_deprecate_after_days = auto_deprecate_after_days
        if require_human_review_above_confidence is not None:
            policy.require_human_review_above_confidence = require_human_review_above_confidence
        if notes is not None:
            policy.notes = notes

        await self.session.flush()
        logger.info("Updated governance policy for node %s", node_id)
        return policy

    async def check_policy_compliance(
        self,
        node_id: str,
        *,
        source_tier: TrustTier | None = None,
        confidence_score: float | None = None,
    ) -> dict:
        """
        Check whether a proposed action complies with node governance policy.

        Returns a dict with ``compliant`` bool and list of ``violations``.
        """
        policy = await self.get_governance_policy(node_id)
        violations: list[str] = []

        tier_order = {TrustTier.TIER1: 1, TrustTier.TIER2: 2, TrustTier.TIER3: 3}
        if source_tier is not None:
            if tier_order[source_tier] > tier_order[policy.minimum_source_tier]:
                violations.append(
                    f"Source tier {source_tier.value!r} is below the required minimum "
                    f"{policy.minimum_source_tier.value!r} for node {node_id!r}."
                )

        if confidence_score is not None:
            if confidence_score < policy.verification_threshold:
                violations.append(
                    f"Confidence score {confidence_score:.2f} is below node threshold "
                    f"{policy.verification_threshold:.2f}."
                )

        return {"compliant": len(violations) == 0, "violations": violations}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _find_by_name(self, name: str) -> Optional[AcademyNode]:
        stmt = select(AcademyNode).where(AcademyNode.node_name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
