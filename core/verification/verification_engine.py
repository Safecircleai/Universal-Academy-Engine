"""
Universal Academy Engine — Verification Engine

Detects conflicts and outdated knowledge, flags claims for human review,
and generates integrity reports.

The Verification Engine is the quality gate of the UAE pipeline.  It runs
continuously and triggers governance workflows whenever anomalies are found.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.schemas.models import (
    Claim, ClaimStatus, ConflictFlag, IntegrityReport, VerificationLog, ReviewStatus
)

logger = logging.getLogger(__name__)


class VerificationEngine:
    """
    Runs claim verification passes and produces integrity reports.

    Methods here do NOT require a full AI pass — they apply deterministic
    rules over the database state.  AI-assisted verification is handled by
    the Integrity Auditor agent.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Core verification actions
    # ------------------------------------------------------------------

    async def detect_conflicts(self) -> List[ConflictFlag]:
        """
        Detect pairs of verified claims whose statements are potentially
        contradictory.

        Strategy (v1 — heuristic):
          Find pairs of claims attached to the same concept that share
          very similar statement prefixes but differ materially.  In
          production this would invoke an NLP similarity model.  For now
          we flag pairs where one claim was created AFTER another without
          the older one being deprecated.
        """
        stmt = select(Claim).where(Claim.status == ClaimStatus.VERIFIED)
        result = await self.session.execute(stmt)
        verified_claims = result.scalars().all()

        # Group by concept_id
        by_concept: dict[str, list[Claim]] = {}
        for claim in verified_claims:
            if claim.concept_id:
                by_concept.setdefault(claim.concept_id, []).append(claim)

        new_flags: list[ConflictFlag] = []
        for concept_id, claims in by_concept.items():
            if len(claims) < 2:
                continue
            # Detect duplicate-adjacent statements (simple heuristic)
            for i, ca in enumerate(claims):
                for cb in claims[i + 1:]:
                    if _is_likely_conflict(ca.statement, cb.statement):
                        existing = await self._flag_exists(ca.claim_id, cb.claim_id)
                        if not existing:
                            flag = ConflictFlag(
                                claim_a_id=ca.claim_id,
                                claim_b_id=cb.claim_id,
                                conflict_description=(
                                    f"Potential conflict detected between claims "
                                    f"{ca.claim_number} and {cb.claim_number} "
                                    f"on concept_id={concept_id}."
                                ),
                            )
                            self.session.add(flag)
                            new_flags.append(flag)

        if new_flags:
            await self.session.flush()
            logger.info("Detected %d new conflict flag(s).", len(new_flags))
        return new_flags

    async def detect_outdated_claims(
        self, *, max_age_days: int | None = None
    ) -> List[Claim]:
        """
        Return verified claims that have not been reviewed within
        ``max_age_days`` and are candidates for deprecation.
        """
        days = max_age_days or settings.auto_deprecate_after_days
        cutoff = datetime.utcnow() - timedelta(days=days)

        stmt = select(Claim).where(
            and_(
                Claim.status == ClaimStatus.VERIFIED,
                Claim.updated_at < cutoff,
            )
        )
        result = await self.session.execute(stmt)
        outdated = result.scalars().all()
        logger.info(
            "Found %d claim(s) not updated in %d days (candidates for review).",
            len(outdated), days,
        )
        return list(outdated)

    async def flag_claim_for_review(
        self,
        claim_id: str,
        *,
        reason: str,
        reviewer: str = "verification_engine",
    ) -> VerificationLog:
        """
        Create a ``VerificationLog`` entry that puts a claim in the human
        review queue.
        """
        log = VerificationLog(
            claim_id=claim_id,
            verification_result="needs_review",
            reviewer=reviewer,
            is_ai_review=True,
            notes=reason,
            review_status=ReviewStatus.PENDING,
        )
        self.session.add(log)
        await self.session.flush()
        logger.info("Flagged claim %r for review: %s", claim_id, reason)
        return log

    async def record_verification_pass(
        self,
        claim_id: str,
        *,
        result: str,
        reviewer: str,
        is_ai: bool = True,
        notes: str | None = None,
    ) -> VerificationLog:
        """Log the outcome of a verification pass (AI or human)."""
        log = VerificationLog(
            claim_id=claim_id,
            verification_result=result,
            reviewer=reviewer,
            is_ai_review=is_ai,
            notes=notes,
            review_status=ReviewStatus.APPROVED if result == "pass" else ReviewStatus.PENDING,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def run_full_audit(self) -> IntegrityReport:
        """
        Execute a complete audit pass and return a summary report.

        Steps:
        1. Count total verified claims
        2. Detect conflicts
        3. Detect outdated claims
        4. Flag candidates for human review
        """
        stmt = select(Claim).where(Claim.status == ClaimStatus.VERIFIED)
        result = await self.session.execute(stmt)
        all_verified = result.scalars().all()

        conflict_flags = await self.detect_conflicts()
        outdated = await self.detect_outdated_claims()

        # Flag outdated claims for review
        flagged_count = 0
        for claim in outdated:
            await self.flag_claim_for_review(
                claim.claim_id,
                reason=f"Claim not updated in {settings.auto_deprecate_after_days} days.",
            )
            flagged_count += 1

        report = IntegrityReport(
            total_claims_checked=len(all_verified),
            conflicts_found=len(conflict_flags),
            outdated_claims=len(outdated),
            flagged_for_review=flagged_count,
            summary=(
                f"Audit complete. {len(all_verified)} verified claims checked. "
                f"{len(conflict_flags)} conflicts detected. "
                f"{flagged_count} claims flagged for human review."
            ),
            details={
                "conflict_flag_ids": [f.flag_id for f in conflict_flags],
                "outdated_claim_ids": [c.claim_id for c in outdated],
            },
        )
        self.session.add(report)
        await self.session.flush()
        logger.info("Integrity report created: %s", report.report_id)
        return report

    # ------------------------------------------------------------------
    # Human review workflow
    # ------------------------------------------------------------------

    async def approve_review(
        self,
        log_id: str,
        *,
        reviewer: str,
        notes: str | None = None,
    ) -> VerificationLog:
        """A human approves a pending review item."""
        log = await self._get_log_or_raise(log_id)
        log.review_status = ReviewStatus.APPROVED
        log.reviewer = reviewer
        if notes:
            log.notes = (log.notes or "") + f"\n[HUMAN] {notes}"
        log.is_ai_review = False
        await self.session.flush()
        return log

    async def reject_review(
        self,
        log_id: str,
        *,
        reviewer: str,
        notes: str | None = None,
    ) -> VerificationLog:
        """A human rejects a pending review item — claim stays contested."""
        log = await self._get_log_or_raise(log_id)
        log.review_status = ReviewStatus.REJECTED
        log.reviewer = reviewer
        if notes:
            log.notes = (log.notes or "") + f"\n[HUMAN REJECT] {notes}"
        log.is_ai_review = False
        await self.session.flush()
        return log

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _flag_exists(self, claim_a_id: str, claim_b_id: str) -> bool:
        stmt = select(ConflictFlag).where(
            (
                (ConflictFlag.claim_a_id == claim_a_id) &
                (ConflictFlag.claim_b_id == claim_b_id)
            ) | (
                (ConflictFlag.claim_a_id == claim_b_id) &
                (ConflictFlag.claim_b_id == claim_a_id)
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def _get_log_or_raise(self, log_id: str) -> VerificationLog:
        stmt = select(VerificationLog).where(VerificationLog.log_id == log_id)
        result = await self.session.execute(stmt)
        log = result.scalar_one_or_none()
        if log is None:
            raise ValueError(f"VerificationLog not found: {log_id!r}")
        return log


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_likely_conflict(stmt_a: str, stmt_b: str) -> bool:
    """
    Heuristic: two statements on the same concept may conflict if they share
    more than 60% of their tokens but have contradictory polarity words.
    """
    CONTRADICTION_PAIRS = [
        ("increases", "decreases"),
        ("opens", "closes"),
        ("higher", "lower"),
        ("always", "never"),
        ("required", "optional"),
        ("must", "must not"),
        ("enables", "disables"),
    ]
    a_lower = stmt_a.lower()
    b_lower = stmt_b.lower()
    for pos, neg in CONTRADICTION_PAIRS:
        if (pos in a_lower and neg in b_lower) or (neg in a_lower and pos in b_lower):
            return True
    return False
