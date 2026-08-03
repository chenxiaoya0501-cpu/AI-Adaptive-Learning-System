"""教材章节目录 API"""
from typing import List, Optional
import re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.chapter import TextbookChapter
from app.models.system import UploadedFile
from app.models.knowledge import KnowledgePoint
from app.schemas.chapter import TextbookChapterResponse, TextbookChapterUpdate, TextbookTocTreeResponse
from app.schemas.knowledge import KnowledgePointResponse
from sqlalchemy import or_

router = APIRouter()


def _normalize_chapter_title(s: str) -> str:
    """统一空白：全角空格/不间断空格 → 半角，再压缩连续空白。"""
    if not s:
        return ""
    s = s.replace("\u3000", " ").replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", s)


async def _query_related_kps(db: AsyncSession, title: str, level: str) -> List[KnowledgePoint]:
    """按知识点「所属章节」匹配目录标题。

    章：规范化空白后完整章标题相等（避免「有理数」误匹配「第二章 有理数的运算」，
    同时兼容标注结果里的全角空格与目录半角空格不一致）。
    """
    raw = (title or "").strip()
    if not raw:
        return []
    if level != "chapter":
        return []

    target = _normalize_chapter_title(raw)
    if not target:
        return []

    # 先收窄候选（含章序号关键词），再在 Python 侧做空白规范化精确比较
    # 例：目标「第五章 一元一次方程」→ 用「第五章」收窄，避免全表扫描
    m = re.match(r"^(第[一二三四五六七八九十百零\d]+章)", target)
    prefix = m.group(1) if m else target[:4]

    result = await db.execute(
        select(KnowledgePoint)
        .where(
            KnowledgePoint.chapter.isnot(None),
            KnowledgePoint.chapter != "",
            KnowledgePoint.chapter.ilike(f"%{prefix}%"),
        )
        .order_by(KnowledgePoint.id)
        .limit(500)
    )
    matched = []
    for kp in result.scalars().all():
        ch = _normalize_chapter_title(kp.chapter or "")
        if not ch:
            continue
        # 精确相等，或 append 多值「章名; …」
        if ch == target or ch.startswith(target + ";") or ch.startswith(target + "；"):
            matched.append(kp)
        elif ";" in ch or "；" in ch:
            parts = re.split(r"[;；]", ch)
            if any(_normalize_chapter_title(p) == target for p in parts):
                matched.append(kp)
    return matched[:200]


