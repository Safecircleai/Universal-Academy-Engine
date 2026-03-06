"""
Universal Academy Engine — Competency & Standards Manager (Part 5)

Maps curriculum entities to external competency frameworks and standards.

Supported entity types for mapping:
  - Claim     → Competency  (what claim supports this skill)
  - Lesson    → Competency  (what skills this lesson develops)
  - Course    → Competency  (what skills this course certifies)
  - Concept   → Competency  (what concepts align to this skill)

Standards integration examples:
  - NATEF automotive tasks
  - Common Core academic standards
  - ASE certification requirements
  - CompTIA certification objectives
  - ISO 9001 quality management competencies
"""

from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Competency, CompetencyMapping, SkillLevel, Standard
)

logger = logging.getLogger(__name__)


class CompetencyError(Exception):
    pass


class CompetencyManager:
    """CRUD and query operations for the competency framework."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Standard management
    # ------------------------------------------------------------------

    async def create_standard(
        self,
        *,
        name: str,
        issuing_body: str,
        version: str | None = None,
        description: str | None = None,
        url: str | None = None,
        domain: str | None = None,
    ) -> Standard:
        existing = await self._find_standard_by_name(name)
        if existing:
            return existing

        std = Standard(
            name=name,
            issuing_body=issuing_body,
            version=version,
            description=description,
            url=url,
            domain=domain,
        )
        self.session.add(std)
        await self.session.flush()
        logger.info("Created standard %r (%s)", name, issuing_body)
        return std

    async def list_standards(self, limit: int = 100) -> List[Standard]:
        stmt = select(Standard).where(Standard.is_active == True).order_by(Standard.name).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Competency management
    # ------------------------------------------------------------------

    async def create_competency(
        self,
        *,
        name: str,
        description: str | None = None,
        skill_level: SkillLevel = SkillLevel.FOUNDATIONAL,
        domain: str | None = None,
        code: str | None = None,
        industry_standard_reference: str | None = None,
        standard_id: str | None = None,
        node_id: str | None = None,
    ) -> Competency:
        comp = Competency(
            name=name,
            description=description,
            skill_level=skill_level,
            domain=domain,
            code=code,
            industry_standard_reference=industry_standard_reference,
            standard_id=standard_id,
            node_id=node_id,
        )
        self.session.add(comp)
        await self.session.flush()
        logger.info("Created competency %r (level=%s)", name, skill_level.value)
        return comp

    async def retrieve_competency(self, competency_id: str) -> Competency:
        stmt = select(Competency).where(Competency.competency_id == competency_id)
        result = await self.session.execute(stmt)
        comp = result.scalar_one_or_none()
        if comp is None:
            raise CompetencyError(f"Competency not found: {competency_id!r}")
        return comp

    async def list_competencies(
        self,
        *,
        domain: str | None = None,
        skill_level: SkillLevel | None = None,
        standard_id: str | None = None,
        limit: int = 100,
    ) -> List[Competency]:
        stmt = select(Competency).where(Competency.is_active == True)
        if domain:
            stmt = stmt.where(Competency.domain == domain)
        if skill_level:
            stmt = stmt.where(Competency.skill_level == skill_level)
        if standard_id:
            stmt = stmt.where(Competency.standard_id == standard_id)
        stmt = stmt.order_by(Competency.name).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Mapping operations
    # ------------------------------------------------------------------

    async def map_claim_to_competency(
        self,
        claim_id: str,
        competency_id: str,
        *,
        alignment_notes: str | None = None,
    ) -> CompetencyMapping:
        return await self._create_mapping(
            competency_id=competency_id,
            claim_id=claim_id,
            alignment_notes=alignment_notes,
        )

    async def map_lesson_to_competency(
        self,
        lesson_id: str,
        competency_id: str,
        *,
        alignment_notes: str | None = None,
    ) -> CompetencyMapping:
        return await self._create_mapping(
            competency_id=competency_id,
            lesson_id=lesson_id,
            alignment_notes=alignment_notes,
        )

    async def map_course_to_competency(
        self,
        course_id: str,
        competency_id: str,
        *,
        alignment_notes: str | None = None,
    ) -> CompetencyMapping:
        return await self._create_mapping(
            competency_id=competency_id,
            course_id=course_id,
            alignment_notes=alignment_notes,
        )

    async def map_concept_to_competency(
        self,
        concept_id: str,
        competency_id: str,
        *,
        alignment_notes: str | None = None,
    ) -> CompetencyMapping:
        return await self._create_mapping(
            competency_id=competency_id,
            concept_id=concept_id,
            alignment_notes=alignment_notes,
        )

    async def get_competencies_for_course(self, course_id: str) -> List[Competency]:
        """Return all competencies addressed by a course (directly or via lessons)."""
        # Direct course mappings
        stmt = (
            select(Competency)
            .join(CompetencyMapping, CompetencyMapping.competency_id == Competency.competency_id)
            .where(CompetencyMapping.course_id == course_id)
        )
        result = await self.session.execute(stmt)
        direct = list(result.scalars().all())

        # Via lessons in this course
        from database.schemas.models import Lesson, Module, Course
        lesson_stmt = (
            select(Competency)
            .join(CompetencyMapping, CompetencyMapping.competency_id == Competency.competency_id)
            .join(Lesson, Lesson.lesson_id == CompetencyMapping.lesson_id)
            .join(Module, Module.module_id == Lesson.module_id)
            .where(Module.course_id == course_id)
        )
        lesson_result = await self.session.execute(lesson_stmt)
        via_lessons = list(lesson_result.scalars().all())

        # Deduplicate
        seen: set[str] = set()
        all_comps: list[Competency] = []
        for c in direct + via_lessons:
            if c.competency_id not in seen:
                seen.add(c.competency_id)
                all_comps.append(c)
        return all_comps

    async def get_competency_coverage_report(self, course_id: str) -> dict:
        """
        Generate a competency coverage report for a course.

        Returns mapping of competency → list of claims/lessons that support it.
        """
        comps = await self.get_competencies_for_course(course_id)
        report = []
        for comp in comps:
            stmt = select(CompetencyMapping).where(
                CompetencyMapping.competency_id == comp.competency_id
            )
            res = await self.session.execute(stmt)
            mappings = res.scalars().all()
            report.append({
                "competency_id": comp.competency_id,
                "name": comp.name,
                "code": comp.code,
                "skill_level": comp.skill_level.value,
                "standard_reference": comp.industry_standard_reference,
                "supporting_claims": [m.claim_id for m in mappings if m.claim_id],
                "supporting_lessons": [m.lesson_id for m in mappings if m.lesson_id],
            })
        return {"course_id": course_id, "competencies": report}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _create_mapping(
        self,
        *,
        competency_id: str,
        claim_id: str | None = None,
        lesson_id: str | None = None,
        course_id: str | None = None,
        concept_id: str | None = None,
        alignment_notes: str | None = None,
    ) -> CompetencyMapping:
        mapping = CompetencyMapping(
            competency_id=competency_id,
            claim_id=claim_id,
            lesson_id=lesson_id,
            course_id=course_id,
            concept_id=concept_id,
            alignment_notes=alignment_notes,
        )
        self.session.add(mapping)
        await self.session.flush()
        return mapping

    async def _find_standard_by_name(self, name: str) -> Optional[Standard]:
        stmt = select(Standard).where(Standard.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
