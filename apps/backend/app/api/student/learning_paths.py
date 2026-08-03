from typing import List, Optional

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_student
from app.database import get_db
from app.models.user import User
from app.schemas.student.learning_path import (
    LearningPathGenerateRequest,
    LearningPathPublic,
    LearningTaskUpdate,
)
from app.services.learning import path_service

router = APIRouter()


@router.post("/goals/{goal_id}/learning-path/preview", response_model=LearningPathPublic)
async def preview_learning_path(
    goal_id: int, body: LearningPathGenerateRequest, response: Response,
    user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return await path_service.build_preview(db, user.id, goal_id, body)


@router.post("/goals/{goal_id}/learning-path/generate", response_model=LearningPathPublic)
async def generate_learning_path(
    goal_id: int, body: LearningPathGenerateRequest,
    user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db),
):
    return await path_service.generate(db, user.id, goal_id, body)


@router.get("/goals/{goal_id}/learning-path/current", response_model=Optional[LearningPathPublic])
async def get_current_learning_path(
    goal_id: int, response: Response,
    user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return await path_service.get_current(db, user.id, goal_id)


@router.get("/learning-paths/{path_id}", response_model=LearningPathPublic)
async def get_learning_path(
    path_id: int, user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await path_service.get_detail(db, user.id, path_id)


@router.post("/learning-paths/{path_id}/activate", response_model=LearningPathPublic)
async def activate_learning_path(
    path_id: int, user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await path_service.activate(db, user.id, path_id)


@router.get("/goals/{goal_id}/learning-paths", response_model=List[LearningPathPublic])
async def list_learning_path_versions(
    goal_id: int, user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await path_service.list_versions(db, user.id, goal_id)


@router.post("/goals/{goal_id}/learning-path/replan", response_model=LearningPathPublic)
async def replan_learning_path(
    goal_id: int, body: LearningPathGenerateRequest,
    user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db),
):
    return await path_service.replan(db, user.id, goal_id, body)


@router.patch("/learning-tasks/{task_id}", response_model=LearningPathPublic)
async def update_learning_task(
    task_id: int, body: LearningTaskUpdate,
    user: User = Depends(get_current_student), db: AsyncSession = Depends(get_db),
):
    return await path_service.update_task(db, user.id, task_id, body)
