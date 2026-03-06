"""
Universal Academy Engine — Curriculum Builder

Assembles verified knowledge claims into structured courses, modules, and
lessons.

Governance invariant (enforced here):
  EVERY lesson MUST reference at least one verified claim.  The builder will
  raise a ``CurriculumError`` if an attempt is made to create a lesson with
  no claim references or with non-verified claims.
"""

from __future__ import annotations

import logging
import re
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.schemas.models import (
    Claim, ClaimStatus, Course, Lesson, LessonClaim, Module, PublishingState, QuizQuestion
)

logger = logging.getLogger(__name__)

_CLAIM_REF_RE = re.compile(r"\[CLM\d{6}\]")


class CurriculumError(Exception):
    """Raised when curriculum assembly violates governance rules."""


class CurriculumBuilder:
    """
    High-level API for building UAE curriculum from verified claims.

    All knowledge assembled here is traceable to source documents through
    the claim ledger.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Course management
    # ------------------------------------------------------------------

    async def create_course(
        self,
        *,
        title: str,
        academy_node: str,
        description: str | None = None,
        version: str = "1.0",
        learning_objectives: list[str] | None = None,
        prerequisite_course_ids: list[str] | None = None,
    ) -> Course:
        """Create a new course scaffold."""
        course = Course(
            title=title,
            academy_node=academy_node,
            description=description,
            version=version,
            learning_objectives=learning_objectives or [],
            prerequisite_course_ids=prerequisite_course_ids or [],
        )
        self.session.add(course)
        await self.session.flush()
        logger.info("Created course %r (%s) for %s", title, course.course_id, academy_node)
        return course

    async def retrieve_course(self, course_id: str) -> Course:
        stmt = select(Course).where(Course.course_id == course_id)
        result = await self.session.execute(stmt)
        course = result.scalar_one_or_none()
        if course is None:
            raise CurriculumError(f"Course not found: {course_id!r}")
        return course

    async def list_courses(
        self,
        *,
        academy_node: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Course]:
        stmt = select(Course)
        if academy_node:
            stmt = stmt.where(Course.academy_node == academy_node)
        stmt = stmt.order_by(Course.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def publish_course(self, course_id: str) -> Course:
        """Mark a course as published after verifying all lessons have claim refs."""
        course = await self.retrieve_course(course_id)
        await self._assert_course_integrity(course)
        course.is_published = True
        course.publishing_state = PublishingState.PUBLISHED
        from datetime import datetime
        course.published_at = datetime.utcnow()
        await self.session.flush()
        logger.info("Published course %s", course_id)
        return course

    async def approve_course(
        self, course_id: str, *, approved_by: str
    ) -> Course:
        """
        Advance a course from VERIFIED → APPROVED state.

        Required by nodes whose governance policy mandates human sign-off
        before publication (``require_approval_to_publish = True``).
        """
        from datetime import datetime
        course = await self.retrieve_course(course_id)
        if course.publishing_state not in (
            PublishingState.DRAFT, PublishingState.VERIFIED
        ):
            raise CurriculumError(
                f"Course is in state {course.publishing_state.value!r} and cannot be approved."
            )
        await self._assert_course_integrity(course)
        course.publishing_state = PublishingState.APPROVED
        course.approved_by = approved_by
        course.approved_at = datetime.utcnow()
        await self.session.flush()
        logger.info("Course %s approved by %s", course_id, approved_by)
        return course

    async def supersede_course(
        self, old_course_id: str, new_course_id: str
    ) -> Course:
        """Mark old_course as superseded by new_course."""
        old_course = await self.retrieve_course(old_course_id)
        new_course = await self.retrieve_course(new_course_id)
        old_course.publishing_state = PublishingState.SUPERSEDED
        old_course.superseded_by_id = new_course_id
        await self.session.flush()
        logger.info("Course %s superseded by %s", old_course_id, new_course_id)
        return old_course

    async def deprecate_course(self, course_id: str) -> Course:
        """Deprecate a course — it remains readable but is no longer recommended."""
        course = await self.retrieve_course(course_id)
        course.publishing_state = PublishingState.DEPRECATED
        course.is_published = False
        await self.session.flush()
        return course

    async def archive_course(self, course_id: str) -> Course:
        """Archive a course — preserved but fully inactive."""
        course = await self.retrieve_course(course_id)
        course.publishing_state = PublishingState.ARCHIVED
        course.is_published = False
        await self.session.flush()
        return course

    # ------------------------------------------------------------------
    # Module management
    # ------------------------------------------------------------------

    async def add_module(
        self,
        course_id: str,
        *,
        title: str,
        description: str | None = None,
        order: int | None = None,
        estimated_minutes: int | None = None,
    ) -> Module:
        """Add a module to an existing course."""
        course = await self.retrieve_course(course_id)

        if order is None:
            existing = await self._count_modules(course_id)
            order = existing + 1

        module = Module(
            course_id=course_id,
            title=title,
            description=description,
            order=order,
            estimated_minutes=estimated_minutes,
        )
        self.session.add(module)
        await self.session.flush()
        logger.info("Added module %r to course %s", title, course_id)
        return module

    # ------------------------------------------------------------------
    # Lesson management
    # ------------------------------------------------------------------

    async def add_lesson(
        self,
        module_id: str,
        *,
        title: str,
        content: str,
        claim_ids: list[str],
        order: int | None = None,
        estimated_minutes: int | None = None,
    ) -> Lesson:
        """
        Add a lesson to a module.

        Args:
            module_id: Parent module.
            title: Lesson title.
            content: Lesson body text.  Must contain at least one [CLMxxxxxx]
                     inline reference.
            claim_ids: List of claim IDs that back the lesson content.
                       All claims must be in ``verified`` status.
            order: Display order within the module.
            estimated_minutes: Reading/study time estimate.

        Raises:
            CurriculumError: If ``claim_ids`` is empty or any claim is not verified.
        """
        if not claim_ids:
            raise CurriculumError(
                "A lesson must reference at least one verified claim.  "
                "Provide claim_ids."
            )

        verified_claims = await self._load_and_validate_claims(claim_ids)

        if order is None:
            order = (await self._count_lessons(module_id)) + 1

        lesson = Lesson(
            module_id=module_id,
            title=title,
            content=content,
            order=order,
            estimated_minutes=estimated_minutes,
        )
        self.session.add(lesson)
        await self.session.flush()

        for claim in verified_claims:
            inline_ref = f"[{claim.claim_number}]"
            lc = LessonClaim(
                lesson_id=lesson.lesson_id,
                claim_id=claim.claim_id,
                inline_reference=inline_ref,
            )
            self.session.add(lc)

        await self.session.flush()
        logger.info(
            "Added lesson %r to module %s with %d claim references",
            title, module_id, len(verified_claims),
        )
        return lesson

    async def add_quiz_question(
        self,
        lesson_id: str,
        *,
        question_text: str,
        correct_answer: str,
        answer_options: list[str] | None = None,
        claim_id: str | None = None,
        explanation: str | None = None,
        difficulty: str = "medium",
    ) -> QuizQuestion:
        """Add a quiz question to a lesson."""
        q = QuizQuestion(
            lesson_id=lesson_id,
            claim_id=claim_id,
            question_text=question_text,
            correct_answer=correct_answer,
            answer_options=answer_options or [],
            explanation=explanation,
            difficulty=difficulty,
        )
        self.session.add(q)
        await self.session.flush()
        return q

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _load_and_validate_claims(self, claim_ids: list[str]) -> list[Claim]:
        claims = []
        for cid in claim_ids:
            stmt = select(Claim).where(Claim.claim_id == cid)
            result = await self.session.execute(stmt)
            claim = result.scalar_one_or_none()
            if claim is None:
                raise CurriculumError(f"Claim not found: {cid!r}")
            if claim.status != ClaimStatus.VERIFIED:
                raise CurriculumError(
                    f"Claim {cid!r} (number={claim.claim_number!r}) has status "
                    f"{claim.status!r}.  Only 'verified' claims may be referenced "
                    f"in lessons."
                )
            claims.append(claim)
        return claims

    async def _count_modules(self, course_id: str) -> int:
        from sqlalchemy import func
        stmt = select(func.count(Module.module_id)).where(Module.course_id == course_id)
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def _count_lessons(self, module_id: str) -> int:
        from sqlalchemy import func
        stmt = select(func.count(Lesson.lesson_id)).where(Lesson.module_id == module_id)
        result = await self.session.execute(stmt)
        return result.scalar_one() or 0

    async def _assert_course_integrity(self, course: Course) -> None:
        """Ensure every lesson in the course has verified claim references."""
        stmt = select(Module).where(Module.course_id == course.course_id)
        result = await self.session.execute(stmt)
        modules = result.scalars().all()

        for module in modules:
            stmt = select(Lesson).where(Lesson.module_id == module.module_id)
            result = await self.session.execute(stmt)
            lessons = result.scalars().all()

            for lesson in lessons:
                stmt = select(LessonClaim).where(LessonClaim.lesson_id == lesson.lesson_id)
                result = await self.session.execute(stmt)
                refs = result.scalars().all()
                if not refs:
                    raise CurriculumError(
                        f"Lesson {lesson.lesson_id!r} ({lesson.title!r}) has no "
                        f"claim references.  All lessons must reference verified claims."
                    )
