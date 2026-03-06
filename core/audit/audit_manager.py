"""
Universal Academy Engine — Audit Manager (Part 8)

Provides comprehensive audit and transparency capabilities.

Answers questions like:
  - Who verified this claim?
  - From which source?
  - When was it changed?
  - What replaced it?
  - Which courses depend on it?
  - What is the full governance trail?

All audit reports are exportable as JSON.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    AuditReport, Claim, ClaimRevision, ClaimStatus,
    Course, FederatedClaimRecord, Lesson, LessonClaim,
    Module, Source, VerificationAttestation, VerificationLog
)

logger = logging.getLogger(__name__)


class AuditManager:
    """
    Generates, stores, and exports structured audit reports.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Claim audit
    # ------------------------------------------------------------------

    async def audit_claim(
        self, claim_id: str, *, generated_by: str = "audit_manager"
    ) -> AuditReport:
        """
        Generate a full audit report for a single claim.

        Covers:
          - Claim details and current state
          - Source provenance
          - Full revision history
          - All verification logs
          - Cryptographic attestations
          - Federation events
          - Lessons that cite this claim
          - Supersession chain
        """
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        claim = result.scalar_one_or_none()
        if claim is None:
            raise ValueError(f"Claim not found: {claim_id!r}")

        # Source
        src_stmt = select(Source).where(Source.source_id == claim.source_id)
        src_result = await self.session.execute(src_stmt)
        source = src_result.scalar_one_or_none()

        # Revisions
        rev_stmt = select(ClaimRevision).where(
            ClaimRevision.claim_id == claim_id
        ).order_by(ClaimRevision.timestamp)
        rev_result = await self.session.execute(rev_stmt)
        revisions = rev_result.scalars().all()

        # Verification logs
        log_stmt = select(VerificationLog).where(
            VerificationLog.claim_id == claim_id
        ).order_by(VerificationLog.timestamp)
        log_result = await self.session.execute(log_stmt)
        logs = log_result.scalars().all()

        # Attestations
        att_stmt = select(VerificationAttestation).where(
            VerificationAttestation.claim_id == claim_id
        ).order_by(VerificationAttestation.verification_timestamp)
        att_result = await self.session.execute(att_stmt)
        attestations = att_result.scalars().all()

        # Federation events
        fed_stmt = select(FederatedClaimRecord).where(
            FederatedClaimRecord.claim_id == claim_id
        ).order_by(FederatedClaimRecord.timestamp)
        fed_result = await self.session.execute(fed_stmt)
        fed_events = fed_result.scalars().all()

        # Lessons that cite this claim
        lc_stmt = select(LessonClaim).where(LessonClaim.claim_id == claim_id)
        lc_result = await self.session.execute(lc_stmt)
        lesson_refs = lc_result.scalars().all()

        findings = {
            "claim": {
                "claim_id": claim.claim_id,
                "claim_number": claim.claim_number,
                "statement": claim.statement,
                "claim_hash": claim.claim_hash,
                "status": claim.status.value if claim.status else None,
                "claim_category": claim.claim_category.value if claim.claim_category else None,
                "confidence_score": claim.confidence_score,
                "version": claim.version,
                "created_at": claim.created_at.isoformat(),
                "updated_at": claim.updated_at.isoformat(),
                "superseded_by_id": claim.superseded_by_id,
                "origin_node_id": claim.origin_node_id,
            },
            "source": {
                "source_id": source.source_id if source else None,
                "title": source.title if source else None,
                "publisher": source.publisher if source else None,
                "trust_tier": source.trust_tier.value if source else None,
                "document_hash": source.document_hash if source else None,
                "citation_location": claim.citation_location,
            },
            "revision_history": [
                {
                    "revision_id": r.revision_id,
                    "from": r.previous_version,
                    "to": r.updated_version,
                    "reason": r.change_reason,
                    "changed_by": r.changed_by,
                    "timestamp": r.timestamp.isoformat(),
                }
                for r in revisions
            ],
            "verification_logs": [
                {
                    "log_id": l.log_id,
                    "result": l.verification_result,
                    "reviewer": l.reviewer,
                    "is_ai": l.is_ai_review,
                    "status": l.review_status.value,
                    "timestamp": l.timestamp.isoformat(),
                }
                for l in logs
            ],
            "attestations": [
                {
                    "attestation_id": a.attestation_id,
                    "reviewer_id": a.reviewer_id,
                    "reviewer_role": a.reviewer_role,
                    "algorithm": a.signature_algorithm,
                    "signature_verified": a.signature_verified,
                    "timestamp": a.verification_timestamp.isoformat(),
                }
                for a in attestations
            ],
            "federation_events": [
                {
                    "record_id": f.record_id,
                    "action": f.action,
                    "source_node_id": f.source_node_id,
                    "target_node_id": f.target_node_id,
                    "timestamp": f.timestamp.isoformat(),
                }
                for f in fed_events
            ],
            "cited_in_lessons": [
                {"lesson_id": lc.lesson_id, "inline_reference": lc.inline_reference}
                for lc in lesson_refs
            ],
        }

        summary = (
            f"Claim {claim.claim_number} ({claim.status.value if claim.status else 'unknown'}). "
            f"Source: {source.title if source else 'unknown'}. "
            f"{len(revisions)} revision(s). "
            f"{len(logs)} verification log(s). "
            f"{len(attestations)} attestation(s). "
            f"Cited in {len(lesson_refs)} lesson(s)."
        )

        report = AuditReport(
            report_type="claim",
            subject_id=claim_id,
            generated_by=generated_by,
            summary=summary,
            findings=findings,
        )
        self.session.add(report)
        await self.session.flush()
        return report

    # ------------------------------------------------------------------
    # Course audit
    # ------------------------------------------------------------------

    async def audit_course(
        self, course_id: str, *, generated_by: str = "audit_manager"
    ) -> AuditReport:
        """
        Audit a course: all modules, lessons, claim citations, and publishing history.
        """
        stmt = select(Course).where(Course.course_id == course_id)
        result = await self.session.execute(stmt)
        course = result.scalar_one_or_none()
        if course is None:
            raise ValueError(f"Course not found: {course_id!r}")

        mod_stmt = select(Module).where(Module.course_id == course_id).order_by(Module.order)
        mod_result = await self.session.execute(mod_stmt)
        modules = mod_result.scalars().all()

        modules_data = []
        total_lessons = 0
        total_claims = set()

        for mod in modules:
            les_stmt = select(Lesson).where(Lesson.module_id == mod.module_id).order_by(Lesson.order)
            les_result = await self.session.execute(les_stmt)
            lessons = les_result.scalars().all()
            total_lessons += len(lessons)

            lessons_data = []
            for lesson in lessons:
                lc_stmt = select(LessonClaim).where(LessonClaim.lesson_id == lesson.lesson_id)
                lc_result = await self.session.execute(lc_stmt)
                lcs = lc_result.scalars().all()
                claim_ids = [lc.claim_id for lc in lcs]
                total_claims.update(claim_ids)
                lessons_data.append({
                    "lesson_id": lesson.lesson_id,
                    "title": lesson.title,
                    "publishing_state": lesson.publishing_state.value if lesson.publishing_state else None,
                    "claim_count": len(claim_ids),
                    "claim_ids": claim_ids,
                })

            modules_data.append({
                "module_id": mod.module_id,
                "title": mod.title,
                "order": mod.order,
                "lessons": lessons_data,
            })

        findings = {
            "course": {
                "course_id": course.course_id,
                "title": course.title,
                "academy_node": course.academy_node,
                "version": course.version,
                "publishing_state": course.publishing_state.value if course.publishing_state else None,
                "approved_by": course.approved_by,
                "approved_at": course.approved_at.isoformat() if course.approved_at else None,
                "created_at": course.created_at.isoformat(),
            },
            "modules": modules_data,
            "summary_stats": {
                "total_modules": len(modules),
                "total_lessons": total_lessons,
                "unique_claims_referenced": len(total_claims),
            },
        }

        summary = (
            f"Course {course.title!r} ({course.publishing_state.value if course.publishing_state else 'unknown'}). "
            f"{len(modules)} modules, {total_lessons} lessons, "
            f"{len(total_claims)} unique claims referenced."
        )

        report = AuditReport(
            report_type="course",
            subject_id=course_id,
            generated_by=generated_by,
            summary=summary,
            findings=findings,
        )
        self.session.add(report)
        await self.session.flush()
        return report

    # ------------------------------------------------------------------
    # Node audit
    # ------------------------------------------------------------------

    async def audit_node(
        self, node_id: str, *, generated_by: str = "audit_manager"
    ) -> AuditReport:
        """Produce a governance summary for an academy node."""
        from database.schemas.models import AcademyNode, NodeGovernancePolicy

        stmt = select(AcademyNode).where(AcademyNode.node_id == node_id)
        result = await self.session.execute(stmt)
        node = result.scalar_one_or_none()
        if node is None:
            raise ValueError(f"Node not found: {node_id!r}")

        # Policy
        pol_stmt = select(NodeGovernancePolicy).where(NodeGovernancePolicy.node_id == node_id)
        pol_result = await self.session.execute(pol_stmt)
        policy = pol_result.scalar_one_or_none()

        # Claims originated by this node
        from sqlalchemy import func
        cl_stmt = select(func.count(Claim.claim_id)).where(Claim.origin_node_id == node_id)
        cl_result = await self.session.execute(cl_stmt)
        claim_count = cl_result.scalar_one() or 0

        verified_stmt = select(func.count(Claim.claim_id)).where(
            Claim.origin_node_id == node_id,
            Claim.status == ClaimStatus.VERIFIED,
        )
        verified_result = await self.session.execute(verified_stmt)
        verified_count = verified_result.scalar_one() or 0

        findings = {
            "node": {
                "node_id": node.node_id,
                "node_name": node.node_name,
                "node_type": node.node_type.value if node.node_type else None,
                "is_federation_member": node.is_federation_member,
                "joined_federation_at": node.joined_federation_at.isoformat() if node.joined_federation_at else None,
            },
            "governance_policy": {
                "minimum_source_tier": policy.minimum_source_tier.value if policy else None,
                "required_reviewers": policy.required_reviewers if policy else None,
                "verification_threshold": policy.verification_threshold if policy else None,
                "require_approval_to_publish": policy.require_approval_to_publish if policy else None,
                "allow_claim_publication": policy.allow_claim_publication if policy else None,
                "allow_imported_claims": policy.allow_imported_claims if policy else None,
            },
            "knowledge_stats": {
                "total_claims_originated": claim_count,
                "verified_claims": verified_count,
                "verification_rate": round(verified_count / claim_count, 3) if claim_count else 0,
            },
        }

        report = AuditReport(
            node_id=node_id,
            report_type="node",
            subject_id=node_id,
            generated_by=generated_by,
            summary=f"Node {node.node_name!r}: {claim_count} claims, {verified_count} verified.",
            findings=findings,
        )
        self.session.add(report)
        await self.session.flush()
        return report

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    async def export_report(self, audit_id: str) -> dict:
        """Return the full audit report as a JSON-serialisable dict."""
        stmt = select(AuditReport).where(AuditReport.audit_id == audit_id)
        result = await self.session.execute(stmt)
        report = result.scalar_one_or_none()
        if report is None:
            raise ValueError(f"AuditReport not found: {audit_id!r}")
        return {
            "audit_id": report.audit_id,
            "report_type": report.report_type,
            "subject_id": report.subject_id,
            "generated_by": report.generated_by,
            "summary": report.summary,
            "findings": report.findings,
            "created_at": report.created_at.isoformat(),
        }

    async def list_reports(
        self,
        *,
        report_type: str | None = None,
        node_id: str | None = None,
        limit: int = 50,
    ) -> list[AuditReport]:
        stmt = select(AuditReport)
        if report_type:
            stmt = stmt.where(AuditReport.report_type == report_type)
        if node_id:
            stmt = stmt.where(AuditReport.node_id == node_id)
        stmt = stmt.order_by(AuditReport.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
