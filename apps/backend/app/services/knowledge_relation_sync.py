"""将前置依赖关系同步到知识点的 prerequisites 展示字段。"""
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint, KnowledgeRelation


async def sync_prerequisite_names(
    db: AsyncSession, target_ids: Optional[Iterable[str]] = None
) -> int:
    """按关系表重算目标知识点的依赖名称，返回发生变化的知识点数。"""
    targets: Optional[Set[str]] = (
        {str(point_id) for point_id in target_ids if point_id}
        if target_ids is not None
        else None
    )
    if targets is not None and not targets:
        return 0

    point_query = select(KnowledgePoint)
    if targets is not None:
        point_query = point_query.where(KnowledgePoint.id.in_(targets))
    target_points = (await db.execute(point_query)).scalars().all()
    if not target_points:
        return 0

    target_point_ids = {point.id for point in target_points}
    relations = (
        await db.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.relation_type == "prerequisite",
                KnowledgeRelation.to_point_id.in_(target_point_ids),
            )
        )
    ).scalars().all()
    source_ids = {relation.from_point_id for relation in relations}
    source_points = (
        (
            await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(source_ids))
            )
        )
        .scalars()
        .all()
        if source_ids
        else []
    )
    source_name_map = {
        point.id: (point.short_name or "").strip() or point.name
        for point in source_points
    }

    names_by_target: Dict[str, List[str]] = {}
    for relation in relations:
        name = source_name_map.get(relation.from_point_id)
        if name:
            names_by_target.setdefault(relation.to_point_id, []).append(name)

    changed = 0
    for point in target_points:
        names = list(dict.fromkeys(names_by_target.get(point.id, [])))
        value = "、".join(names) if names else None
        if point.prerequisites != value:
            point.prerequisites = value
            changed += 1
    await db.flush()
    return changed
