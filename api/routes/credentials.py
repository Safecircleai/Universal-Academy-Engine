"""
UAE API — Credential Issuance Routes (Part 6)

POST   /credentials                         Issue a credential
GET    /credentials/{id}                    Get a credential
GET    /credentials/{id}/json               Export as W3C VC JSON
GET    /credentials/{id}/token              Export as portable token
POST   /credentials/{id}/verify             Verify credential integrity
POST   /credentials/{id}/revoke             Revoke a credential
GET    /credentials/student/{student_id}    List student's credentials
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.credentials.credential_issuer import CredentialIssuer, CredentialError
from database.connection import get_async_session
from database.schemas.models import Credential, CredentialType

router = APIRouter(prefix="/credentials", tags=["Credentials"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class IssueCredentialRequest(BaseModel):
    student_id: str = Field(..., min_length=1)
    student_name: Optional[str] = None
    student_email: Optional[str] = None
    course_id: str
    issuing_node_id: str
    issued_by: str
    credential_type: str = "completion"
    expiry_date: Optional[str] = None
    signing_private_key_pem: Optional[str] = None


class RevokeRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    revoked_by: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def issue_credential(
    body: IssueCredentialRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Issue a verifiable credential upon course completion."""
    issuer = CredentialIssuer(session)
    try:
        cred_type = CredentialType(body.credential_type)
        expiry = datetime.fromisoformat(body.expiry_date) if body.expiry_date else None
        credential = await issuer.issue_credential(
            student_id=body.student_id,
            student_name=body.student_name,
            student_email=body.student_email,
            course_id=body.course_id,
            issuing_node_id=body.issuing_node_id,
            issued_by=body.issued_by,
            credential_type=cred_type,
            expiry_date=expiry,
            signing_private_key_pem=body.signing_private_key_pem,
        )
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _cred_dict(credential)


@router.get("/{credential_id}")
async def get_credential(
    credential_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(Credential).where(Credential.credential_id == credential_id)
    result = await session.execute(stmt)
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found.")
    return _cred_dict(cred)


@router.get("/{credential_id}/json")
async def export_credential_json(
    credential_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Export credential as a W3C Verifiable Credential JSON document."""
    issuer = CredentialIssuer(session)
    try:
        doc = await issuer.export_json(credential_id)
    except CredentialError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return doc


@router.get("/{credential_id}/token")
async def export_portable_token(
    credential_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Export credential as a Base64-encoded portable verification token."""
    issuer = CredentialIssuer(session)
    try:
        token = await issuer.export_portable_token(credential_id)
    except CredentialError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"credential_id": credential_id, "token": token}


@router.post("/{credential_id}/verify")
async def verify_credential(
    credential_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Verify a credential's integrity (not revoked, not expired, hash valid)."""
    issuer = CredentialIssuer(session)
    try:
        result = await issuer.verify_credential(credential_id)
    except CredentialError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.post("/{credential_id}/revoke")
async def revoke_credential(
    credential_id: str,
    body: RevokeRequest,
    session: AsyncSession = Depends(get_async_session),
):
    issuer = CredentialIssuer(session)
    try:
        cred = await issuer.revoke_credential(
            credential_id, reason=body.reason, revoked_by=body.revoked_by
        )
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"credential_id": credential_id, "is_revoked": cred.is_revoked, "revoked_at": cred.revoked_at.isoformat()}


@router.get("/student/{student_id}")
async def list_student_credentials(
    student_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    issuer = CredentialIssuer(session)
    creds = await issuer.list_student_credentials(student_id)
    return [_cred_dict(c) for c in creds]


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _cred_dict(cred) -> dict:
    return {
        "credential_id": cred.credential_id,
        "student_id": cred.student_id,
        "student_name": cred.student_name,
        "course_id": cred.course_id,
        "issuing_node_id": cred.issuing_node_id,
        "credential_type": cred.credential_type.value if cred.credential_type else None,
        "credential_hash": cred.credential_hash,
        "issue_date": cred.issue_date.isoformat(),
        "expiry_date": cred.expiry_date.isoformat() if cred.expiry_date else None,
        "is_revoked": cred.is_revoked,
    }
