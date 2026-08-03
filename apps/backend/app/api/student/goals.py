from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_student
from app.database import get_db
from app.models.user import User
from app.schemas.student.goal import (
    GoalCreate,
    GoalResponse,
    GoalResultRecordPublic,
    GoalUpdate,
    PreviewKpRequest,
    PreviewKpResponse,
)
from app.services.learning import goal_service, learning_map, result_records
from app.services.learning.chapter_kp import (
    expand_learned_scope_to_kp_ids,
    prior_grade_stages,
)

router = APIRouter(prefix="/goals")


@router.get("", response_model=List[GoalResponse])
async def list_goals(
    status: Optional[str] = Query("active", description="active / archived / 空=全部"),
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    st = status if status else None
    if st == "all":
        st = None
    return await goal_service.list_goals(db, user.id, status=st)


@router.get("/primary", response_model=Optional[GoalResponse])
async def get_primary_goal(
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await goal_service.get_primary(db, user.id)


@router.post("/preview-kp", response_model=PreviewKpResponse)
async def preview_kp(
    body: PreviewKpRequest,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    ids = list(dict.fromkeys(body.chapter_ids or []))
    await goal_service.validate_chapter_ids(db, ids)
    priors = prior_grade_stages(body.grade_stage)
    kp_ids = await expand_learned_scope_to_kp_ids(db, body.grade_stage, ids)
    return PreviewKpResponse(
        chapter_count=len(ids),
        kp_count=len(kp_ids),
        kp_ids=kp_ids,
        prior_stages_included=priors,
    )


@router.get("/{goal_id}/result-records", response_model=List[GoalResultRecordPublic])
async def list_goal_result_records(
    goal_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    await goal_service.get_owned_goal(db, goal_id, user.id)
    return await result_records.list_for_goal(db, user.id, goal_id)


@router.get("/{goal_id}/learning-map")
async def get_learning_map(
    goal_id: int,
    response: Response,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    return await learning_map.build_learning_map(db, user.id, goal_id)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    goal = await goal_service.get_owned_goal(db, goal_id, user.id)
    recent = await result_records.list_for_goal(db, user.id, goal_id, limit=6)
    return goal_service.to_response(
        goal, await goal_service.get_chapter_ids(db, goal.id), recent=recent
    )


@router.post("", response_model=GoalResponse)
async def create_goal(
    body: GoalCreate,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await goal_service.create_goal(db, user.id, body)


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: int,
    body: GoalUpdate,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await goal_service.update_goal(db, user.id, goal_id, body)


@router.post("/{goal_id}/set-primary", response_model=GoalResponse)
async def set_primary(
    goal_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await goal_service.set_primary(db, user.id, goal_id)


@router.post("/{goal_id}/archive", response_model=GoalResponse)
async def archive_goal(
    goal_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await goal_service.archive_goal(db, user.id, goal_id)


@router.post("/{goal_id}/copy", response_model=GoalResponse)
async def copy_goal(
    goal_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await goal_service.copy_goal(db, user.id, goal_id)


@router.post("/{goal_id}/ack-replan", response_model=GoalResponse)
async def ack_replan(
    goal_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """关闭「建议重测/重规划」提示（正式复测流程在后续步骤接入）。"""
    goal = await goal_service.get_owned_goal(db, goal_id, user.id)
    goal.needs_replan = False
    await db.commit()
    await db.refresh(goal)
    return goal_service.to_response(goal, await goal_service.get_chapter_ids(db, goal.id))
