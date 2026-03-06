"""
UAE API — Academy Node Routes (Part 1 — Federation)

POST   /nodes                          Register a new academy node
GET    /nodes                          List nodes
GET    /nodes/{node_id}                Retrieve a node
POST   /nodes/{node_id}/federation     Admit node to federation
DELETE /nodes/{node_id}                Deactivate node
GET    /nodes/{node_id}/policy         Get governance policy
PATCH  /nodes/{node_id}/policy         Update governance policy
POST   /nodes/{node_id}/policy/check   Check policy compliance

POST   /federation/claims/{id}/publish  Publish claim to federation
POST   /federation/claims/{id}/import   Import a federated claim
POST   /federation/claims/{id}/contest  Contest a federated claim
POST   /federation/claims/{id}/adopt    Adopt a contested claim
GET    /federation/claims/published     List published claims
GET    /federation/claims/contested     List contested claims
GET    /federation/events               List federation events
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.federation.node_manager import NodeManager, NodeManagerError
from core.federation.claim_federation import ClaimFederationProtocol, FederationError
from database.connection import get_async_session
from database.schemas.models import NodeType, TrustTier

router = APIRouter(tags=["Federation & Nodes"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RegisterNodeRequest(BaseModel):
    node_name: str = Field(..., min_length=1)
    node_type: str
    description: Optional[str] = None
    contact_email: Optional[str] = None
    website_url: Optional[str] = None
    public_key_pem: Optional[str] = None
    did: Optional[str] = None
    metadata: Optional[dict] = None


class UpdatePolicyRequest(BaseModel):
    minimum_source_tier: Optional[str] = None
    required_reviewers: Optional[int] = None
    reviewer_roles: Optional[List[str]] = None
    verification_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    require_approval_to_publish: Optional[bool] = None
    allow_imported_claims: Optional[bool] = None
    allow_claim_publication: Optional[bool] = None
    auto_deprecate_after_days: Optional[int] = None
    require_human_review_above_confidence: Optional[float] = None
    notes: Optional[str] = None


class PolicyCheckRequest(BaseModel):
    source_tier: Optional[str] = None
    confidence_score: Optional[float] = None


class FederationActionRequest(BaseModel):
    node_id: str
    notes: Optional[str] = None
    reason: Optional[str] = None  # for contest


# ---------------------------------------------------------------------------
# Node endpoints
# ---------------------------------------------------------------------------

@router.post("/nodes", status_code=status.HTTP_201_CREATED)
async def register_node(
    body: RegisterNodeRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    try:
        node_type = NodeType(body.node_type)
        node = await manager.register_node(
            node_name=body.node_name,
            node_type=node_type,
            description=body.description,
            contact_email=body.contact_email,
            website_url=body.website_url,
            public_key_pem=body.public_key_pem,
            did=body.did,
            metadata=body.metadata,
        )
    except (NodeManagerError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _node_dict(node)


@router.get("/nodes")
async def list_nodes(
    node_type: Optional[str] = None,
    federation_members_only: bool = False,
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    nt = NodeType(node_type) if node_type else None
    nodes = await manager.list_nodes(
        node_type=nt,
        federation_members_only=federation_members_only,
        limit=min(limit, 200),
    )
    return [_node_dict(n) for n in nodes]


@router.get("/nodes/{node_id}")
async def get_node(
    node_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    try:
        node = await manager.retrieve_node(node_id)
    except NodeManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _node_dict(node)


@router.post("/nodes/{node_id}/federation")
async def admit_to_federation(
    node_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    try:
        node = await manager.admit_to_federation(node_id)
    except NodeManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _node_dict(node)


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_node(
    node_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    try:
        await manager.deactivate_node(node_id)
    except NodeManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/nodes/{node_id}/policy")
async def get_policy(
    node_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    try:
        policy = await manager.get_governance_policy(node_id)
    except NodeManagerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _policy_dict(policy)


@router.patch("/nodes/{node_id}/policy")
async def update_policy(
    node_id: str,
    body: UpdatePolicyRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    try:
        tier = TrustTier(body.minimum_source_tier) if body.minimum_source_tier else None
        policy = await manager.update_governance_policy(
            node_id,
            minimum_source_tier=tier,
            required_reviewers=body.required_reviewers,
            reviewer_roles=body.reviewer_roles,
            verification_threshold=body.verification_threshold,
            require_approval_to_publish=body.require_approval_to_publish,
            allow_imported_claims=body.allow_imported_claims,
            allow_claim_publication=body.allow_claim_publication,
            auto_deprecate_after_days=body.auto_deprecate_after_days,
            require_human_review_above_confidence=body.require_human_review_above_confidence,
            notes=body.notes,
        )
    except NodeManagerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _policy_dict(policy)


@router.post("/nodes/{node_id}/policy/check")
async def check_policy(
    node_id: str,
    body: PolicyCheckRequest,
    session: AsyncSession = Depends(get_async_session),
):
    manager = NodeManager(session)
    tier = TrustTier(body.source_tier) if body.source_tier else None
    result = await manager.check_policy_compliance(
        node_id,
        source_tier=tier,
        confidence_score=body.confidence_score,
    )
    return result


# ---------------------------------------------------------------------------
# Claim federation endpoints
# ---------------------------------------------------------------------------

@router.post("/federation/claims/{claim_id}/publish")
async def publish_claim(
    claim_id: str,
    body: FederationActionRequest,
    session: AsyncSession = Depends(get_async_session),
):
    protocol = ClaimFederationProtocol(session)
    try:
        record = await protocol.publish_claim(
            claim_id, body.node_id, notes=body.notes
        )
    except FederationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _fed_record_dict(record)


@router.post("/federation/claims/{claim_id}/import")
async def import_claim(
    claim_id: str,
    body: FederationActionRequest,
    session: AsyncSession = Depends(get_async_session),
):
    protocol = ClaimFederationProtocol(session)
    try:
        claim, record = await protocol.import_claim(
            claim_id, body.node_id, notes=body.notes
        )
    except FederationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"claim_id": claim_id, "record": _fed_record_dict(record)}


@router.post("/federation/claims/{claim_id}/contest")
async def contest_claim(
    claim_id: str,
    body: FederationActionRequest,
    session: AsyncSession = Depends(get_async_session),
):
    if not body.reason:
        raise HTTPException(status_code=400, detail="reason is required to contest a claim.")
    protocol = ClaimFederationProtocol(session)
    try:
        record = await protocol.contest_claim(
            claim_id, body.node_id, reason=body.reason, notes=body.notes
        )
    except FederationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _fed_record_dict(record)


@router.post("/federation/claims/{claim_id}/adopt")
async def adopt_claim(
    claim_id: str,
    body: FederationActionRequest,
    session: AsyncSession = Depends(get_async_session),
):
    protocol = ClaimFederationProtocol(session)
    try:
        record = await protocol.adopt_claim(
            claim_id, body.node_id, resolution_notes=body.notes
        )
    except FederationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _fed_record_dict(record)


@router.get("/federation/claims/published")
async def list_published_claims(
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    protocol = ClaimFederationProtocol(session)
    claims = await protocol.list_published_claims(limit=min(limit, 200))
    return [{"claim_id": c.claim_id, "claim_number": c.claim_number, "statement": c.statement} for c in claims]


@router.get("/federation/claims/contested")
async def list_contested_claims(
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    protocol = ClaimFederationProtocol(session)
    claims = await protocol.list_contested_claims(limit=min(limit, 200))
    return [{"claim_id": c.claim_id, "claim_number": c.claim_number, "statement": c.statement} for c in claims]


@router.get("/federation/events")
async def list_federation_events(
    claim_id: Optional[str] = None,
    node_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    protocol = ClaimFederationProtocol(session)
    records = await protocol.list_federation_events(
        claim_id=claim_id, node_id=node_id, action=action, limit=min(limit, 200)
    )
    return [_fed_record_dict(r) for r in records]


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _node_dict(node) -> dict:
    return {
        "node_id": node.node_id,
        "node_name": node.node_name,
        "node_type": node.node_type.value if node.node_type else None,
        "description": node.description,
        "is_federation_member": node.is_federation_member,
        "is_active": node.is_active,
        "did": node.did,
        "joined_federation_at": node.joined_federation_at.isoformat() if node.joined_federation_at else None,
        "created_at": node.created_at.isoformat(),
    }


def _policy_dict(policy) -> dict:
    return {
        "policy_id": policy.policy_id,
        "node_id": policy.node_id,
        "minimum_source_tier": policy.minimum_source_tier.value if policy.minimum_source_tier else None,
        "required_reviewers": policy.required_reviewers,
        "reviewer_roles": policy.reviewer_roles,
        "verification_threshold": policy.verification_threshold,
        "require_approval_to_publish": policy.require_approval_to_publish,
        "allow_imported_claims": policy.allow_imported_claims,
        "allow_claim_publication": policy.allow_claim_publication,
        "auto_deprecate_after_days": policy.auto_deprecate_after_days,
        "require_human_review_above_confidence": policy.require_human_review_above_confidence,
    }


def _fed_record_dict(record) -> dict:
    return {
        "record_id": record.record_id,
        "claim_id": record.claim_id,
        "action": record.action,
        "source_node_id": record.source_node_id,
        "target_node_id": record.target_node_id,
        "notes": record.notes,
        "timestamp": record.timestamp.isoformat(),
    }
