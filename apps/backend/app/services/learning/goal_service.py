from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import TextbookChapter
from app.models.student.goal import GoalLearnedChapter, LearningGoal
from app.schemas.student.goal import GoalCreate, GoalResponse, GoalResultRecordPublic, GoalUpdate
from app.services.learning.chapter_kp import expand_learned_scope_to_kp_ids
from app.services.learning import result_records


def default_title(exam_type: str, subject: str, target_score: float) -> str:
    return "{}{}冲{}".format(exam_type, subject, int(target_score) if target_score == int(target_score) else target_score)


async def get_owned_goal(db: AsyncSession, goal_id: int, user_id: int) -> LearningGoal:
    goal = (
        await db.execute(
            select(LearningGoal).where(
                LearningGoal.id == goal_id,
                LearningGoal.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if goal is None:
        # 统一 404，防枚举
        raise HTTPException(status_code=404, detail="目标不存在")
    return goal


async def get_chapter_ids(db: AsyncSession, goal_id: int) -> List[int]:
    rows = (
        await db.execute(
            select(GoalLearnedChapter.chapter_id).where(GoalLearnedChapter.goal_id == goal_id)
        )
    ).scalars().all()
    return list(rows)


async def validate_chapter_ids(db: AsyncSession, chapter_ids: List[int]) -> List[int]:
    if not chapter_ids:
        return []
    uniq = list(dict.fromkeys(chapter_ids))
    found = (
        await db.execute(select(TextbookChapter.id).where(TextbookChapter.id.in_(uniq)))
    ).scalars().all()
    found_set = set(found)
    missing = [i for i in uniq if i not in found_set]
    if missing:
        raise HTTPException(status_code=400, detail="部分章节不存在：{}".format(missing[:5]))
    return uniq


async def replace_learned_chapters(
    db: AsyncSession, goal: LearningGoal, chapter_ids: List[int]
) -> List[str]:
    ids = await validate_chapter_ids(db, chapter_ids)
    # 必须先落库删除再插入，否则同 (goal_id, chapter_id) 在同一次 flush 会撞 UNIQUE
    await db.execute(
        delete(GoalLearnedChapter).where(GoalLearnedChapter.goal_id == goal.id)
    )
    await db.flush()
    for cid in ids:
        db.add(GoalLearnedChapter(goal_id=goal.id, chapter_id=cid))
    # 本册勾选章 + 此前各册（七/八年级等）全部章 → 知识点
    kp_ids = await expand_learned_scope_to_kp_ids(db, goal.grade_stage, ids)
    goal.learned_kp_ids = kp_ids
    return kp_ids


async def clear_primary(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(LearningGoal)
        .where(LearningGoal.user_id == user_id, LearningGoal.is_primary.is_(True))
        .values(is_primary=False)
    )


def normalize_mastery_status(value: Optional[str]) -> str:
    if value in ("pending_test", "assessed"):
        return value
    return "pending_test"


def to_response(
    goal: LearningGoal,
    chapter_ids: List[int],
    recent: Optional[List[GoalResultRecordPublic]] = None,
) -> GoalResponse:
    kp_ids = list(goal.learned_kp_ids or [])
    return GoalResponse(
        id=goal.id,
        user_id=goal.user_id,
        title=goal.title,
        exam_type=goal.exam_type,
        subject=goal.subject,
        target_score=goal.target_score,
        current_score_estimate=goal.current_score_estimate,
        grade_stage=goal.grade_stage,
        exam_date=goal.exam_date,
        daily_study_minutes=goal.daily_study_minutes,
        region=goal.region,
        status=goal.status,
        is_primary=bool(goal.is_primary),
        mastery_status=normalize_mastery_status(getattr(goal, "mastery_status", None)),
        learned_chapter_ids=chapter_ids,
        learned_kp_ids=kp_ids,
        learned_chapter_count=len(chapter_ids),
        learned_kp_count=len(kp_ids),
        needs_replan=bool(goal.needs_replan),
        recent_results=list(recent or []),
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


async def create_goal(db: AsyncSession, user_id: int, body: GoalCreate) -> GoalResponse:
    title = (body.title or "").strip() or default_title(body.exam_type, body.subject, body.target_score)
    has_any = (
        await db.execute(
            select(LearningGoal.id).where(
                LearningGoal.user_id == user_id,
                LearningGoal.status == "active",
            ).limit(1)
        )
    ).scalar_one_or_none()
    set_primary = body.set_as_primary or has_any is None
    if set_primary:
        await clear_primary(db, user_id)

    goal = LearningGoal(
        user_id=user_id,
        title=title,
        exam_type=body.exam_type,
        subject=body.subject,
        target_score=body.target_score,
        current_score_estimate=body.current_score_estimate,
        grade_stage=body.grade_stage,
        exam_date=body.exam_date,
        daily_study_minutes=body.daily_study_minutes,
        region=body.region,
        status="active",
        is_primary=set_primary,
        mastery_status=normalize_mastery_status(body.mastery_status),
        needs_replan=False,
        learned_kp_ids=[],
    )
    db.add(goal)
    await db.flush()
    await replace_learned_chapters(db, goal, body.learned_chapter_ids)
    await db.commit()
    await db.refresh(goal)
    return to_response(goal, await get_chapter_ids(db, goal.id))


async def update_goal(
    db: AsyncSession, user_id: int, goal_id: int, body: GoalUpdate
) -> GoalResponse:
    goal = await get_owned_goal(db, goal_id, user_id)
    if goal.status == "archived":
        raise HTTPException(status_code=400, detail="已归档目标不可编辑，请先复制或新建")

    data = body.model_dump(exclude_unset=True)
    chapter_ids_in = data.pop("learned_chapter_ids", None)
    if "mastery_status" in data:
        data["mastery_status"] = normalize_mastery_status(data.get("mastery_status"))
    score_or_chapters_changed = False

    if "target_score" in data and data["target_score"] != goal.target_score:
        score_or_chapters_changed = True
    for k, v in data.items():
        setattr(goal, k, v)

    if chapter_ids_in is not None:
        old_ids = set(await get_chapter_ids(db, goal.id))
        new_ids = set(await validate_chapter_ids(db, chapter_ids_in))
        if old_ids != new_ids:
            score_or_chapters_changed = True
        await replace_learned_chapters(db, goal, chapter_ids_in)

    if score_or_chapters_changed:
        goal.needs_replan = True

    if not (goal.title or "").strip():
        goal.title = default_title(goal.exam_type, goal.subject, goal.target_score)

    await db.commit()
    await db.refresh(goal)
    return to_response(goal, await get_chapter_ids(db, goal.id))


async def list_goals(
    db: AsyncSession, user_id: int, status: Optional[str] = "active"
) -> List[GoalResponse]:
    q = select(LearningGoal).where(LearningGoal.user_id == user_id)
    if status:
        q = q.where(LearningGoal.status == status)
    q = q.order_by(LearningGoal.is_primary.desc(), LearningGoal.updated_at.desc())
    goals = (await db.execute(q)).scalars().all()
    records_map = await result_records.list_for_goals(
        db, user_id, [g.id for g in goals], limit_per_goal=6
    )
    out = []
    for g in goals:
        out.append(
            to_response(
                g,
                await get_chapter_ids(db, g.id),
                recent=records_map.get(g.id, []),
            )
        )
    return out


async def set_primary(db: AsyncSession, user_id: int, goal_id: int) -> GoalResponse:
    goal = await get_owned_goal(db, goal_id, user_id)
    if goal.status != "active":
        raise HTTPException(status_code=400, detail="只能将进行中的目标设为主目标")
    await clear_primary(db, user_id)
    goal.is_primary = True
    await db.commit()
    await db.refresh(goal)
    return to_response(goal, await get_chapter_ids(db, goal.id))


async def archive_goal(db: AsyncSession, user_id: int, goal_id: int) -> GoalResponse:
    goal = await get_owned_goal(db, goal_id, user_id)
    was_primary = goal.is_primary
    goal.status = "archived"
    goal.is_primary = False
    await db.flush()
    if was_primary:
        nxt = (
            await db.execute(
                select(LearningGoal)
                .where(
                    LearningGoal.user_id == user_id,
                    LearningGoal.status == "active",
                )
                .order_by(LearningGoal.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if nxt:
            nxt.is_primary = True
    await db.commit()
    await db.refresh(goal)
    return to_response(goal, await get_chapter_ids(db, goal.id))


async def copy_goal(db: AsyncSession, user_id: int, goal_id: int) -> GoalResponse:
    src = await get_owned_goal(db, goal_id, user_id)
    chapter_ids = await get_chapter_ids(db, src.id)
    body = GoalCreate(
        exam_type=src.exam_type,
        subject=src.subject,
        target_score=src.target_score,
        current_score_estimate=src.current_score_estimate,
        grade_stage=src.grade_stage,
        exam_date=src.exam_date,
        daily_study_minutes=src.daily_study_minutes,
        region=src.region,
        learned_chapter_ids=chapter_ids,
        mastery_status=normalize_mastery_status(getattr(src, "mastery_status", None)),
        title=(src.title or "目标") + "（副本）",
        set_as_primary=False,
    )
    return await create_goal(db, user_id, body)


async def get_primary(db: AsyncSession, user_id: int) -> Optional[GoalResponse]:
    goal = (
        await db.execute(
            select(LearningGoal).where(
                LearningGoal.user_id == user_id,
                LearningGoal.is_primary.is_(True),
                LearningGoal.status == "active",
            )
        )
    ).scalar_one_or_none()
    if goal is None:
        return None
    return to_response(goal, await get_chapter_ids(db, goal.id))
