"""
UAE API — Verification & Integrity Routes

POST   /verification/run          Run verification audit
GET    /verification/reports       List integrity reports
GET    /verification/reports/{id}  Get a specific report
GET    /verification/pending       List claims pending review
POST   /verification/approve/{log_id}  Human approves a review item
POST   /verification/reject/{log_id}   Human rejects a review item

POST   /agents/source_sentinel     Run Source Sentinel agent
POST   /agents/integrity_auditor   Run Integrity Auditor agent
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.integrity_auditor import IntegrityAuditorAgent
from agents.source_sentinel import SourceSentinelAgent
from api.models.requests import RunAgentRequest, RunVerificationRequest
from api.models.responses import IntegrityReportResponse
from core.verification.verification_engine import VerificationEngine
from database.connection import get_async_session
from database.schemas.models import IntegrityReport, ReviewStatus, VerificationLog

router = APIRouter(tags=["Verification & Governance"])


@router.post("/verification/run", response_model=IntegrityReportResponse)
async def run_verification(
    body: RunVerificationRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Execute a verification audit pass."""
    engine = VerificationEngine(session)

    if body.mode == "full":
        report = await engine.run_full_audit()
    else:
        agent = IntegrityAuditorAgent(session)
        result = await agent.run({
            "mode": body.mode,
            "max_age_days": body.max_age_days,
            "escalate_high_confidence": body.escalate_high_confidence,
        })
        # Fetch the report if created
        if result.get("report_id"):
            stmt = select(IntegrityReport).where(IntegrityReport.report_id == result["report_id"])
            res = await session.execute(stmt)
            report = res.scalar_one_or_none()
        else:
            # Create a synthetic report record
            report = IntegrityReport(
                run_by="integrity_auditor_agent",
                total_claims_checked=0,
                conflicts_found=result.get("conflicts_found", 0),
                outdated_claims=result.get("outdated_found", 0),
                flagged_for_review=result.get("flagged_for_review", 0),
                summary=f"Mode: {body.mode}. {result}",
            )
            session.add(report)
            await session.flush()

    return IntegrityReportResponse.model_validate(report)


@router.get("/verification/reports", response_model=List[IntegrityReportResponse])
async def list_reports(
    limit: int = 20,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(IntegrityReport).order_by(IntegrityReport.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    reports = result.scalars().all()
    return [IntegrityReportResponse.model_validate(r) for r in reports]


@router.get("/verification/reports/{report_id}", response_model=IntegrityReportResponse)
async def get_report(
    report_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    stmt = select(IntegrityReport).where(IntegrityReport.report_id == report_id)
    result = await session.execute(stmt)
    report = result.scalar_one_or_none()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    return IntegrityReportResponse.model_validate(report)


@router.get("/verification/pending")
async def list_pending_reviews(
    limit: int = 50,
    session: AsyncSession = Depends(get_async_session),
):
    """Return claims currently pending human review."""
    stmt = (
        select(VerificationLog)
        .where(VerificationLog.review_status == ReviewStatus.PENDING)
        .order_by(VerificationLog.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "log_id": l.log_id,
            "claim_id": l.claim_id,
            "verification_result": l.verification_result,
            "reviewer": l.reviewer,
            "is_ai_review": l.is_ai_review,
            "notes": l.notes,
            "timestamp": l.timestamp.isoformat(),
        }
        for l in logs
    ]


@router.post("/verification/approve/{log_id}")
async def approve_review(
    log_id: str,
    reviewer: str = "human_reviewer",
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_async_session),
):
    engine = VerificationEngine(session)
    try:
        log = await engine.approve_review(log_id, reviewer=reviewer, notes=notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"log_id": log.log_id, "status": log.review_status.value, "reviewer": log.reviewer}


@router.post("/verification/reject/{log_id}")
async def reject_review(
    log_id: str,
    reviewer: str = "human_reviewer",
    notes: Optional[str] = None,
    session: AsyncSession = Depends(get_async_session),
):
    engine = VerificationEngine(session)
    try:
        log = await engine.reject_review(log_id, reviewer=reviewer, notes=notes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"log_id": log.log_id, "status": log.review_status.value, "reviewer": log.reviewer}


# ---------------------------------------------------------------------------
# Agent endpoints
# ---------------------------------------------------------------------------

@router.post("/agents/source_sentinel")
async def run_source_sentinel(
    body: RunAgentRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Run the Source Sentinel agent to ingest a document."""
    agent = SourceSentinelAgent(session)
    try:
        result = await agent.run(body.payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/agents/integrity_auditor")
async def run_integrity_auditor(
    body: RunAgentRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Run the Integrity Auditor agent."""
    agent = IntegrityAuditorAgent(session)
    try:
        result = await agent.run(body.payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result
