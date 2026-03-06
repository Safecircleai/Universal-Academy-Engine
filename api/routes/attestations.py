"""
UAE API — Verification Attestation Routes (Part 2)

POST   /attestations/keys                  Register a reviewer public key
GET    /attestations/keys/{reviewer_id}    Get reviewer key for a node
POST   /attestations                       Create an attestation
GET    /attestations/{attestation_id}      Get an attestation
POST   /attestations/{id}/verify           Re-verify an attestation signature
GET    /claims/{claim_id}/attestations     List attestations for a claim
POST   /attestations/dev/keygen            Generate a dev key pair (non-production)
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.attestation.attestation_manager import AttestationManager, AttestationError
from database.connection import get_async_session

router = APIRouter(prefix="/attestations", tags=["Cryptographic Attestations"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RegisterKeyRequest(BaseModel):
    node_id: str
    reviewer_id: str
    reviewer_name: Optional[str] = None
    reviewer_role: Optional[str] = None
    reviewer_credentials: Optional[list] = None
    public_key_pem: str
    signature_algorithm: str = "RSA-SHA256"
    valid_until: Optional[str] = None


class CreateAttestationRequest(BaseModel):
    claim_id: str
    log_id: Optional[str] = None
    reviewer_key_id: str
    reviewer_id: str
    reviewer_role: Optional[str] = None
    reviewer_signature: str = Field(..., description="Base64-encoded signature of the signing payload")
    verification_reason: Optional[str] = None
    signature_algorithm: str = "RSA-SHA256"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/keys", status_code=status.HTTP_201_CREATED)
async def register_reviewer_key(
    body: RegisterKeyRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Register a reviewer's public key for cryptographic attestation."""
    manager = AttestationManager(session)
    valid_until = None
    if body.valid_until:
        try:
            valid_until = datetime.fromisoformat(body.valid_until)
        except ValueError:
            pass
    try:
        key = await manager.register_reviewer_key(
            node_id=body.node_id,
            reviewer_id=body.reviewer_id,
            reviewer_name=body.reviewer_name,
            reviewer_role=body.reviewer_role,
            reviewer_credentials=body.reviewer_credentials,
            public_key_pem=body.public_key_pem,
            signature_algorithm=body.signature_algorithm,
            valid_until=valid_until,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "key_id": key.key_id,
        "reviewer_id": key.reviewer_id,
        "key_fingerprint": key.key_fingerprint,
        "signature_algorithm": key.signature_algorithm,
        "is_active": key.is_active,
        "created_at": key.created_at.isoformat(),
    }


@router.get("/keys/{reviewer_id}")
async def get_reviewer_key(
    reviewer_id: str,
    node_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = AttestationManager(session)
    key = await manager.get_reviewer_key(reviewer_id, node_id)
    if not key:
        raise HTTPException(status_code=404, detail="Reviewer key not found.")
    return {
        "key_id": key.key_id,
        "reviewer_id": key.reviewer_id,
        "reviewer_role": key.reviewer_role,
        "key_fingerprint": key.key_fingerprint,
        "signature_algorithm": key.signature_algorithm,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_attestation(
    body: CreateAttestationRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """
    Create a cryptographic attestation for a claim verification.

    The ``reviewer_signature`` must be a Base64-encoded signature of the
    canonical signing payload (obtainable from ``GET /attestations/payload``).
    """
    manager = AttestationManager(session)
    try:
        att = await manager.create_attestation(
            claim_id=body.claim_id,
            log_id=body.log_id,
            reviewer_key_id=body.reviewer_key_id,
            reviewer_id=body.reviewer_id,
            reviewer_role=body.reviewer_role,
            reviewer_signature=body.reviewer_signature,
            verification_reason=body.verification_reason,
            signature_algorithm=body.signature_algorithm,
        )
    except AttestationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _att_dict(att)


@router.get("/{attestation_id}")
async def get_attestation(
    attestation_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    from sqlalchemy import select
    from database.schemas.models import VerificationAttestation
    stmt = select(VerificationAttestation).where(
        VerificationAttestation.attestation_id == attestation_id
    )
    result = await session.execute(stmt)
    att = result.scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attestation not found.")
    return _att_dict(att)


@router.post("/{attestation_id}/verify")
async def verify_attestation(
    attestation_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Re-verify an attestation's signature against the stored public key."""
    manager = AttestationManager(session)
    try:
        result = await manager.verify_attestation(attestation_id)
    except AttestationError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.get("/claim/{claim_id}")
async def get_claim_attestations(
    claim_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    manager = AttestationManager(session)
    atts = await manager.get_claim_attestations(claim_id)
    return [_att_dict(a) for a in atts]


@router.post("/dev/keygen")
async def generate_dev_keypair():
    """
    Generate a development RSA key pair.

    WARNING: Do not use in production. Private keys should never leave the
    reviewer's machine. This endpoint exists solely for testing and development.
    """
    priv, pub = AttestationManager.generate_dev_key_pair()
    return {
        "private_key_pem": priv,
        "public_key_pem": pub,
        "warning": "DEVELOPMENT ONLY — never use this in production.",
    }


@router.get("/payload/{claim_id}")
async def get_signing_payload(
    claim_id: str,
    reviewer_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Return the canonical payload that a reviewer must sign."""
    from sqlalchemy import select
    from database.schemas.models import Claim
    import hashlib
    stmt = select(Claim).where(Claim.claim_id == claim_id)
    result = await session.execute(stmt)
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found.")
    claim_hash = hashlib.sha256(claim.statement.encode()).hexdigest()
    payload = AttestationManager.build_signing_payload(claim_id, claim_hash, reviewer_id)
    return {"claim_id": claim_id, "claim_hash": claim_hash, "signing_payload": payload}


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _att_dict(att) -> dict:
    return {
        "attestation_id": att.attestation_id,
        "claim_id": att.claim_id,
        "reviewer_id": att.reviewer_id,
        "reviewer_role": att.reviewer_role,
        "claim_hash": att.claim_hash,
        "signature_algorithm": att.signature_algorithm,
        "signature_verified": att.signature_verified,
        "verification_reason": att.verification_reason,
        "verification_timestamp": att.verification_timestamp.isoformat(),
    }
