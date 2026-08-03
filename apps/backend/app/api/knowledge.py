from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, case, cast, Integer
from typing import Optional, List
from pydantic import BaseModel

from app.database import get_db
from app.models.knowledge import KnowledgePoint, KnowledgeRelation
from app.services.knowledge_relation_sync import sync_prerequisite_names
from app.models.system import UploadedFile, ExtractionTask
from app.schemas.knowledge import (
    KnowledgePointCreate, KnowledgePointUpdate, KnowledgePointResponse,
    KnowledgeRelationCreate, KnowledgeRelationResponse,
    KnowledgePointListResponse, KnowledgeStatsResponse
)

router = APIRouter()


class AnnotateRequest(BaseModel):
    textbook_file_ids: List[int]
    mode: str = "overwrite"  # overwrite | append
    point_ids: Optional[List[str]] = None


def _paren_number_sort_expr(column):
    """从 '(2) 实数' 这类文本中提取括号内序号，用于数值排序；解析失败排到后面。"""
    open_pos = func.instr(column, "(")
    close_pos = func.instr(column, ")")
    extracted = func.substr(column, open_pos + 1, close_pos - open_pos - 1)
    return case(
        (func.coalesce(open_pos, 0) <= 0, 9999),
        (func.coalesce(close_pos, 0) <= open_pos, 9999),
        else_=func.coalesce(cast(extracted, Integer), 9999),
    )


def _domain_sort_expr():
    return case(
        (KnowledgePoint.domain == "数与代数", 1),
        (KnowledgePoint.domain == "图形与几何", 2),
        (KnowledgePoint.domain == "统计与概率", 3),
        (KnowledgePoint.domain == "综合与实践", 4),
        else_=99,
    )


def _category1_sort_expr():
    """一级分类课标顺序。较长/更具体名称必须先匹配，避免「概率」误匹配「随机事件的概率」。"""
    return case(
        (KnowledgePoint.category_1.contains("数与式"), 1),
        (KnowledgePoint.category_1.contains("方程与不等式"), 2),
        (KnowledgePoint.category_1.contains("函数"), 3),
        (KnowledgePoint.category_1.contains("图形的性质"), 1),
        (KnowledgePoint.category_1.contains("图形的变化"), 2),
        (KnowledgePoint.category_1.contains("图形与坐标"), 3),
        (KnowledgePoint.category_1.contains("抽样与数据分析"), 1),
        (KnowledgePoint.category_1.contains("随机事件的概率"), 2),
        (KnowledgePoint.category_1 == "统计", 1),
        (KnowledgePoint.category_1 == "概率", 2),
        (KnowledgePoint.category_1.contains("综合与实践"), 1),
        else_=99,
    )


def _example_number_sort_expr():
    """从典型题目「例83」提取序号，用于无二级分类时的课标顺序近似排序。"""
    pos = func.instr(func.coalesce(KnowledgePoint.typical_questions, ""), "例")
    extracted = func.substr(KnowledgePoint.typical_questions, pos + 1, 3)
    return case(
        (func.coalesce(pos, 0) <= 0, 9999),
        else_=func.coalesce(cast(extracted, Integer), 9999),
    )


