"""学习目标结果记录：组卷记录（每目标一条，动态汇总套数）+ 多次批改完成。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student.goal import GoalResultRecord
from app.models.student.test_paper import TestPaper
from app.schemas.student.goal import GoalResultRecordPublic

# assembled = 首次「开始诊断测评」；submitted = 历史误把交卷写成组卷类记录
_ASSEMBLED_LIKE_EVENTS = ("assembled", "submitted")
_ASSEMBLED_LIKE_TITLES = ("组卷记录", "组卷完成", "已交卷")
_TESTED_STATUSES = ("submitted", "grading", "graded")
_TESTING_STATUSES = ("in_progress",)
_NOT_TESTED_STATUSES = ("assembled",)


def to_public(row: GoalResultRecord) -> GoalResultRecordPublic:
    return GoalResultRecordPublic(
        id=row.id,
        goal_id=row.goal_id,
        test_paper_id=row.test_paper_id,
        event_type=row.event_type,
        title=row.title,
        summary=row.summary,
        earned_score=row.earned_score,
        total_score=row.total_score,
        correct_count=row.correct_count,
        total_count=row.total_count,
        created_at=row.created_at,
    )


def _is_assembled_like(row: GoalResultRecord) -> bool:
    if row.event_type in _ASSEMBLED_LIKE_EVENTS:
        return True
    return (row.title or "") in _ASSEMBLED_LIKE_TITLES


def _collapse_assembled(rows: Sequence[GoalResultRecord]) -> List[GoalResultRecord]:
    """每个目标最多保留一条「组卷记录」（最早那条），批改完成可多条。"""
    assembled = [r for r in rows if _is_assembled_like(r)]
    others = [r for r in rows if not _is_assembled_like(r)]
    keep: List[GoalResultRecord] = []
    if assembled:
        keep.append(min(assembled, key=lambda r: (r.created_at is None, r.created_at, r.id)))
    keep.extend(others)
    keep.sort(key=lambda r: (r.created_at is None, r.created_at, r.id), reverse=True)
    return keep


def format_paper_stats_summary(
    total: int, not_tested: int, testing: int, tested: int
) -> str:
    return (
        f"共生成 {total} 套试卷：未测试 {not_tested} 套，"
        f"测试中 {testing} 套，已测试 {tested} 套。"
    )


async def count_paper_stats(
    db: AsyncSession, *, user_id: int, goal_id: int
) -> Tuple[int, int, int, int]:
    """返回 (总套数, 未测试, 测试中, 已测试)。"""
    rows = (
        await db.execute(
            select(TestPaper.status, func.count(TestPaper.id))
            .where(TestPaper.user_id == user_id, TestPaper.goal_id == goal_id)
            .group_by(TestPaper.status)
        )
    ).all()
    by_status = {str(status): int(cnt) for status, cnt in rows}
    not_tested = sum(by_status.get(s, 0) for s in _NOT_TESTED_STATUSES)
    testing = sum(by_status.get(s, 0) for s in _TESTING_STATUSES)
    tested = sum(by_status.get(s, 0) for s in _TESTED_STATUSES)
    total = sum(by_status.values())
    known = not_tested + testing + tested
    if total > known:
        not_tested += total - known
    return total, not_tested, testing, tested


async def refresh_assembled_summary(
    db: AsyncSession, *, user_id: int, goal_id: int
) -> Optional[GoalResultRecord]:
    """按当前历史组卷套数刷新「组卷记录」文案。"""
    row = (
        await db.execute(
            select(GoalResultRecord)
            .where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.goal_id == goal_id,
                or_(
                    GoalResultRecord.event_type.in_(list(_ASSEMBLED_LIKE_EVENTS)),
                    GoalResultRecord.title.in_(list(_ASSEMBLED_LIKE_TITLES)),
                ),
            )
            .order_by(GoalResultRecord.created_at.asc(), GoalResultRecord.id.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    total, not_tested, testing, tested = await count_paper_stats(
        db, user_id=user_id, goal_id=goal_id
    )
    row.event_type = "assembled"
    row.title = "组卷记录"
    row.summary = format_paper_stats_summary(total, not_tested, testing, tested)
    row.total_count = total
    row.correct_count = tested
    row.meta = {
        **(row.meta or {}),
        "paper_total": total,
        "paper_not_tested": not_tested,
        "paper_testing": testing,
        "paper_tested": tested,
    }
    await db.flush()
    return row


_TAKING_EVENT = "taking"
_TAKING_TITLE = "答题中"


async def clear_taking_for_paper(
    db: AsyncSession, *, user_id: int, test_paper_id: int
) -> int:
    """交卷后清除该卷的「答题中」记录。"""
    result = await db.execute(
        delete(GoalResultRecord).where(
            GoalResultRecord.user_id == user_id,
            GoalResultRecord.test_paper_id == test_paper_id,
            or_(
                GoalResultRecord.event_type == _TAKING_EVENT,
                GoalResultRecord.title == _TAKING_TITLE,
            ),
        )
    )
    await db.flush()
    return int(result.rowcount or 0)


async def upsert_taking_record(
    db: AsyncSession,
    *,
    goal_id: int,
    user_id: int,
    test_paper_id: int,
    paper_title: str,
    answered_count: int,
    total_count: int,
    total_score: float,
) -> GoalResultRecord:
    """保存进度时写入/刷新「答题中」（每卷只保留一条，并更新为最新）。"""
    title = paper_title or f"试卷 #{test_paper_id}"
    summary = f"「{title}」答题中，已答 {answered_count}/{total_count} 题。"
    existing = (
        await db.execute(
            select(GoalResultRecord)
            .where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.test_paper_id == test_paper_id,
                or_(
                    GoalResultRecord.event_type == _TAKING_EVENT,
                    GoalResultRecord.title == _TAKING_TITLE,
                ),
            )
            .order_by(GoalResultRecord.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        # 去掉同卷多余旧记录
        await db.execute(
            delete(GoalResultRecord).where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.test_paper_id == test_paper_id,
                or_(
                    GoalResultRecord.event_type == _TAKING_EVENT,
                    GoalResultRecord.title == _TAKING_TITLE,
                ),
                GoalResultRecord.id != existing.id,
            )
        )
        existing.event_type = _TAKING_EVENT
        existing.title = _TAKING_TITLE
        existing.summary = summary
        existing.total_score = total_score
        existing.correct_count = answered_count
        existing.total_count = total_count
        existing.meta = {**(existing.meta or {}), "source": "save_progress"}
        await db.execute(
            update(GoalResultRecord)
            .where(GoalResultRecord.id == existing.id)
            .values(created_at=func.now())
        )
        await db.flush()
        await db.refresh(existing)
        return existing
    return await add_record(
        db,
        goal_id=goal_id,
        user_id=user_id,
        test_paper_id=test_paper_id,
        event_type=_TAKING_EVENT,
        title=_TAKING_TITLE,
        summary=summary,
        total_score=total_score,
        correct_count=answered_count,
        total_count=total_count,
        meta={"source": "save_progress"},
    )


async def add_record(
    db: AsyncSession,
    *,
    goal_id: int,
    user_id: int,
    test_paper_id: Optional[int],
    event_type: str,
    title: str,
    summary: Optional[str] = None,
    earned_score: Optional[float] = None,
    total_score: Optional[float] = None,
    correct_count: Optional[int] = None,
    total_count: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> GoalResultRecord:
    row = GoalResultRecord(
        goal_id=goal_id,
        user_id=user_id,
        test_paper_id=test_paper_id,
        event_type=event_type,
        title=title,
        summary=summary,
        earned_score=earned_score,
        total_score=total_score,
        correct_count=correct_count,
        total_count=total_count,
        meta=meta,
    )
    db.add(row)
    await db.flush()
    return row


async def has_assembled_record(db: AsyncSession, user_id: int, goal_id: int) -> bool:
    row = (
        await db.execute(
            select(GoalResultRecord.id)
            .where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.goal_id == goal_id,
                or_(
                    GoalResultRecord.event_type.in_(list(_ASSEMBLED_LIKE_EVENTS)),
                    GoalResultRecord.title.in_(list(_ASSEMBLED_LIKE_TITLES)),
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def ensure_assembled_once(
    db: AsyncSession,
    *,
    goal_id: int,
    user_id: int,
    test_paper_id: int,
    paper_title: str = "",
    total_score: float = 0,
    total_count: int = 0,
) -> Optional[GoalResultRecord]:
    """首次「开始诊断测评」写入唯一的「组卷记录」；已有则只刷新套数汇总。"""
    await prune_extra_assembled(db, user_id=user_id, goal_id=goal_id)
    if not await has_assembled_record(db, user_id, goal_id):
        total, not_tested, testing, tested = await count_paper_stats(
            db, user_id=user_id, goal_id=goal_id
        )
        await add_record(
            db,
            goal_id=goal_id,
            user_id=user_id,
            test_paper_id=test_paper_id,
            event_type="assembled",
            title="组卷记录",
            summary=format_paper_stats_summary(total, not_tested, testing, tested),
            total_score=total_score,
            total_count=total,
            correct_count=tested,
            meta={
                "source": "first_assemble",
                "paper_total": total,
                "paper_not_tested": not_tested,
                "paper_testing": testing,
                "paper_tested": tested,
                "first_paper_title": paper_title or None,
            },
        )
    return await refresh_assembled_summary(db, user_id=user_id, goal_id=goal_id)


async def prune_extra_assembled(
    db: AsyncSession, *, user_id: int, goal_id: int
) -> int:
    """删除同一目标下多余的组卷类记录，只留最早一条并规范标题。"""
    rows = (
        await db.execute(
            select(GoalResultRecord)
            .where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.goal_id == goal_id,
                or_(
                    GoalResultRecord.event_type.in_(list(_ASSEMBLED_LIKE_EVENTS)),
                    GoalResultRecord.title.in_(list(_ASSEMBLED_LIKE_TITLES)),
                ),
            )
            .order_by(GoalResultRecord.created_at.asc(), GoalResultRecord.id.asc())
        )
    ).scalars().all()
    if not rows:
        return 0
    keep = rows[0]
    changed = 0
    if keep.event_type != "assembled" or keep.title != "组卷记录":
        keep.event_type = "assembled"
        keep.title = "组卷记录"
        changed = 1
    if len(rows) > 1:
        drop_ids = [r.id for r in rows[1:]]
        await db.execute(delete(GoalResultRecord).where(GoalResultRecord.id.in_(drop_ids)))
        changed += len(drop_ids)
    if changed:
        await db.flush()
    return changed


async def _enrich_assembled_summaries(
    db: AsyncSession, user_id: int, goal_ids: List[int]
) -> None:
    for gid in goal_ids:
        await prune_extra_assembled(db, user_id=user_id, goal_id=gid)
        await refresh_assembled_summary(db, user_id=user_id, goal_id=gid)


def _is_result_feed_item(row: GoalResultRecord) -> bool:
    """结果记录展示：批改完成 + 答题中；不含组卷记录。"""
    if _is_assembled_like(row):
        return False
    if row.event_type in ("graded", _TAKING_EVENT):
        return True
    if (row.title or "") in ("批改完成", _TAKING_TITLE):
        return True
    return False


async def list_for_goals(
    db: AsyncSession, user_id: int, goal_ids: List[int], limit_per_goal: int = 8
) -> Dict[int, List[GoalResultRecordPublic]]:
    """结果记录：批改完成 + 答题中。"""
    if not goal_ids:
        return {}
    rows = (
        await db.execute(
            select(GoalResultRecord)
            .where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.goal_id.in_(goal_ids),
            )
            .order_by(GoalResultRecord.created_at.desc())
        )
    ).scalars().all()
    by_goal: Dict[int, List[GoalResultRecord]] = {gid: [] for gid in goal_ids}
    for row in rows:
        if not _is_result_feed_item(row):
            continue
        by_goal.setdefault(row.goal_id, []).append(row)

    out: Dict[int, List[GoalResultRecordPublic]] = {gid: [] for gid in goal_ids}
    for gid, bucket in by_goal.items():
        out[gid] = [to_public(r) for r in bucket[:limit_per_goal]]
    return out


async def list_for_goal(
    db: AsyncSession, user_id: int, goal_id: int, limit: int = 20
) -> List[GoalResultRecordPublic]:
    rows = (
        await db.execute(
            select(GoalResultRecord)
            .where(
                GoalResultRecord.user_id == user_id,
                GoalResultRecord.goal_id == goal_id,
            )
            .order_by(GoalResultRecord.created_at.desc())
        )
    ).scalars().all()
    feed = [r for r in rows if _is_result_feed_item(r)]
    return [to_public(r) for r in feed[:limit]]
