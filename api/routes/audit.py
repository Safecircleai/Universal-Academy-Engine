"""
UAE API — Audit & Transparency Routes (Part 8)

POST   /audit/claims/{claim_id}     Generate claim audit report
POST   /audit/courses/{course_id}   Generate course audit report
POST   /audit/nodes/{node_id}       Generate node audit report
GET    /audit/reports               List audit reports
GET    /audit/reports/{audit_id}    Get an audit report
GET    /audit/reports/{audit_id}/export  Export report as JSON

GET    /evidence/claim/{claim_id}   List evidence for a claim
POST   /evidence                    Add evidence to a claim
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit.audit_manager import AuditManager
from database.connection import get_async_session
from database.schemas.models import AuditReport, ClaimEvidence

router = APIRouter(tags=["Audit & Transparency"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class AddEvidenceRequest(BaseModel):
    claim_id: str
    source_id: str
    page_range: Optional[str] = None
    section: Optional[str] = None
    paragraph: Optional[int] = None
    figure_reference: Optional[str] = None
    timecode: Optional[str] = None
    exact_quote: Optional[str] = None
    extracted_text: Optional[str] = None
    diagram_reference: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Audit report endpoints
# ---------------------------------------------------------------------------

@router.post("/audit/claims/{claim_id}", status_code=status.HTTP_201_CREATED)
async def audit_claim(
    claim_id: str,
    generated_by: str = "api_user",
    session: AsyncSession = Depends(get_async_session),
):
    """Generate a comprehensive audit report for a single claim."""
    manager = AuditManager(session)
    try:
        report = await manager.audit_claim(claim_id, generated_by=generated_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _report_dict(report)


@router.post("/audit/courses/{course_id}", status_code=status.HTTP_201_CREATED)
async def audit_course(
    course_id: str,
    generated_by: str = "api_user",
    session: AsyncSession = Depends(get_async_session),
):
    """Generate a course audit: modules, lessons, claim citations, publishing history."""
    manager = AuditManager(session)
    try:
        report = await manager.audit_course(course_id, generated_by=generated_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _report_dict(report)


@router.post("/audit/nodes/{node_id}", status_code=status.HTTP_201_CREATED)
async def audit_node(
    node_id: str,
    generated_by: str = "api_user",
    session: AsyncSession = Depends(get_async_session),
):
    """Generate a governance summary audit for a node."""
    manager = AuditManager(session)
    try:
        report = await manager.audit_node(node_id, generated_by=generated_by)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _report_dict(report)


@router.get("/audit/reports")
async def list_audit_reports(
    report_type: Optional[str] = None,
    node_id: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    manager = AuditManager(session)
    reports = await manager.list_reports(
        report_type=report_type, node_id=node_id, limit=min(limit, 200)
    )
    return [_report_dict(r) for r in reports]


@router.get("/audit/reports/{audit_id}")
async def get_audit_report(
    audit_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(AuditReport).where(AuditReport.audit_id == audit_id)
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Audit report not found.")
    return _report_dict(report)


@router.get("/audit/reports/{audit_id}/export")
async def export_audit_report(
    audit_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """Export a full audit report as a JSON-serialisable dict."""
    manager = AuditManager(session)
    try:
        data = await manager.export_report(audit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return data


# ---------------------------------------------------------------------------
# Evidence endpoints (Part 3)
# ---------------------------------------------------------------------------

@router.post("/evidence", status_code=status.HTTP_201_CREATED)
async def add_evidence(
    body: AddEvidenceRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Add granular evidence reference to a claim."""
    import hashlib
    evidence_hash = None
    if body.exact_quote:
        evidence_hash = hashlib.sha256(body.exact_quote.encode()).hexdigest()

    evidence = ClaimEvidence(
        claim_id=body.claim_id,
        source_id=body.source_id,
        page_range=body.page_range,
        section=body.section,
        paragraph=body.paragraph,
        figure_reference=body.figure_reference,
        timecode=body.timecode,
        exact_quote=body.exact_quote,
        extracted_text=body.extracted_text,
        diagram_reference=body.diagram_reference,
        evidence_text_hash=evidence_hash,
        notes=body.notes,
    )
    session.add(evidence)
    await session.flush()
    return _evidence_dict(evidence)


@router.get("/evidence/claim/{claim_id}")
async def list_claim_evidence(
    claim_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """List all evidence fragments for a claim."""
    stmt = select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_id).order_by(ClaimEvidence.created_at)
    result = await session.execute(stmt)
    evidences = result.scalars().all()
    return [_evidence_dict(e) for e in evidences]


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def _report_dict(report) -> dict:
    return {
        "audit_id": report.audit_id,
        "report_type": report.report_type,
        "subject_id": report.subject_id,
        "generated_by": report.generated_by,
        "summary": report.summary,
        "created_at": report.created_at.isoformat(),
    }


def _evidence_dict(e) -> dict:
    return {
        "evidence_id": e.evidence_id,
        "claim_id": e.claim_id,
        "source_id": e.source_id,
        "page_range": e.page_range,
        "section": e.section,
        "paragraph": e.paragraph,
        "figure_reference": e.figure_reference,
        "timecode": e.timecode,
        "exact_quote": e.exact_quote,
        "evidence_text_hash": e.evidence_text_hash,
        "created_at": e.created_at.isoformat(),
    }
