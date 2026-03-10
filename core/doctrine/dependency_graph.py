"""
UAE v4 — Doctrine Dependency Graph

Tracks which claims depend on which doctrine sources, enabling impact
analysis when doctrine changes. Answers:

  "If I change claim X (which is immutable_core), what claims, lessons,
   courses, and credentials will be affected?"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ClaimClassification, ClaimStatus, Source, SourceType,
    LessonClaim, Lesson, Module, Course,
)

logger = logging.getLogger(__name__)


@dataclass
class DependencyNode:
    """A node in the doctrine dependency graph."""
    node_id: str
    node_type: str          # claim / lesson / module / course
    label: str
    source_type: Optional[str] = None
    status: Optional[str] = None
    depth: int = 0


@dataclass
class ImpactReport:
    """Result of an impact analysis for a doctrine change."""
    subject_claim_id: str
    subject_source_type: Optional[str]
    total_affected: int
    affected_claims: List[DependencyNode] = field(default_factory=list)
    affected_lessons: List[DependencyNode] = field(default_factory=list)
    affected_modules: List[DependencyNode] = field(default_factory=list)
    affected_courses: List[DependencyNode] = field(default_factory=list)
    dependency_chain: List[str] = field(default_factory=list)
    requires_doctrine_review: bool = False
    review_reason: str = ""

    @property
    def summary(self) -> dict:
        return {
            "subject_claim_id": self.subject_claim_id,
            "total_affected": self.total_affected,
            "affected_claims": len(self.affected_claims),
            "affected_lessons": len(self.affected_lessons),
            "affected_modules": len(self.affected_modules),
            "affected_courses": len(self.affected_courses),
            "requires_doctrine_review": self.requires_doctrine_review,
            "review_reason": self.review_reason,
        }


class DoctrineDependencyGraph:
    """
    Builds and queries the doctrine dependency graph.

    Usage::

        graph = DoctrineDependencyGraph(session)
        report = await graph.impact_analysis("claim-uuid")
        print(report.summary)
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def impact_analysis(
        self,
        claim_id: str,
        max_depth: int = 5,
    ) -> ImpactReport:
        """
        Analyse the downstream impact of a change to the given claim.

        Traverses:
          Claim → claims that classify against it (supersedes/conflicts_with)
          Claim → LessonClaims → Lessons → Modules → Courses

        Args:
            claim_id: The claim whose doctrine is being changed.
            max_depth: Maximum traversal depth (prevents infinite loops).

        Returns:
            ImpactReport with full impact breakdown.
        """
        subject_claim = await self._get_claim(claim_id)
        subject_source_type: Optional[str] = None
        if subject_claim:
            source = await self._get_source(subject_claim.source_id)
            subject_source_type = source.source_type.value if source and source.source_type else None

        # Collect downstream claims (those with doctrine_dependency referencing this claim)
        affected_claims = await self._find_dependent_claims(claim_id, max_depth)

        # Collect curriculum impact
        lesson_nodes, module_nodes, course_nodes = await self._find_curriculum_impact(claim_id)

        total_affected = (
            len(affected_claims) + len(lesson_nodes) +
            len(module_nodes) + len(course_nodes)
        )

        requires_review = subject_source_type in (
            SourceType.IMMUTABLE_CORE.value,
            SourceType.CONSTITUTIONAL_DOCTRINE.value,
            SourceType.GOVERNANCE_SPEC.value,
        )

        review_reason = ""
        if requires_review:
            review_reason = (
                f"Changing a {subject_source_type!r} claim affects "
                f"{total_affected} downstream entity(ies). "
                "Governance review is required before propagation."
            )

        return ImpactReport(
            subject_claim_id=claim_id,
            subject_source_type=subject_source_type,
            total_affected=total_affected,
            affected_claims=affected_claims,
            affected_lessons=lesson_nodes,
            affected_modules=module_nodes,
            affected_courses=course_nodes,
            requires_doctrine_review=requires_review,
            review_reason=review_reason,
        )

    async def get_doctrine_chain(self, claim_id: str) -> List[dict]:
        """
        Return the precedence chain for a claim: its source type hierarchy
        path from immutable_core down to the claim's own level.
        """
        claim = await self._get_claim(claim_id)
        if not claim:
            return []

        source = await self._get_source(claim.source_id)
        if not source or not source.source_type:
            return []

        from core.doctrine.precedence_engine import PrecedenceEngine, _PRECEDENCE_ORDER
        engine = PrecedenceEngine()
        level = engine.precedence_level(source.source_type)
        chain = []
        for i, st in enumerate(_PRECEDENCE_ORDER):
            chain.append({
                "source_type": st.value,
                "precedence_level": i,
                "is_subject": i == level,
                "is_higher_authority": i < level,
            })
        return chain

    async def find_conflicts_for_claim(self, claim_id: str) -> List[dict]:
        """
        Return all other verified claims that are marked as conflicts_with
        or supersedes relative to this claim.
        """
        stmt = (
            select(Claim)
            .where(
                Claim.doctrine_dependency.isnot(None)
            )
            .where(Claim.status != ClaimStatus.DEPRECATED)
        )
        result = await self.session.execute(stmt)
        candidates = result.scalars().all()

        conflicts = []
        for c in candidates:
            dep = c.doctrine_dependency or {}
            dep_ids = dep.get("dependency_ids", [])
            if claim_id in dep_ids:
                conflicts.append({
                    "claim_id": c.claim_id,
                    "claim_number": c.claim_number,
                    "classification": c.claim_classification.value if c.claim_classification else None,
                    "status": c.status.value,
                })
        return conflicts

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_claim(self, claim_id: str) -> Optional[Claim]:
        stmt = select(Claim).where(Claim.claim_id == claim_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_source(self, source_id: str) -> Optional[Source]:
        stmt = select(Source).where(Source.source_id == source_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_dependent_claims(
        self, claim_id: str, max_depth: int
    ) -> List[DependencyNode]:
        """Find claims whose doctrine_dependency references claim_id."""
        visited: Set[str] = set()
        nodes: List[DependencyNode] = []

        async def _traverse(cid: str, depth: int) -> None:
            if depth >= max_depth or cid in visited:
                return
            visited.add(cid)

            stmt = (
                select(Claim)
                .where(Claim.doctrine_dependency.isnot(None))
                .where(Claim.status != ClaimStatus.DEPRECATED)
            )
            result = await self.session.execute(stmt)
            candidates = result.scalars().all()

            for c in candidates:
                dep = c.doctrine_dependency or {}
                dep_ids = dep.get("dependency_ids", [])
                if cid in dep_ids and c.claim_id not in visited:
                    source = await self._get_source(c.source_id)
                    nodes.append(DependencyNode(
                        node_id=c.claim_id,
                        node_type="claim",
                        label=c.claim_number or c.claim_id,
                        source_type=source.source_type.value if source and source.source_type else None,
                        status=c.status.value,
                        depth=depth + 1,
                    ))
                    await _traverse(c.claim_id, depth + 1)

        await _traverse(claim_id, 0)
        return nodes

    async def _find_curriculum_impact(
        self, claim_id: str
    ) -> tuple[List[DependencyNode], List[DependencyNode], List[DependencyNode]]:
        """Traverse claim → lesson_claims → lessons → modules → courses."""
        # Lessons referencing this claim
        stmt = (
            select(LessonClaim)
            .where(LessonClaim.claim_id == claim_id)
        )
        result = await self.session.execute(stmt)
        lesson_claims = result.scalars().all()

        lesson_ids: Set[str] = {lc.lesson_id for lc in lesson_claims}
        lesson_nodes: List[DependencyNode] = []
        module_ids: Set[str] = set()
        module_nodes: List[DependencyNode] = []
        course_ids: Set[str] = set()
        course_nodes: List[DependencyNode] = []

        for lid in lesson_ids:
            stmt = select(Lesson).where(Lesson.lesson_id == lid)
            result = await self.session.execute(stmt)
            lesson = result.scalar_one_or_none()
            if lesson:
                lesson_nodes.append(DependencyNode(
                    node_id=lesson.lesson_id,
                    node_type="lesson",
                    label=lesson.title,
                    status=lesson.publishing_state.value if lesson.publishing_state else None,
                ))
                module_ids.add(lesson.module_id)

        for mid in module_ids:
            stmt = select(Module).where(Module.module_id == mid)
            result = await self.session.execute(stmt)
            module = result.scalar_one_or_none()
            if module:
                module_nodes.append(DependencyNode(
                    node_id=module.module_id,
                    node_type="module",
                    label=module.title,
                ))
                course_ids.add(module.course_id)

        for cid in course_ids:
            stmt = select(Course).where(Course.course_id == cid)
            result = await self.session.execute(stmt)
            course = result.scalar_one_or_none()
            if course:
                course_nodes.append(DependencyNode(
                    node_id=course.course_id,
                    node_type="course",
                    label=course.title,
                    status=course.publishing_state.value if course.publishing_state else None,
                ))

        return lesson_nodes, module_nodes, course_nodes
