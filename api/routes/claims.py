"""
UAE API — Claim Ledger Routes

POST   /claims                        Create a new claim
GET    /claims                        List claims
GET    /claims/{claim_id}             Retrieve a claim
POST   /claims/{claim_id}/verify      Verify a claim
PATCH  /claims/{claim_id}/status      Update claim status
GET    /claims/{claim_id}/history     Claim revision history
GET    /claims/{claim_id}/audit       Full governance audit trail
POST   /claims/{claim_id}/override    Human override
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.requests import (
    CreateClaimRequest, HumanOverrideRequest, UpdateClaimStatusRequest
)
from api.models.responses import AuditTrailResponse, ClaimResponse
from core.ingestion.claim_ledger import ClaimLedger, ClaimLedgerError
from core.governance.governance_manager import GovernanceManager
from database.connection import get_async_session
from database.schemas.models import ClaimStatus

router = APIRouter(prefix="/claims", tags=["Claims"])


@router.post("", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def create_claim(
    body: CreateClaimRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Create a new knowledge claim in draft status."""
    ledger = ClaimLedger(session)
    try:
        claim = await ledger.create_claim(
            statement=body.statement,
            source_id=body.source_id,
            concept_id=body.concept_id,
            citation_location=body.citation_location,
            confidence_score=body.confidence_score,
            tags=body.tags,
        )
    except ClaimLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ClaimResponse.model_validate(claim)


@router.get("", response_model=List[ClaimResponse])
async def list_claims(
    source_id: Optional[str] = None,
    concept_id: Optional[str] = None,
    claim_status: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    """List claims with optional filtering."""
    ledger = ClaimLedger(session)
    parsed_status = ClaimStatus(claim_status) if claim_status else None
    claims = await ledger.list_claims(
        source_id=source_id,
        concept_id=concept_id,
        status=parsed_status,
        min_confidence=min_confidence,
        limit=min(limit, 500),
        offset=offset,
    )
    return [ClaimResponse.model_validate(c) for c in claims]


@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    claim_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    ledger = ClaimLedger(session)
    try:
        claim = await ledger.retrieve_claim(claim_id)
    except ClaimLedgerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ClaimResponse.model_validate(claim)


@router.post("/{claim_id}/verify", response_model=ClaimResponse)
async def verify_claim(
    claim_id: str,
    reviewer: str = "api_user",
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_async_session),
):
    """Promote a draft claim to verified status."""
    ledger = ClaimLedger(session)
    try:
        claim = await ledger.verify_claim(claim_id, reviewer=reviewer, notes=notes)
    except ClaimLedgerError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ClaimResponse.model_validate(claim)


@router.patch("/{claim_id}/status", response_model=ClaimResponse)
async def update_claim_status(
    claim_id: str,
    body: UpdateClaimStatusRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Update the status of a claim with a recorded reason."""
    ledger = ClaimLedger(session)
    try:
        new_status = ClaimStatus(body.new_status)
        claim = await ledger.update_claim_status(
            claim_id, new_status, reason=body.reason, changed_by=body.changed_by
        )
    except (ClaimLedgerError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ClaimResponse.model_validate(claim)


@router.get("/{claim_id}/history")
async def get_claim_history(
    claim_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Return the revision history of a claim."""
    ledger = ClaimLedger(session)
    try:
        revisions = await ledger.get_claim_history(claim_id)
    except ClaimLedgerError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [
        {
            "revision_id": r.revision_id,
            "from": r.previous_version,
            "to": r.updated_version,
            "reason": r.change_reason,
            "changed_by": r.changed_by,
            "timestamp": r.timestamp.isoformat(),
        }
        for r in revisions
    ]


@router.get("/{claim_id}/audit", response_model=AuditTrailResponse)
async def get_audit_trail(
    claim_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Return the full governance audit trail for a claim."""
    gov = GovernanceManager(session)
    trail = await gov.get_claim_audit_trail(claim_id)
    return AuditTrailResponse(**trail)


@router.post("/{claim_id}/override", response_model=ClaimResponse)
async def human_override(
    claim_id: str,
    body: HumanOverrideRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Human reviewer overrides the AI-assigned status of a claim."""
    gov = GovernanceManager(session)
    try:
        new_status = ClaimStatus(body.new_status)
        claim = await gov.human_override_claim(
            claim_id, new_status, reviewer=body.reviewer, reason=body.reason
        )
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ClaimResponse.model_validate(claim)
