"""
Curriculum Architect Agent

Responsibilities:
  1. Query verified claims for a specified domain or concept
  2. Organise claims into logical lesson groups
  3. Build module and course scaffolds
  4. Generate quiz questions from claims
  5. Enforce the no-hallucination invariant (all lessons cite verified claims)

Outputs:
  courses, modules, lessons (all with claim citations)
"""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base_agent import BaseAgent
from core.curriculum_engine.curriculum_builder import CurriculumBuilder
from database.schemas.models import Claim, ClaimStatus, Concept

logger = logging.getLogger(__name__)


class CurriculumArchitectAgent(BaseAgent):
    """
    Assembles verified claims into structured curriculum.

    The agent never invents knowledge — it only aggregates and organises
    claims that already exist in the verified claim ledger.
    """

    name = "curriculum_architect"

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self.builder = CurriculumBuilder(session)

    async def _run(self, payload: dict) -> dict:
        """
        Payload keys:
          course_title (str): Title of the course to create
          academy_node (str): Academy identifier (e.g. "cfrs_academy")
          description (str, optional)
          concept_ids (list[str], optional): Concepts to draw claims from
          source_ids (list[str], optional): Sources to draw claims from
          module_definitions (list[dict], optional): Manual module definitions
              Each dict: {"title": str, "description": str, "concept_ids": list[str]}
          learning_objectives (list[str], optional)
          claims_per_lesson (int, optional): Target claims per lesson (default 3)
          version (str, optional)
        """
        course_title = payload["course_title"]
        academy_node = payload["academy_node"]
        concept_ids: list[str] = payload.get("concept_ids", [])
        source_ids: list[str] = payload.get("source_ids", [])
        module_defs: list[dict] = payload.get("module_definitions", [])
        claims_per_lesson = int(payload.get("claims_per_lesson", 3))

        # Create course
        course = await self.builder.create_course(
            title=course_title,
            academy_node=academy_node,
            description=payload.get("description"),
            version=payload.get("version", "1.0"),
            learning_objectives=payload.get("learning_objectives", []),
        )

        modules_created = 0
        lessons_created = 0

        if module_defs:
            # Build from explicit module definitions
            for i, mod_def in enumerate(module_defs, start=1):
                mod_concept_ids = mod_def.get("concept_ids", concept_ids)
                module = await self.builder.add_module(
                    course.course_id,
                    title=mod_def["title"],
                    description=mod_def.get("description"),
                    order=i,
                )
                modules_created += 1

                # Gather verified claims for this module
                verified_claims = await self._fetch_verified_claims(
                    concept_ids=mod_concept_ids,
                    source_ids=source_ids,
                    limit=claims_per_lesson * 5,
                )

                lesson_count = await self._create_lessons_from_claims(
                    module.module_id, verified_claims, claims_per_lesson
                )
                lessons_created += lesson_count
        else:
            # Auto-generate a single module from all available claims
            module = await self.builder.add_module(
                course.course_id,
                title=f"{course_title} — Overview",
                order=1,
            )
            modules_created = 1
            verified_claims = await self._fetch_verified_claims(
                concept_ids=concept_ids,
                source_ids=source_ids,
                limit=claims_per_lesson * 10,
            )
            lessons_created = await self._create_lessons_from_claims(
                module.module_id, verified_claims, claims_per_lesson
            )

        logger.info(
            "Curriculum Architect built course %r: %d modules, %d lessons",
            course_title, modules_created, lessons_created,
        )
        return {
            "course_id": course.course_id,
            "course_title": course.title,
            "academy_node": academy_node,
            "modules_created": modules_created,
            "lessons_created": lessons_created,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_verified_claims(
        self,
        *,
        concept_ids: list[str],
        source_ids: list[str],
        limit: int,
    ) -> List[Claim]:
        stmt = select(Claim).where(Claim.status == ClaimStatus.VERIFIED)
        if concept_ids:
            stmt = stmt.where(Claim.concept_id.in_(concept_ids))
        if source_ids:
            stmt = stmt.where(Claim.source_id.in_(source_ids))
        stmt = stmt.order_by(Claim.confidence_score.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _create_lessons_from_claims(
        self,
        module_id: str,
        claims: List[Claim],
        claims_per_lesson: int,
    ) -> int:
        if not claims:
            return 0

        lesson_count = 0
        for batch_start in range(0, len(claims), claims_per_lesson):
            batch = claims[batch_start : batch_start + claims_per_lesson]
            if not batch:
                break

            lesson_num = lesson_count + 1
            title = f"Lesson {lesson_num}: {batch[0].statement[:60].rstrip('.,;')}…"

            # Build lesson content with inline claim references
            lines = []
            for claim in batch:
                lines.append(f"{claim.statement} [{claim.claim_number}]")
            content = "\n\n".join(lines)

            await self.builder.add_lesson(
                module_id,
                title=title,
                content=content,
                claim_ids=[c.claim_id for c in batch],
                order=lesson_num,
            )
            lesson_count += 1

            # Add a quiz question for the highest-confidence claim in the batch
            top = max(batch, key=lambda c: c.confidence_score)
            await self._add_quiz_from_claim(module_id, top, lesson_count)

        return lesson_count

    async def _add_quiz_from_claim(
        self, module_id: str, claim: Claim, lesson_order: int
    ) -> None:
        """Generate a simple true/false quiz question from a claim."""
        # Retrieve the lesson just created
        from database.schemas.models import Lesson
        stmt = (
            select(Lesson)
            .where(Lesson.module_id == module_id, Lesson.order == lesson_order)
        )
        result = await self.session.execute(stmt)
        lesson = result.scalar_one_or_none()
        if lesson is None:
            return

        await self.builder.add_quiz_question(
            lesson.lesson_id,
            question_text=f"True or False: {claim.statement}",
            correct_answer="True",
            answer_options=["True", "False"],
            claim_id=claim.claim_id,
            explanation=f"Source: {claim.citation_location or 'see claim ' + (claim.claim_number or claim.claim_id)}",
            difficulty="easy",
        )
