from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict

from app.database import get_db
from app.models.system import ExtractionTask, UploadedFile
from app.schemas.system import ExtractionTaskResponse, ExtractionTaskCreate
from app.services.extraction_service import run_extraction_task

router = APIRouter()


async def _file_name_map(db: AsyncSession, file_ids: List[int]) -> Dict[int, str]:
    if not file_ids:
        return {}
    result = await db.execute(select(UploadedFile).where(UploadedFile.id.in_(file_ids)))
    return {f.id: f.original_name or f"文件#{f.id}" for f in result.scalars().all()}


def _parse_file_ids(source_file_ids: Optional[str]) -> List[int]:
    if not source_file_ids:
        return []
    ids = []
    for part in str(source_file_ids).split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return ids


async def _to_task_response(db: AsyncSession, task: ExtractionTask) -> ExtractionTaskResponse:
    resp = ExtractionTaskResponse.model_validate(task, from_attributes=True)
    ids = _parse_file_ids(task.source_file_ids)
    if ids:
        names = await _file_name_map(db, ids)
        resp.source_file_names = "、".join(
            names.get(i) or f"已删除文件#{i}" for i in ids
        )
    else:
        resp.source_file_names = None
    return resp


@router.post("/start", response_model=ExtractionTaskResponse)
async def start_extraction(
    data: ExtractionTaskCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    allowed_types = {
        "knowledge_extraction",
        "relation_extraction",
        "annotation",
        "chapter_toc_extraction",
    }
    if data.task_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"不支持的任务类型: {data.task_type}")

    file_ids_str = ""
    if data.source_file_ids:
        for fid in data.source_file_ids:
            result = await db.execute(select(UploadedFile).where(UploadedFile.id == fid))
            file_record = result.scalar_one_or_none()
            if not file_record:
                raise HTTPException(status_code=404, detail=f"源文件ID={fid}不存在")
        file_ids_str = ",".join(str(fid) for fid in data.source_file_ids)

    if data.task_type == "chapter_toc_extraction" and not data.source_file_ids:
        raise HTTPException(status_code=400, detail="章节目录抽取请选择已上传的PDF文件")

    task = ExtractionTask(
        task_type=data.task_type,
        source_file_ids=file_ids_str or None,
        status="pending",
        config=data.config,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    background_tasks.add_task(run_extraction_task, task.id)

    return await _to_task_response(db, task)


@router.get("/tasks", response_model=List[ExtractionTaskResponse])
async def list_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExtractionTask).order_by(ExtractionTask.created_at.desc()).limit(50)
    )
    tasks = result.scalars().all()
    return [await _to_task_response(db, t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=ExtractionTaskResponse)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return await _to_task_response(db, task)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """删除抽取任务记录（不删除已写入的知识点/目录等结果数据）"""
    result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status in ("pending", "running"):
        raise HTTPException(status_code=400, detail="任务进行中，请结束后再删除")
    await db.delete(task)
    await db.commit()
    return {"message": "已删除任务记录"}