@router.get("/points", response_model=KnowledgePointListResponse)
async def list_knowledge_points(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    domain: Optional[str] = None,
    grade: Optional[str] = None,
    cognitive_level: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(KnowledgePoint)
    count_query = select(func.count()).select_from(KnowledgePoint)

    if domain:
        query = query.where(KnowledgePoint.domain == domain)
        count_query = count_query.where(KnowledgePoint.domain == domain)
    if grade:
        query = query.where(KnowledgePoint.grade.ilike(f"%{grade}%"))
        count_query = count_query.where(KnowledgePoint.grade.ilike(f"%{grade}%"))
    if cognitive_level:
        query = query.where(KnowledgePoint.cognitive_level == cognitive_level)
        count_query = count_query.where(KnowledgePoint.cognitive_level == cognitive_level)
    if status:
        query = query.where(KnowledgePoint.status == status)
        count_query = count_query.where(KnowledgePoint.status == status)
    if keyword:
        query = query.where(KnowledgePoint.name.ilike(f"%{keyword}%"))
        count_query = count_query.where(KnowledgePoint.name.ilike(f"%{keyword}%"))

    total = await db.scalar(count_query)
    # 课标结构序：领域 → 一级分类 → 二级分类序号 → 例题序号（扁平无二级时）→ ID
    query = (
        query.order_by(
            _domain_sort_expr(),
            _category1_sort_expr(),
            KnowledgePoint.category_1,
            _paren_number_sort_expr(KnowledgePoint.category_2),
            KnowledgePoint.category_2,
            _example_number_sort_expr(),
            KnowledgePoint.id,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    points = result.scalars().all()

    return KnowledgePointListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[KnowledgePointResponse.model_validate(p, from_attributes=True) for p in points],
    )


# ==================== AI 生成知识点名称 ====================

class GenerateShortNameRequest(BaseModel):
    mode: str = "empty_only"  # empty_only | overwrite
    domain: Optional[str] = None
    grade: Optional[str] = None
    point_ids: Optional[List[str]] = None


class GeneratePrerequisiteRequest(BaseModel):
    point_ids: Optional[List[str]] = None


class UpdatePointPrerequisitesRequest(BaseModel):
    prerequisite_ids: List[str]


@router.post("/points/generate-short-names")
async def generate_short_names(
    data: GenerateShortNameRequest,
    background_tasks: BackgroundTasks,
):
    """启动AI生成知识点名称任务"""
    import uuid
    task_key = f"shortname_{uuid.uuid4().hex[:8]}"

    from app.services.kp_shortname_service import run_shortname_task
    background_tasks.add_task(run_shortname_task, task_key, data.mode, data.domain, data.grade, data.point_ids)

    return {"message": "生成任务已启动", "task_key": task_key}


@router.get("/points/generate-short-names/progress/{task_key}")
async def get_shortname_progress(task_key: str):
    """查询知识点名称生成任务进度"""
    from app.services.kp_shortname_service import get_shortname_task_progress
    progress = get_shortname_task_progress(task_key)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")
    return progress


@router.post("/points/generate-prerequisites")
async def generate_prerequisites(
    data: GeneratePrerequisiteRequest,
    background_tasks: BackgroundTasks,
):
    """为选中知识点生成前置依赖；未选择时处理全部知识点。"""
    import uuid

    task_key = f"prerequisite_{uuid.uuid4().hex[:8]}"
    from app.services.kp_prerequisite_service import run_prerequisite_task

    background_tasks.add_task(
        run_prerequisite_task, task_key, data.point_ids
    )
    return {"message": "前置知识点生成任务已启动", "task_key": task_key}


@router.get("/points/generate-prerequisites/progress/{task_key}")
async def get_prerequisite_progress(task_key: str):
    from app.services.kp_prerequisite_service import (
        get_prerequisite_task_progress,
    )

    progress = get_prerequisite_task_progress(task_key)
    if not progress:
        raise HTTPException(status_code=404, detail="任务不存在")
    return progress


@router.put("/points/{point_id}/prerequisites", response_model=KnowledgePointResponse)
async def update_point_prerequisites(
    point_id: str,
    data: UpdatePointPrerequisitesRequest,
    db: AsyncSession = Depends(get_db),
):
    point = (
        await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.id == point_id)
        )
    ).scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")

    prerequisite_ids = list(
        dict.fromkeys(
            str(candidate_id).strip()
            for candidate_id in data.prerequisite_ids
            if str(candidate_id).strip() and str(candidate_id).strip() != point_id
        )
    )
    if prerequisite_ids:
        existing_ids = set(
            (
                await db.execute(
                    select(KnowledgePoint.id).where(
                        KnowledgePoint.id.in_(prerequisite_ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        missing_ids = [
            candidate_id
            for candidate_id in prerequisite_ids
            if candidate_id not in existing_ids
        ]
        if missing_ids:
            raise HTTPException(
                status_code=400,
                detail=f"依赖知识点不存在：{', '.join(missing_ids[:5])}",
            )

    await db.execute(
        delete(KnowledgeRelation).where(
            KnowledgeRelation.to_point_id == point_id,
            KnowledgeRelation.relation_type == "prerequisite",
        )
    )
    for prerequisite_id in prerequisite_ids:
        db.add(
            KnowledgeRelation(
                from_point_id=prerequisite_id,
                to_point_id=point_id,
                relation_type="prerequisite",
                weight=1.0,
            )
        )
    await db.flush()
    await sync_prerequisite_names(db, [point_id])
    await db.commit()
    await db.refresh(point)
    return KnowledgePointResponse.model_validate(point, from_attributes=True)


@router.get("/points/{point_id}", response_model=KnowledgePointResponse)
async def get_knowledge_point(point_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return KnowledgePointResponse.model_validate(point, from_attributes=True)


@router.post("/points", response_model=KnowledgePointResponse)
async def create_knowledge_point(data: KnowledgePointCreate, db: AsyncSession = Depends(get_db)):
    point = KnowledgePoint(**data.model_dump())
    db.add(point)
    await db.commit()
    await db.refresh(point)
    return KnowledgePointResponse.model_validate(point, from_attributes=True)


@router.put("/points/{point_id}", response_model=KnowledgePointResponse)
async def update_knowledge_point(point_id: str, data: KnowledgePointUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(point, key, value)
    await db.commit()
    await db.refresh(point)
    return KnowledgePointResponse.model_validate(point, from_attributes=True)


@router.delete("/points/clear-all")
async def clear_all_knowledge_points(db: AsyncSession = Depends(get_db)):
    """清除所有知识点及相关关系"""
    await db.execute(delete(KnowledgeRelation))
    await db.execute(delete(KnowledgePoint))
    await db.commit()
    return {"message": "已清除所有知识点"}


@router.delete("/points/{point_id}")
async def delete_knowledge_point(point_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == point_id))
    point = result.scalar_one_or_none()
    if not point:
        raise HTTPException(status_code=404, detail="知识点不存在")
    await db.delete(point)
    await db.commit()
    return {"message": "已删除"}


@router.get("/relations", response_model=List[KnowledgeRelationResponse])
async def list_relations(
    point_id: Optional[str] = None,
    relation_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(KnowledgeRelation)
    if point_id:
        query = query.where(
            (KnowledgeRelation.from_point_id == point_id) |
            (KnowledgeRelation.to_point_id == point_id)
        )
    if relation_type:
        query = query.where(KnowledgeRelation.relation_type == relation_type)
    result = await db.execute(query)
    relations = result.scalars().all()

    # 收集所有涉及的知识点ID，批量查询名称
    point_ids = set()
    for r in relations:
        point_ids.add(r.from_point_id)
        point_ids.add(r.to_point_id)

    name_map = {}
    short_name_map = {}
    if point_ids:
        points_result = await db.execute(
            select(KnowledgePoint.id, KnowledgePoint.name, KnowledgePoint.short_name).where(KnowledgePoint.id.in_(point_ids))
        )
        for pid, pname, pshort in points_result.all():
            name_map[pid] = pname
            short_name_map[pid] = pshort

    resp = []
    for r in relations:
        data = KnowledgeRelationResponse.model_validate(r, from_attributes=True)
        data.from_point_name = name_map.get(r.from_point_id)
        data.from_point_short_name = short_name_map.get(r.from_point_id)
        data.to_point_name = name_map.get(r.to_point_id)
        data.to_point_short_name = short_name_map.get(r.to_point_id)
        resp.append(data)
    return resp


@router.post("/relations", response_model=KnowledgeRelationResponse)
async def create_relation(data: KnowledgeRelationCreate, db: AsyncSession = Depends(get_db)):
    relation = KnowledgeRelation(**data.model_dump())
    db.add(relation)
    await db.flush()
    if relation.relation_type == "prerequisite":
        await sync_prerequisite_names(db, [relation.to_point_id])
    await db.commit()
    await db.refresh(relation)
    return KnowledgeRelationResponse.model_validate(relation, from_attributes=True)


@router.post("/relations/sync-prerequisites")
async def sync_relation_prerequisites(db: AsyncSession = Depends(get_db)):
    """将全部历史前置依赖关系回填为目标知识点的依赖名称。"""
    updated = await sync_prerequisite_names(db)
    await db.commit()
    populated = await db.scalar(
        select(func.count())
        .select_from(KnowledgePoint)
        .where(KnowledgePoint.prerequisites.isnot(None))
    ) or 0
    return {
        "message": f"同步完成：{populated} 个知识点已有前置依赖",
        "updated": updated,
        "populated": populated,
    }


@router.delete("/relations/clear-all")
async def clear_all_relations(db: AsyncSession = Depends(get_db)):
    """一键清除全部知识点关系"""
    count = await db.scalar(select(func.count()).select_from(KnowledgeRelation)) or 0
    await db.execute(delete(KnowledgeRelation))
    await sync_prerequisite_names(db)
    await db.commit()
    return {"message": f"已清除全部关系（{count} 条）", "deleted": count}


@router.delete("/relations/{relation_id}")
async def delete_relation(relation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgeRelation).where(KnowledgeRelation.id == relation_id))
    relation = result.scalar_one_or_none()
    if not relation:
        raise HTTPException(status_code=404, detail="关系不存在")
    target_id = relation.to_point_id
    is_prerequisite = relation.relation_type == "prerequisite"
    await db.delete(relation)
    await db.flush()
    if is_prerequisite:
        await sync_prerequisite_names(db, [target_id])
    await db.commit()
    return {"message": "已删除"}


@router.get("/stats", response_model=KnowledgeStatsResponse)
async def get_stats(db: AsyncSession = Depends(get_db)):
    total = await db.scalar(select(func.count()).select_from(KnowledgePoint))
    by_domain = {}
    for domain in ["数与代数", "图形与几何", "统计与概率", "综合与实践"]:
        count = await db.scalar(
            select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.domain == domain)
        )
        by_domain[domain] = count or 0

    by_grade = {}
    for g in ["七年级", "八年级", "九年级"]:
        count = await db.scalar(
            select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.grade.ilike(f"%{g}%"))
        )
        by_grade[g] = count or 0

    by_status = {}
    for status in ["draft", "reviewed", "published"]:
        count = await db.scalar(
            select(func.count()).select_from(KnowledgePoint).where(KnowledgePoint.status == status)
        )
        by_status[status] = count or 0

    relation_count = await db.scalar(select(func.count()).select_from(KnowledgeRelation))

    return KnowledgeStatsResponse(
        total=total or 0,
        by_domain=by_domain,
        by_grade=by_grade,
        by_status=by_status,
        relation_count=relation_count or 0,
    )


@router.post("/annotate-chapters")
async def annotate_chapters(
    data: AnnotateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """启动章节/年级段标注任务：根据多本教材PDF综合为知识点标注grade和chapter"""
    if not data.textbook_file_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个教材文件")

    # 验证所有文件存在
    for fid in data.textbook_file_ids:
        result = await db.execute(select(UploadedFile).where(UploadedFile.id == fid))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail=f"教材文件ID {fid} 不存在")

    # 创建ExtractionTask记录用于进度跟踪
    file_ids_str = ",".join(str(fid) for fid in data.textbook_file_ids)
    task = ExtractionTask(
        task_type="annotation",
        source_file_ids=file_ids_str,
        status="pending",
        config={"mode": data.mode, "point_ids": data.point_ids},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.services.annotation_service import run_annotation_task
    background_tasks.add_task(run_annotation_task, data.textbook_file_ids, data.mode, task.id, data.point_ids)

    return {"message": "标注任务已启动", "textbook_file_ids": data.textbook_file_ids, "mode": data.mode, "task_id": task.id}
