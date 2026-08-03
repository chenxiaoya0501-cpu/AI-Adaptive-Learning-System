import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_student
from app.database import get_db
from app.models.user import User
from app.schemas.student.course import (
    CourseCompleteRequest,
    CourseCompleteResult,
    CourseMasterySyncResult,
    CoursePublic,
    CourseTutorRequest,
    CourseTutorResponse,
    LearningCourseSummary,
)
from app.services.learning import course_service, course_tutor_service

router = APIRouter(prefix="/courses")
logger = logging.getLogger(__name__)


@router.get("", response_model=List[LearningCourseSummary])
async def list_courses(
    user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db)
):
    return await course_service.list_courses(db, user.id)


@router.get("/{path_id}/{kp_id}", response_model=CoursePublic)
async def get_course(
    path_id: int,
    kp_id: str,
    question_count: int = Query(20, ge=1, le=30),
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await course_service.get_course(db, user.id, path_id, kp_id, question_count)


@router.post("/{path_id}/{kp_id}/complete", response_model=CourseCompleteResult)
async def complete_course(
    path_id: int,
    kp_id: str,
    body: CourseCompleteRequest,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await course_service.complete_course(db, user.id, path_id, kp_id, body)


@router.post("/{path_id}/{kp_id}/sync-mastery", response_model=CourseMasterySyncResult)
async def sync_course_mastery(
    path_id: int,
    kp_id: str,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await course_service.sync_mastery(db, user.id, path_id, kp_id)


@router.post("/{path_id}/{kp_id}/tutor", response_model=CourseTutorResponse)
async def ask_course_tutor(
    path_id: int,
    kp_id: str,
    body: CourseTutorRequest,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await course_tutor_service.answer_question(
            db=db,
            user_id=user.id,
            path_id=path_id,
            kp_id=kp_id,
            question=body.question,
            history=[turn.model_dump() for turn in body.history],
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning(
            "课程实时答疑失败 user=%s path=%s kp=%s error=%s",
            user.id,
            path_id,
            kp_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail="AI助教暂时忙碌，请稍后重新提问",
        ) from exc
