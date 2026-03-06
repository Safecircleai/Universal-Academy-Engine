"""
UAE API — Curriculum Routes

POST   /courses                          Create a course
GET    /courses                          List courses
GET    /courses/{course_id}              Retrieve a course with modules/lessons
POST   /courses/{course_id}/publish      Publish a course
POST   /courses/{course_id}/modules      Add a module
POST   /modules/{module_id}/lessons      Add a lesson

POST   /agents/curriculum                Run Curriculum Architect agent
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from agents.curriculum_architect import CurriculumArchitectAgent
from api.models.requests import (
    AddLessonRequest, AddModuleRequest, CreateCourseRequest, RunAgentRequest
)
from api.models.responses import CourseResponse, LessonResponse, ModuleResponse
from core.curriculum_engine.curriculum_builder import CurriculumBuilder, CurriculumError
from database.connection import get_async_session
from database.schemas.models import Course, Lesson, Module

router = APIRouter(tags=["Curriculum"])


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

@router.post("/courses", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CreateCourseRequest,
    session: AsyncSession = Depends(get_async_session),
):
    builder = CurriculumBuilder(session)
    course = await builder.create_course(
        title=body.title,
        academy_node=body.academy_node,
        description=body.description,
        version=body.version,
        learning_objectives=body.learning_objectives,
        prerequisite_course_ids=body.prerequisite_course_ids,
    )
    return _course_to_response(course)


@router.get("/courses", response_model=List[CourseResponse])
async def list_courses(
    academy_node: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    builder = CurriculumBuilder(session)
    courses = await builder.list_courses(
        academy_node=academy_node, limit=min(limit, 200), offset=offset
    )
    return [_course_to_response(c) for c in courses]


@router.get("/courses/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    builder = CurriculumBuilder(session)
    try:
        course = await builder.retrieve_course(course_id)
    except CurriculumError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Eager-load modules and lessons
    stmt = select(Module).where(Module.course_id == course_id).order_by(Module.order)
    result = await session.execute(stmt)
    modules = result.scalars().all()

    module_responses = []
    for mod in modules:
        stmt2 = select(Lesson).where(Lesson.module_id == mod.module_id).order_by(Lesson.order)
        res2 = await session.execute(stmt2)
        lessons = res2.scalars().all()
        module_responses.append(ModuleResponse(
            module_id=mod.module_id,
            course_id=mod.course_id,
            title=mod.title,
            description=mod.description,
            order=mod.order,
            estimated_minutes=mod.estimated_minutes,
            created_at=mod.created_at,
            lessons=[LessonResponse.model_validate(l) for l in lessons],
        ))

    return CourseResponse(
        course_id=course.course_id,
        title=course.title,
        academy_node=course.academy_node,
        description=course.description,
        version=course.version,
        is_published=course.is_published,
        learning_objectives=course.learning_objectives,
        created_at=course.created_at,
        modules=module_responses,
    )


@router.post("/courses/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    builder = CurriculumBuilder(session)
    try:
        course = await builder.publish_course(course_id)
    except CurriculumError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _course_to_response(course)


# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------

@router.post("/courses/{course_id}/modules", response_model=ModuleResponse, status_code=status.HTTP_201_CREATED)
async def add_module(
    course_id: str,
    body: AddModuleRequest,
    session: AsyncSession = Depends(get_async_session),
):
    builder = CurriculumBuilder(session)
    try:
        module = await builder.add_module(
            course_id,
            title=body.title,
            description=body.description,
            order=body.order,
            estimated_minutes=body.estimated_minutes,
        )
    except CurriculumError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ModuleResponse.model_validate(module)


# ---------------------------------------------------------------------------
# Lessons
# ---------------------------------------------------------------------------

@router.post("/modules/{module_id}/lessons", response_model=LessonResponse, status_code=status.HTTP_201_CREATED)
async def add_lesson(
    module_id: str,
    body: AddLessonRequest,
    session: AsyncSession = Depends(get_async_session),
):
    builder = CurriculumBuilder(session)
    try:
        lesson = await builder.add_lesson(
            module_id,
            title=body.title,
            content=body.content,
            claim_ids=body.claim_ids,
            order=body.order,
            estimated_minutes=body.estimated_minutes,
        )
    except CurriculumError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return LessonResponse.model_validate(lesson)


# ---------------------------------------------------------------------------
# Curriculum Architect Agent
# ---------------------------------------------------------------------------

@router.post("/agents/curriculum")
async def run_curriculum_architect(
    body: RunAgentRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Run the Curriculum Architect agent to auto-build a course from verified claims."""
    agent = CurriculumArchitectAgent(session)
    try:
        result = await agent.run(body.payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _course_to_response(course: Course) -> CourseResponse:
    return CourseResponse(
        course_id=course.course_id,
        title=course.title,
        academy_node=course.academy_node,
        description=course.description,
        version=course.version,
        is_published=course.is_published,
        learning_objectives=course.learning_objectives,
        created_at=course.created_at,
        modules=[],
    )