@router.get("/trees", response_model=List[TextbookTocTreeResponse])
async def list_toc_trees(
    grade: Optional[str] = None,
    uploaded_file_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """按教材列出章节目录树（含已有目录的文件，或标记为教材的文件）"""
    # 已有章节的文件 ID
    chapter_file_ids = list((await db.execute(
        select(TextbookChapter.uploaded_file_id).distinct()
    )).scalars().all())

    file_query = select(UploadedFile)
    if uploaded_file_id:
        file_query = file_query.where(UploadedFile.id == uploaded_file_id)
    else:
        # 教材类型，或已抽出目录的文件（兼容历史上被标成课标的课本）
        conds = [UploadedFile.file_type == "textbook"]
        if chapter_file_ids:
            conds.append(UploadedFile.id.in_(chapter_file_ids))
        file_query = file_query.where(or_(*conds))
    files = (await db.execute(file_query.order_by(UploadedFile.id.desc()))).scalars().all()

    trees = []
    for f in files:
        ch_query = select(TextbookChapter).where(TextbookChapter.uploaded_file_id == f.id)
        if grade:
            ch_query = ch_query.where(TextbookChapter.grade.ilike(f"%{grade}%"))
        chapters = (await db.execute(
            ch_query.order_by(TextbookChapter.sort_order, TextbookChapter.id)
        )).scalars().all()

        # KP 计数：按 title 模糊匹配 knowledge_points.chapter
        chapter_nodes = [c for c in chapters if c.level == "chapter"]
        section_nodes = [c for c in chapters if c.level == "section"]

        children_map = {}
        for s in section_nodes:
            children_map.setdefault(s.parent_id, []).append(s)

        tree_chapters = []
        for ch in chapter_nodes:
            related = await _query_related_kps(db, ch.title, "chapter")
            kp_count = len(related)

            child_res = []
            for s in children_map.get(ch.id, []):
                # 节不展示关联知识点（知识点仅标注到章）
                child_res.append(TextbookChapterResponse(
                    id=s.id,
                    uploaded_file_id=s.uploaded_file_id,
                    subject=s.subject,
                    grade=s.grade,
                    semester=s.semester,
                    parent_id=s.parent_id,
                    level=s.level,
                    title=s.title,
                    sort_order=s.sort_order,
                    content_summary=s.content_summary,
                    status=s.status,
                    kp_count=0,
                ))

            tree_chapters.append(TextbookChapterResponse(
                id=ch.id,
                uploaded_file_id=ch.uploaded_file_id,
                subject=ch.subject,
                grade=ch.grade,
                semester=ch.semester,
                parent_id=ch.parent_id,
                level=ch.level,
                title=ch.title,
                sort_order=ch.sort_order,
                content_summary=ch.content_summary,
                status=ch.status,
                kp_count=kp_count,
                children=child_res,
            ))

        grade_map = {"7": "七年级", "8": "八年级", "9": "九年级"}
        file_grade = grade_map.get(str(f.grade or ""), f.grade)

        trees.append(TextbookTocTreeResponse(
            uploaded_file_id=f.id,
            file_name=f.original_name,
            grade=tree_chapters[0].grade if tree_chapters else file_grade,
            semester=tree_chapters[0].semester if tree_chapters else f.semester,
            chapters=tree_chapters,
        ))

    return trees


@router.put("/{chapter_id}", response_model=TextbookChapterResponse)
async def update_chapter(
    chapter_id: int,
    data: TextbookChapterUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(TextbookChapter).where(TextbookChapter.id == chapter_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return TextbookChapterResponse(
        id=row.id,
        uploaded_file_id=row.uploaded_file_id,
        subject=row.subject,
        grade=row.grade,
        semester=row.semester,
        parent_id=row.parent_id,
        level=row.level,
        title=row.title,
        sort_order=row.sort_order,
        content_summary=row.content_summary,
        status=row.status,
        kp_count=0,
    )


@router.delete("/clear-all")
async def clear_all_chapters(db: AsyncSession = Depends(get_db)):
    """一键清除全部章节目录"""
    count = await db.scalar(select(func.count()).select_from(TextbookChapter)) or 0
    await db.execute(delete(TextbookChapter))
    await db.commit()
    return {"message": f"已清除全部章节目录（{count} 条）", "deleted": count}


@router.get("/{chapter_id}/knowledge-points", response_model=List[KnowledgePointResponse])
async def list_chapter_knowledge_points(chapter_id: int, db: AsyncSession = Depends(get_db)):
    """查看某章/节关联的知识点（按 chapter 字段模糊匹配）"""
    result = await db.execute(select(TextbookChapter).where(TextbookChapter.id == chapter_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    kps = await _query_related_kps(db, row.title, row.level or "chapter")
    return [KnowledgePointResponse.model_validate(kp, from_attributes=True) for kp in kps]


@router.delete("/{chapter_id}")
async def delete_chapter(chapter_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(TextbookChapter).where(TextbookChapter.id == chapter_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="章节不存在")
    # 删子节
    await db.execute(delete(TextbookChapter).where(TextbookChapter.parent_id == chapter_id))
    await db.delete(row)
    await db.commit()
    return {"message": "已删除"}


@router.post("/reorder")
async def reorder_chapters(
    items: List[dict],
    db: AsyncSession = Depends(get_db),
):
    """批量更新排序 [{id, sort_order}]"""
    for it in items:
        cid = it.get("id")
        order = it.get("sort_order")
        if cid is None or order is None:
            continue
        result = await db.execute(select(TextbookChapter).where(TextbookChapter.id == cid))
        row = result.scalar_one_or_none()
        if row:
            row.sort_order = order
    await db.commit()
    return {"message": "已更新排序"}


@router.post("/extract-summaries/{uploaded_file_id}")
async def extract_section_summaries(
    uploaded_file_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """根据上传的电子教材PDF，创建后台任务为各节提取内容概述"""
    from app.services.chapter_summary_service import run_summary_extraction_task
    from app.models.system import ExtractionTask as ET

    # 检查文件是否存在
    file_result = await db.execute(select(UploadedFile).where(UploadedFile.id == uploaded_file_id))
    file_record = file_result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="教材文件不存在")

    # 检查是否有正在运行的同类任务
    running = (await db.execute(
        select(ET).where(
            ET.task_type == "summary_extraction",
            ET.source_file_ids == str(uploaded_file_id),
            ET.status.in_(["pending", "running"]),
        )
    )).scalar_one_or_none()
    if running:
        return {
            "task_id": running.id,
            "message": "已有正在进行的提取任务",
            "status": running.status,
            "progress": running.progress,
        }

    # 创建任务记录
    task = ET(
        task_type="summary_extraction",
        source_file_ids=str(uploaded_file_id),
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 后台执行
    background_tasks.add_task(run_summary_extraction_task, task.id)

    return {
        "task_id": task.id,
        "message": "内容概述提取任务已启动",
        "status": "pending",
        "progress": 0,
    }


@router.get("/extract-summaries/task/{task_id}")
async def get_summary_extraction_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查询内容概述提取任务的进度"""
    from app.models.system import ExtractionTask as ET

    result = await db.execute(select(ET).where(ET.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": task.id,
        "status": task.status,
        "progress": task.progress,
        "result_summary": task.result_summary,
        "error_message": task.error_message,
    }


@router.get("/extract-summaries/active/{uploaded_file_id}")
async def get_active_summary_task(
    uploaded_file_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查询指定教材是否有正在进行的内容概述提取任务（用于页面恢复轮询）"""
    from app.models.system import ExtractionTask as ET

    result = await db.execute(
        select(ET).where(
            ET.task_type == "summary_extraction",
            ET.source_file_ids == str(uploaded_file_id),
            ET.status.in_(["pending", "running"]),
        ).order_by(ET.id.desc()).limit(1)
    )
    task = result.scalar_one_or_none()
    if not task:
        return {"task_id": None, "active": False}
    return {
        "task_id": task.id,
        "active": True,
        "status": task.status,
        "progress": task.progress,
        "result_summary": task.result_summary,
    }
