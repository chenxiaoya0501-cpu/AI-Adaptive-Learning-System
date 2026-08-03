"""题库与试卷管理 API"""
import os
import shutil
import uuid
import logging
from typing import Optional, List, Dict, Set, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Query
from sqlalchemy import select, func, delete, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.config import settings
from app.models.question import (
    ExamPaper, Question, KpLinkTask, KpLinkSuggestion,
    AnswerRewriteTask, AnswerRewriteSuggestion,
    AbilityLabelTask, AbilityLabelSuggestion,
    ExamScoreScheme, ExamStructureTemplate, ExamKpScoreStat,
)
from app.models.knowledge import KnowledgePoint
from app.schemas.question import (
    ExamPaperCreate, ExamPaperUpdate, ExamPaperResponse,
    QuestionCreate, QuestionUpdate, QuestionResponse, QuestionListResponse,
    KpLinkStartRequest, KpLinkTaskResponse, KpLinkSuggestionResponse, KpLinkConfirmRequest,
    BatchSetPrimaryKpRequest, BatchRewriteImageAnswersRequest,
    AnswerRewriteStartRequest, AnswerRewriteTaskResponse,
    AnswerRewriteSuggestionResponse, AnswerRewriteConfirmRequest,
    AbilityLabelStartRequest, AbilityLabelTaskResponse,
    AbilityLabelSuggestionResponse, AbilityLabelConfirmRequest,
    BatchDeleteQuestionsRequest,
    ExamScoreSchemeCreate, ExamScoreSchemeResponse,
    ApplyScoreSchemeRequest, BuildTemplateRequest,
    ExamStructureTemplateResponse, ExamKpScoreStatResponse,
    ABILITY_DIMENSIONS,
    AIGenerateRequest, AIGenerateResponse, AIGeneratedQuestionItem,
)
from app.services import exam_template_service as tpl_svc

router = APIRouter()
logger = logging.getLogger(__name__)


async def _kp_name_map(db: AsyncSession, kp_ids: Set[str]) -> Dict[str, str]:
    ids = [i for i in kp_ids if i]
    if not ids:
        return {}
    result = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))
    return {kp.id: kp.name for kp in result.scalars().all()}


async def _pending_question_ids(db: AsyncSession, question_ids: List[int]) -> Set[int]:
    if not question_ids:
        return set()
    result = await db.execute(
        select(KpLinkSuggestion.question_id).where(
            KpLinkSuggestion.question_id.in_(question_ids),
            KpLinkSuggestion.status == "pending",
        ).distinct()
    )
    return set(result.scalars().all())


async def _to_question_response(
    db: AsyncSession,
    q: Question,
    kp_names: Optional[Dict[str, str]] = None,
    pending_ids: Optional[Set[int]] = None,
) -> QuestionResponse:
    names = kp_names
    if names is None and q.primary_kp_id:
        names = await _kp_name_map(db, {q.primary_kp_id})
    names = names or {}
    pending = pending_ids
    if pending is None:
        pending = await _pending_question_ids(db, [q.id])
    data = QuestionResponse.model_validate(q, from_attributes=True)
    data.primary_kp_name = names.get(q.primary_kp_id) if q.primary_kp_id else None
    data.has_pending_suggestion = q.id in pending
    if not data.primary_kp_confidence:
        data.primary_kp_confidence = await _suggestion_confidence(db, q.id)
    return data


# ==================== 试卷管理 ====================

@router.post("/papers/upload", response_model=ExamPaperResponse)
async def upload_exam_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(...),
    paper_type: str = Form("real"),
    source: Optional[str] = Form(None),
    grade: Optional[str] = Form(None),
    year: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """上传试卷Word文件并启动解析"""
    # 验证文件类型
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".docx", ".doc"):
        raise HTTPException(status_code=400, detail="只支持 .docx/.doc 格式的Word文件")

    # 保存文件
    stored_name = f"{uuid.uuid4().hex}{ext}"
    upload_dir = os.path.join(settings.UPLOAD_DIR, "papers")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, stored_name)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 创建试卷记录
    paper = ExamPaper(
        title=title,
        paper_type=paper_type,
        source=source,
        grade=grade,
        year=year,
        region=region,
        subject="数学",
        original_filename=file.filename,
        stored_filename=stored_name,
        parse_status="pending",
    )
    db.add(paper)
    await db.commit()
    await db.refresh(paper)

    # 启动后台解析
    background_tasks.add_task(_parse_paper_background, paper.id, file_path)

    return ExamPaperResponse.model_validate(paper, from_attributes=True)


@router.get("/papers", response_model=List[ExamPaperResponse])
async def list_papers(
    paper_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取试卷列表（含挂载 / 分值 / 模板统计）"""
    await tpl_svc.ensure_default_score_scheme(db)
    query = select(ExamPaper).order_by(ExamPaper.created_at.desc())
    if paper_type:
        query = query.where(ExamPaper.paper_type == paper_type)
    result = await db.execute(query)
    papers = result.scalars().all()
    items = []
    for p in papers:
        linked = await db.scalar(
            select(func.count()).select_from(Question).where(
                Question.exam_paper_id == p.id,
                Question.primary_kp_id.isnot(None),
                Question.primary_kp_id != "",
            )
        ) or 0
        scored = await db.scalar(
            select(func.count()).select_from(Question).where(
                Question.exam_paper_id == p.id,
                Question.score.isnot(None),
            )
        ) or 0
        tpl = await tpl_svc.template_for_paper(db, p.id)
        resp = ExamPaperResponse.model_validate(p, from_attributes=True)
        resp.linked_count = linked
        resp.scored_count = scored
        if tpl:
            resp.template_id = tpl.id
            resp.template_status = tpl.status
            resp.template_is_default = bool(tpl.is_default)
        else:
            resp.template_status = "none"
            resp.template_is_default = False
        items.append(resp)
    return items


@router.delete("/clear-all")
async def clear_all_questions(
    bank_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """按类型清除题库。bank_type=real|mock 时只清对应类型；不传则清除全部。"""
    if bank_type and bank_type not in ("real", "mock"):
        raise HTTPException(status_code=400, detail="bank_type 只能是 real 或 mock")

    if bank_type:
        paper_query = select(ExamPaper).where(ExamPaper.paper_type == bank_type)
    else:
        paper_query = select(ExamPaper)

    result = await db.execute(paper_query)
    papers = result.scalars().all()
    paper_ids = [p.id for p in papers]

    # 清理来源于这些试卷的结构模板
    if paper_ids:
        all_tpl = (await db.execute(select(ExamStructureTemplate))).scalars().all()
        for t in all_tpl:
            src = t.source_paper_ids or []
            if src and all(pid in paper_ids for pid in src):
                await db.execute(delete(ExamKpScoreStat).where(ExamKpScoreStat.template_id == t.id))
                await db.execute(delete(ExamStructureTemplate).where(ExamStructureTemplate.id == t.id))

    if bank_type:
        await db.execute(delete(Question).where(Question.bank_type == bank_type))
        if paper_ids:
            await db.execute(delete(ExamPaper).where(ExamPaper.id.in_(paper_ids)))
    else:
        await db.execute(delete(Question))
        await db.execute(delete(ExamPaper))
    await db.commit()

    papers_dir = os.path.join(settings.UPLOAD_DIR, "papers")
    for paper in papers:
        if paper.stored_filename:
            file_path = os.path.join(papers_dir, paper.stored_filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        img_dir = os.path.join(papers_dir, f"paper_{paper.id}_images")
        if os.path.exists(img_dir):
            shutil.rmtree(img_dir)

    type_label = {"real": "真题", "mock": "模拟题"}.get(bank_type or "", "全部")
    return {
        "message": f"已清除{type_label}题库数据",
        "bank_type": bank_type,
        "deleted_papers": len(papers),
    }


@router.put("/papers/{paper_id}", response_model=ExamPaperResponse)
async def update_paper(
    paper_id: int,
    data: ExamPaperUpdate,
    db: AsyncSession = Depends(get_db),
):
    """编辑试卷元信息（标题/类型/年级/年份/地区等）。"""
    result = await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    payload = data.model_dump(exclude_unset=True)
    if "paper_type" in payload and payload["paper_type"] not in ("real", "mock"):
        raise HTTPException(status_code=400, detail="试卷类型仅支持 real / mock")
    if "title" in payload:
        title = (payload["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="试卷标题不能为空")
        payload["title"] = title

    old_type = paper.paper_type
    for k, v in payload.items():
        setattr(paper, k, v)

    # 类型变更时同步题目 bank_type
    new_type = paper.paper_type
    if "paper_type" in payload and new_type != old_type:
        qrows = await db.execute(select(Question).where(Question.exam_paper_id == paper_id))
        for q in qrows.scalars().all():
            q.bank_type = new_type

    await db.commit()
    await db.refresh(paper)
    resp = ExamPaperResponse.model_validate(paper, from_attributes=True)
    return resp


@router.delete("/papers/{paper_id}")
async def delete_paper(paper_id: int, db: AsyncSession = Depends(get_db)):
    """删除试卷及其所有题目"""
    result = await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    # 删除仅来源于该卷的结构模板
    tpl = await tpl_svc.template_for_paper(db, paper_id)
    if tpl:
        await db.execute(delete(ExamKpScoreStat).where(ExamKpScoreStat.template_id == tpl.id))
        await db.execute(delete(ExamStructureTemplate).where(ExamStructureTemplate.id == tpl.id))

    # 删除关联题目
    await db.execute(delete(Question).where(Question.exam_paper_id == paper_id))
    # 删除文件
    if paper.stored_filename:
        file_path = os.path.join(settings.UPLOAD_DIR, "papers", paper.stored_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    # 删除图片目录
    img_dir = os.path.join(settings.UPLOAD_DIR, "papers", f"paper_{paper_id}_images")
    if os.path.exists(img_dir):
        shutil.rmtree(img_dir)

    await db.delete(paper)
    await db.commit()
    return {"message": "已删除试卷及相关题目"}


@router.post("/papers/{paper_id}/reparse")
async def reparse_paper(
    paper_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """重新解析试卷"""
    result = await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    file_path = os.path.join(settings.UPLOAD_DIR, "papers", paper.stored_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="试卷文件不存在")

    # 删除旧题目
    await db.execute(delete(Question).where(Question.exam_paper_id == paper_id))
    # 清理旧图片目录
    img_dir = os.path.join(settings.UPLOAD_DIR, "papers", f"paper_{paper_id}_images")
    if os.path.exists(img_dir):
        shutil.rmtree(img_dir)
    paper.parse_status = "pending"
    paper.parse_error = None
    paper.total_questions = 0
    await db.commit()

    background_tasks.add_task(_parse_paper_background, paper_id, file_path)
    return {"message": "已启动重新解析"}


@router.post("/papers/reparse-all")
async def reparse_all_papers(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """重新解析所有试卷"""
    result = await db.execute(select(ExamPaper))
    papers = result.scalars().all()
    count = 0
    for paper in papers:
        file_path = os.path.join(settings.UPLOAD_DIR, "papers", paper.stored_filename)
        if not os.path.exists(file_path):
            continue
        await db.execute(delete(Question).where(Question.exam_paper_id == paper.id))
        img_dir = os.path.join(settings.UPLOAD_DIR, "papers", f"paper_{paper.id}_images")
        if os.path.exists(img_dir):
            shutil.rmtree(img_dir)
        paper.parse_status = "pending"
        paper.parse_error = None
        paper.total_questions = 0
        background_tasks.add_task(_parse_paper_background, paper.id, file_path)
        count += 1
    await db.commit()
    return {"message": f"已启动 {count} 份试卷的重新解析"}


# ==================== 题目管理 ====================

async def _suggestion_confidence(db: AsyncSession, question_id: int) -> Optional[str]:
    """取该题最近一条建议的置信度（优先已确认，其次待确认）"""
    for st in ("accepted", "modified", "pending"):
        sug = (await db.execute(
            select(KpLinkSuggestion)
            .where(
                KpLinkSuggestion.question_id == question_id,
                KpLinkSuggestion.status == st,
            )
            .order_by(KpLinkSuggestion.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        if sug and sug.confidence:
            return sug.confidence
    return None


async def _enrich_question(db: AsyncSession, q: Question) -> QuestionResponse:
    resp = QuestionResponse.model_validate(q, from_attributes=True)
    if q.primary_kp_id:
        kp = (await db.execute(
            select(KnowledgePoint).where(KnowledgePoint.id == q.primary_kp_id)
        )).scalar_one_or_none()
        resp.primary_kp_name = kp.name if kp else q.primary_kp_id
        if kp:
            resp.primary_kp_category_1 = kp.category_1
            resp.primary_kp_category_2 = kp.category_2
    pending = await db.scalar(
        select(func.count()).select_from(KpLinkSuggestion).where(
            KpLinkSuggestion.question_id == q.id,
            KpLinkSuggestion.status == "pending",
        )
    ) or 0
    resp.has_pending_suggestion = pending > 0
    # 列表展示：落库字段优先，否则回退到建议表
    conf = getattr(q, "primary_kp_confidence", None)
    if not conf:
        conf = await _suggestion_confidence(db, q.id)
    resp.primary_kp_confidence = conf
    return resp


@router.get("/list", response_model=QuestionListResponse)
async def list_questions(
    page: int = 1,
    page_size: int = 20,
    exam_paper_id: Optional[int] = None,
    question_type: Optional[str] = None,
    bank_type: Optional[str] = None,
    difficulty: Optional[int] = None,
    ability_dimension: Optional[str] = None,
    keyword: Optional[str] = None,
    link_status: Optional[str] = None,
    primary_kp_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """获取题目列表。link_status: linked/unlinked/pending"""
    query = select(Question).order_by(Question.exam_paper_id, Question.question_number)
    count_query = select(func.count()).select_from(Question)

    filters = []
    if exam_paper_id:
        filters.append(Question.exam_paper_id == exam_paper_id)
    if primary_kp_id:
        filters.append(Question.primary_kp_id == primary_kp_id)
    if question_type:
        filters.append(Question.question_type == question_type)
    if bank_type:
        filters.append(Question.bank_type == bank_type)
    if difficulty:
        filters.append(Question.difficulty == difficulty)
    if ability_dimension:
        filters.append(Question.ability_dimension == ability_dimension)
    if keyword:
        filters.append(Question.content.ilike(f"%{keyword}%"))

    if link_status == "linked":
        filters.append(Question.primary_kp_id.isnot(None))
        filters.append(Question.primary_kp_id != "")
    elif link_status == "unlinked":
        from sqlalchemy import or_
        filters.append(or_(Question.primary_kp_id.is_(None), Question.primary_kp_id == ""))
    elif link_status == "pending":
        pending_qids = select(KpLinkSuggestion.question_id).where(
            KpLinkSuggestion.status == "pending"
        ).distinct()
        filters.append(Question.id.in_(pending_qids))

    for f in filters:
        query = query.where(f)
        count_query = count_query.where(f)

    total = await db.scalar(count_query) or 0
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    items = result.scalars().all()

    # 挂载率：相对当前筛选范围（不含 link_status 本身时更有意义；用同 bank/paper 统计）
    rate_filters = []
    if exam_paper_id:
        rate_filters.append(Question.exam_paper_id == exam_paper_id)
    if bank_type:
        rate_filters.append(Question.bank_type == bank_type)
    rate_base = select(func.count()).select_from(Question)
    rate_linked_q = select(func.count()).select_from(Question).where(
        Question.primary_kp_id.isnot(None),
        Question.primary_kp_id != "",
    )
    for f in rate_filters:
        rate_base = rate_base.where(f)
        rate_linked_q = rate_linked_q.where(f)
    rate_total = await db.scalar(rate_base) or 0
    linked_count = await db.scalar(rate_linked_q) or 0
    link_rate = round(linked_count / rate_total * 100, 1) if rate_total else 0.0

    enriched = [await _enrich_question(db, q) for q in items]
    return QuestionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=enriched,
        linked_count=linked_count,
        link_rate=link_rate,
    )


# ==================== 知识点智能关联 ====================

@router.post("/kp-link/start", response_model=KpLinkTaskResponse)
async def start_kp_link(
    data: KpLinkStartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """启动题目-主知识点智能关联任务（建议不直接落库）"""
    if not data.exam_paper_id and not data.question_ids and not data.only_unlinked:
        raise HTTPException(status_code=400, detail="请指定关联范围")

    task = KpLinkTask(
        status="pending",
        progress=0,
        scope={
            "exam_paper_id": data.exam_paper_id,
            "only_unlinked": data.only_unlinked,
            "question_ids": data.question_ids,
            "bank_type": data.bank_type,
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.services.kp_link_service import run_kp_link_task
    background_tasks.add_task(run_kp_link_task, task.id)
    return KpLinkTaskResponse.model_validate(task, from_attributes=True)


@router.get("/kp-link/tasks", response_model=List[KpLinkTaskResponse])
async def list_kp_link_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KpLinkTask).order_by(KpLinkTask.id.desc()).limit(30))
    return [KpLinkTaskResponse.model_validate(t, from_attributes=True) for t in result.scalars().all()]


@router.get("/kp-link/tasks/{task_id}", response_model=KpLinkTaskResponse)
async def get_kp_link_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KpLinkTask).where(KpLinkTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return KpLinkTaskResponse.model_validate(task, from_attributes=True)


@router.get("/kp-link/suggestions", response_model=List[KpLinkSuggestionResponse])
async def list_kp_link_suggestions(
    task_id: Optional[int] = None,
    status: Optional[str] = "pending",
    db: AsyncSession = Depends(get_db),
):
    query = select(KpLinkSuggestion).order_by(KpLinkSuggestion.id.desc())
    if task_id:
        query = query.where(KpLinkSuggestion.task_id == task_id)
    if status:
        query = query.where(KpLinkSuggestion.status == status)
    result = await db.execute(query.limit(500))
    suggestions = result.scalars().all()

    items = []
    for s in suggestions:
        q = (await db.execute(select(Question).where(Question.id == s.question_id))).scalar_one_or_none()
        kp_name = None
        if s.suggested_kp_id:
            kp = (await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.id == s.suggested_kp_id)
            )).scalar_one_or_none()
            kp_name = kp.name if kp else s.suggested_kp_id
        items.append(KpLinkSuggestionResponse(
            id=s.id,
            task_id=s.task_id,
            question_id=s.question_id,
            question_number=q.question_number if q else None,
            question_content=(q.content or "")[:200] if q else None,
            suggested_kp_id=s.suggested_kp_id,
            suggested_kp_name=kp_name,
            confidence=s.confidence,
            reason=s.reason,
            status=s.status,
            final_kp_id=s.final_kp_id,
        ))
    return items


@router.post("/kp-link/confirm")
async def confirm_kp_link(data: KpLinkConfirmRequest, db: AsyncSession = Depends(get_db)):
    """确认智能关联建议：accept / reject / modify"""
    accepted = 0
    rejected = 0
    modified = 0
    for item in data.items:
        result = await db.execute(
            select(KpLinkSuggestion).where(KpLinkSuggestion.id == item.suggestion_id)
        )
        sug = result.scalar_one_or_none()
        if not sug:
            continue
        q = (await db.execute(select(Question).where(Question.id == sug.question_id))).scalar_one_or_none()
        if item.action == "reject":
            sug.status = "rejected"
            rejected += 1
            continue
        kp_id = item.kp_id if item.action == "modify" else sug.suggested_kp_id
        if not kp_id:
            sug.status = "rejected"
            rejected += 1
            continue
        kp = (await db.execute(select(KnowledgePoint).where(KnowledgePoint.id == kp_id))).scalar_one_or_none()
        if not kp:
            raise HTTPException(status_code=400, detail=f"知识点不存在: {kp_id}")
        if q:
            q.primary_kp_id = kp_id
            # 采用保留模型置信度；改选记为人工
            if item.action == "modify":
                q.primary_kp_confidence = "manual"
            else:
                q.primary_kp_confidence = (sug.confidence or "medium").lower()
            # 同步旧字段，便于兼容
            ids = list(q.knowledge_point_ids or [])
            if kp_id not in ids:
                ids = [kp_id] + [x for x in ids if x != kp_id]
                q.knowledge_point_ids = ids
        sug.final_kp_id = kp_id
        sug.status = "modified" if item.action == "modify" else "accepted"
        if item.action == "modify":
            modified += 1
        else:
            accepted += 1
    await db.commit()
    return {"message": "确认完成", "accepted": accepted, "rejected": rejected, "modified": modified}


@router.post("/batch-set-primary-kp")
async def batch_set_primary_kp(
    data: BatchSetPrimaryKpRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量指定主知识点"""
    if not data.question_ids:
        raise HTTPException(status_code=400, detail="请选择题目")
    kp = (await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == data.primary_kp_id)
    )).scalar_one_or_none()
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")
    result = await db.execute(select(Question).where(Question.id.in_(data.question_ids)))
    qs = result.scalars().all()
    for q in qs:
        q.primary_kp_id = data.primary_kp_id
        q.primary_kp_confidence = "manual"
        ids = list(q.knowledge_point_ids or [])
        if data.primary_kp_id not in ids:
            ids = [data.primary_kp_id] + [x for x in ids if x != data.primary_kp_id]
            q.knowledge_point_ids = ids
    await db.commit()
    return {"message": f"已更新 {len(qs)} 题", "updated": len(qs)}


@router.post("/batch-rewrite-image-answers")
async def batch_rewrite_image_answers(
    data: BatchRewriteImageAnswersRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """兼容旧入口：改为启动「待确认」任务，不直接改写答案。"""
    start = AnswerRewriteStartRequest(
        question_ids=data.question_ids,
        exam_paper_id=data.exam_paper_id,
        bank_type=data.bank_type,
    )
    return await start_answer_rewrite(start, background_tasks, db)


@router.post("/answer-rewrite/start", response_model=AnswerRewriteTaskResponse)
async def start_answer_rewrite(
    data: AnswerRewriteStartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """启动图片答案转文本任务：仅生成建议，需人工确认后才写入答案。"""
    task = AnswerRewriteTask(
        status="pending",
        progress=0,
        scope={
            "exam_paper_id": data.exam_paper_id,
            "question_ids": data.question_ids,
            "bank_type": data.bank_type,
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.services.answer_rewrite_task_service import run_answer_rewrite_task
    background_tasks.add_task(run_answer_rewrite_task, task.id)
    return AnswerRewriteTaskResponse.model_validate(task, from_attributes=True)


@router.get("/answer-rewrite/tasks/{task_id}", response_model=AnswerRewriteTaskResponse)
async def get_answer_rewrite_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AnswerRewriteTask).where(AnswerRewriteTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return AnswerRewriteTaskResponse.model_validate(task, from_attributes=True)


@router.get("/answer-rewrite/suggestions", response_model=List[AnswerRewriteSuggestionResponse])
async def list_answer_rewrite_suggestions(
    task_id: Optional[int] = None,
    status: Optional[str] = "pending",
    db: AsyncSession = Depends(get_db),
):
    query = select(AnswerRewriteSuggestion).order_by(AnswerRewriteSuggestion.id.desc())
    if task_id:
        query = query.where(AnswerRewriteSuggestion.task_id == task_id)
    if status:
        query = query.where(AnswerRewriteSuggestion.status == status)
    result = await db.execute(query.limit(500))
    suggestions = result.scalars().all()

    items = []
    for s in suggestions:
        q = (
            await db.execute(select(Question).where(Question.id == s.question_id))
        ).scalar_one_or_none()
        items.append(
            AnswerRewriteSuggestionResponse(
                id=s.id,
                task_id=s.task_id,
                question_id=s.question_id,
                question_number=q.question_number if q else None,
                question_content=(q.content or "")[:200] if q else None,
                exam_paper_id=q.exam_paper_id if q else None,
                original_answer=s.original_answer,
                suggested_answer=s.suggested_answer,
                confidence=s.confidence,
                detail=s.detail,
                status=s.status,
            )
        )
    return items


@router.post("/answer-rewrite/confirm")
async def confirm_answer_rewrite(
    data: AnswerRewriteConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """确认图片答案转写建议：accept 写入答案 / reject 丢弃。"""
    accepted = 0
    rejected = 0
    for item in data.items:
        result = await db.execute(
            select(AnswerRewriteSuggestion).where(
                AnswerRewriteSuggestion.id == item.suggestion_id
            )
        )
        sug = result.scalar_one_or_none()
        if not sug or sug.status != "pending":
            continue
        if item.action == "reject":
            sug.status = "rejected"
            rejected += 1
            continue
        if item.action == "accept":
            q = (
                await db.execute(select(Question).where(Question.id == sug.question_id))
            ).scalar_one_or_none()
            if q and sug.suggested_answer is not None:
                q.answer = sug.suggested_answer
            sug.status = "accepted"
            accepted += 1
            continue
        raise HTTPException(status_code=400, detail=f"不支持的操作: {item.action}")
    await db.commit()
    return {
        "message": "确认完成",
        "accepted": accepted,
        "rejected": rejected,
    }


@router.post("/ability-label/start", response_model=AbilityLabelTaskResponse)
async def start_ability_label(
    data: AbilityLabelStartRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """启动能力维度 AI 标注任务：仅生成建议，需人工确认后写入。"""
    if not data.exam_paper_id and not data.question_ids and not data.only_unlabeled and not data.bank_type:
        raise HTTPException(status_code=400, detail="请指定标注范围")
    task = AbilityLabelTask(
        status="pending",
        progress=0,
        scope={
            "exam_paper_id": data.exam_paper_id,
            "question_ids": data.question_ids,
            "bank_type": data.bank_type,
            "only_unlabeled": data.only_unlabeled,
        },
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    from app.services.ability_label_service import run_ability_label_task
    background_tasks.add_task(run_ability_label_task, task.id)
    return AbilityLabelTaskResponse.model_validate(task, from_attributes=True)


@router.get("/ability-label/tasks/{task_id}", response_model=AbilityLabelTaskResponse)
async def get_ability_label_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AbilityLabelTask).where(AbilityLabelTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return AbilityLabelTaskResponse.model_validate(task, from_attributes=True)


@router.get("/ability-label/suggestions", response_model=List[AbilityLabelSuggestionResponse])
async def list_ability_label_suggestions(
    task_id: Optional[int] = None,
    status: Optional[str] = "pending",
    db: AsyncSession = Depends(get_db),
):
    query = select(AbilityLabelSuggestion).order_by(AbilityLabelSuggestion.id.desc())
    if task_id:
        query = query.where(AbilityLabelSuggestion.task_id == task_id)
    if status:
        query = query.where(AbilityLabelSuggestion.status == status)
    result = await db.execute(query.limit(500))
    suggestions = result.scalars().all()
    items = []
    for s in suggestions:
        q = (
            await db.execute(select(Question).where(Question.id == s.question_id))
        ).scalar_one_or_none()
        items.append(
            AbilityLabelSuggestionResponse(
                id=s.id,
                task_id=s.task_id,
                question_id=s.question_id,
                question_number=q.question_number if q else None,
                question_content=(q.content or "")[:200] if q else None,
                current_dimension=q.ability_dimension if q else None,
                suggested_dimension=s.suggested_dimension,
                confidence=s.confidence,
                reason=s.reason,
                status=s.status,
                final_dimension=s.final_dimension,
            )
        )
    return items


@router.post("/ability-label/confirm")
async def confirm_ability_label(
    data: AbilityLabelConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """确认能力维度标注：accept / reject / modify。"""
    accepted = 0
    rejected = 0
    modified = 0
    for item in data.items:
        sug = (
            await db.execute(
                select(AbilityLabelSuggestion).where(
                    AbilityLabelSuggestion.id == item.suggestion_id
                )
            )
        ).scalar_one_or_none()
        if not sug or sug.status != "pending":
            continue
        if item.action == "reject":
            sug.status = "rejected"
            rejected += 1
            continue
        dim = item.ability_dimension if item.action == "modify" else sug.suggested_dimension
        if not dim or dim not in ABILITY_DIMENSIONS:
            sug.status = "rejected"
            rejected += 1
            continue
        q = (
            await db.execute(select(Question).where(Question.id == sug.question_id))
        ).scalar_one_or_none()
        if q:
            q.ability_dimension = dim
        sug.final_dimension = dim
        sug.status = "modified" if item.action == "modify" else "accepted"
        if item.action == "modify":
            modified += 1
        else:
            accepted += 1
    await db.commit()
    return {
        "message": "确认完成",
        "accepted": accepted,
        "rejected": rejected,
        "modified": modified,
    }


@router.get("/{question_id}", response_model=QuestionResponse)
async def get_question(question_id: int, db: AsyncSession = Depends(get_db)):
    """获取单个题目详情"""
    result = await db.execute(select(Question).where(Question.id == question_id))
    q = result.scalar_one_or_none()
    if not q:
        raise HTTPException(status_code=404, detail="题目不存在")
    return await _enrich_question(db, q)


@router.post("/", response_model=QuestionResponse)
async def create_question(data: QuestionCreate, db: AsyncSession = Depends(get_db)):
    """手动创建题目"""
    question = Question(**data.model_dump())
    db.add(question)
    await db.commit()
    await db.refresh(question)
    return await _enrich_question(db, question)


@router.put("/{question_id}", response_model=QuestionResponse)
async def update_question(question_id: int, data: QuestionUpdate, db: AsyncSession = Depends(get_db)):
    """更新题目"""
    result = await db.execute(select(Question).where(Question.id == question_id))
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    update_data = data.model_dump(exclude_unset=True)
    if "primary_kp_id" in update_data:
        pid = update_data["primary_kp_id"]
        if pid:
            kp = (await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.id == pid)
            )).scalar_one_or_none()
            if not kp:
                raise HTTPException(status_code=400, detail="主知识点不存在")
            # 同步旧字段；手动改挂载记为人工
            ids = list(question.knowledge_point_ids or [])
            if pid not in ids:
                ids = [pid] + [x for x in ids if x != pid]
                update_data["knowledge_point_ids"] = ids
            if question.primary_kp_id != pid:
                update_data["primary_kp_confidence"] = "manual"
        else:
            update_data["primary_kp_confidence"] = None
    for key, value in update_data.items():
        setattr(question, key, value)
    await db.commit()
    await db.refresh(question)
    return await _enrich_question(db, question)


@router.delete("/{question_id}")
async def delete_question(question_id: int, db: AsyncSession = Depends(get_db)):
    """删除题目"""
    result = await db.execute(select(Question).where(Question.id == question_id))
    question = result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    paper_id = question.exam_paper_id
    await db.execute(delete(KpLinkSuggestion).where(KpLinkSuggestion.question_id == question_id))
    await db.execute(
        delete(AnswerRewriteSuggestion).where(AnswerRewriteSuggestion.question_id == question_id)
    )
    await db.execute(
        delete(AbilityLabelSuggestion).where(AbilityLabelSuggestion.question_id == question_id)
    )
    await db.delete(question)
    if paper_id:
        paper = (
            await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
        ).scalar_one_or_none()
        if paper:
            cnt = await db.scalar(
                select(func.count()).select_from(Question).where(Question.exam_paper_id == paper_id)
            )
            paper.total_questions = int(cnt or 0)
    await db.commit()
    return {"message": "已删除"}


@router.post("/batch-delete")
async def batch_delete_questions(
    data: BatchDeleteQuestionsRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量删除选中题目"""
    ids = [int(i) for i in (data.question_ids or []) if i]
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的题目")
    result = await db.execute(select(Question).where(Question.id.in_(ids)))
    qs = list(result.scalars().all())
    if not qs:
        raise HTTPException(status_code=404, detail="未找到可删除的题目")
    found_ids = [q.id for q in qs]
    paper_ids = {q.exam_paper_id for q in qs if q.exam_paper_id}
    await db.execute(delete(KpLinkSuggestion).where(KpLinkSuggestion.question_id.in_(found_ids)))
    await db.execute(
        delete(AnswerRewriteSuggestion).where(AnswerRewriteSuggestion.question_id.in_(found_ids))
    )
    await db.execute(
        delete(AbilityLabelSuggestion).where(AbilityLabelSuggestion.question_id.in_(found_ids))
    )
    for q in qs:
        await db.delete(q)
    for paper_id in paper_ids:
        paper = (
            await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
        ).scalar_one_or_none()
        if paper:
            cnt = await db.scalar(
                select(func.count()).select_from(Question).where(Question.exam_paper_id == paper_id)
            )
            paper.total_questions = int(cnt or 0)
    await db.commit()
    return {"message": f"已删除 {len(qs)} 题", "deleted": len(qs)}

# ==================== 后台解析任务 ====================

async def _parse_paper_background(paper_id: int, file_path: str):
    """后台异步解析试卷Word文件"""
    from app.services.word_parser import parse_exam_word

    async with async_session() as db:
        result = await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
        paper = result.scalar_one_or_none()
        if not paper:
            return

        try:
            paper.parse_status = "parsing"
            await db.commit()

            # 图片保存目录
            image_dir = os.path.join(settings.UPLOAD_DIR, "papers", f"paper_{paper_id}_images")

            # 解析Word文档
            questions_data = parse_exam_word(file_path, image_dir)

            # 写入数据库
            for q_data in questions_data:
                question = Question(
                    exam_paper_id=paper_id,
                    bank_type=paper.paper_type,
                    question_type=q_data.get("question_type", "answer"),
                    question_number=q_data.get("question_number"),
                    content=q_data.get("content", ""),
                    options=q_data.get("options"),
                    answer=q_data.get("answer"),
                    analysis=q_data.get("analysis"),
                    difficulty=q_data.get("difficulty", 3),
                    score=q_data.get("score"),
                    images=q_data.get("images"),
                    source=paper.source,
                )
                db.add(question)

            paper.total_questions = len(questions_data)
            paper.parse_status = "parsed"
            paper.parse_error = None
            await db.commit()

            logger.info(f"试卷 {paper_id} 解析完成，共 {len(questions_data)} 题")

        except Exception as e:
            logger.error(f"试卷 {paper_id} 解析失败: {e}", exc_info=True)
            paper.parse_status = "failed"
            paper.parse_error = str(e)[:1000]
            await db.commit()


# ==================== 分值方案 / 结构模板 ====================

def _scheme_to_response(s: ExamScoreScheme) -> ExamScoreSchemeResponse:
    return ExamScoreSchemeResponse(
        id=s.id,
        name=s.name,
        exam_type=s.exam_type,
        subject=s.subject,
        region=s.region,
        rules=s.rules or {},
        is_default=bool(s.is_default),
        created_at=s.created_at,
    )


async def _template_to_response(
    db: AsyncSession,
    t: ExamStructureTemplate,
    include_stats: bool = False,
    build_meta: Optional[Dict] = None,
) -> ExamStructureTemplateResponse:
    stats_resp = None
    question_rows = None
    type_structure = tpl_svc.normalize_type_structure_order(t.type_structure)
    if include_stats:
        rows = await db.execute(
            select(ExamKpScoreStat).where(ExamKpScoreStat.template_id == t.id)
        )
        enriched = await tpl_svc.enrich_stats_with_kp_names(db, list(rows.scalars().all()))
        stats_resp = [ExamKpScoreStatResponse(**x) for x in enriched]
        question_rows = await tpl_svc.list_question_detail_rows(db, t.source_paper_ids)
    return ExamStructureTemplateResponse(
        id=t.id,
        name=t.name,
        exam_type=t.exam_type,
        subject=t.subject,
        region=t.region,
        year=t.year,
        source_paper_ids=_coerce_paper_ids(t.source_paper_ids),
        type_structure=type_structure,
        category_score_stats=t.category_score_stats,
        total_score=t.total_score or 0,
        scheme_id=t.scheme_id,
        status=t.status,
        is_default=bool(t.is_default),
        used_temp_scores=bool(t.used_temp_scores),
        created_at=t.created_at,
        updated_at=t.updated_at,
        stats=stats_resp,
        build_meta=build_meta,
        question_rows=question_rows,
    )


@router.get("/score-schemes", response_model=List[ExamScoreSchemeResponse])
async def list_score_schemes(db: AsyncSession = Depends(get_db)):
    await tpl_svc.ensure_default_score_scheme(db)
    result = await db.execute(select(ExamScoreScheme).order_by(ExamScoreScheme.id.asc()))
    return [_scheme_to_response(s) for s in result.scalars().all()]


@router.post("/score-schemes", response_model=ExamScoreSchemeResponse)
async def create_score_scheme(
    data: ExamScoreSchemeCreate,
    db: AsyncSession = Depends(get_db),
):
    if data.is_default:
        others = await db.execute(
            select(ExamScoreScheme).where(
                ExamScoreScheme.subject == data.subject,
                ExamScoreScheme.region == data.region,
                ExamScoreScheme.exam_type == data.exam_type,
                ExamScoreScheme.is_default == 1,
            )
        )
        for o in others.scalars().all():
            o.is_default = 0
    scheme = ExamScoreScheme(
        name=data.name,
        exam_type=data.exam_type,
        subject=data.subject,
        region=data.region,
        rules=data.rules,
        is_default=1 if data.is_default else 0,
    )
    db.add(scheme)
    await db.commit()
    await db.refresh(scheme)
    return _scheme_to_response(scheme)


@router.post("/papers/{paper_id}/apply-score-scheme")
async def apply_score_scheme(
    paper_id: int,
    data: ApplyScoreSchemeRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExamPaper).where(ExamPaper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="试卷不存在")

    if data.scheme_id:
        sres = await db.execute(select(ExamScoreScheme).where(ExamScoreScheme.id == data.scheme_id))
        scheme = sres.scalar_one_or_none()
        if not scheme:
            raise HTTPException(status_code=404, detail="分值方案不存在")
    else:
        scheme = await tpl_svc.ensure_default_score_scheme(db)

    summary = await tpl_svc.apply_score_scheme(db, paper, scheme, overwrite=data.overwrite)
    return {"message": "分值已应用", **summary}


@router.post("/papers/{paper_id}/build-template", response_model=ExamStructureTemplateResponse)
async def build_paper_template(
    paper_id: int,
    data: Optional[BuildTemplateRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """单卷快捷入口（等价于只选这一套）。"""
    data = data or BuildTemplateRequest()
    data.paper_ids = [paper_id]
    return await build_templates_from_papers(data, db)


@router.post("/templates/build", response_model=ExamStructureTemplateResponse)
async def build_templates_from_papers(
    data: BuildTemplateRequest,
    db: AsyncSession = Depends(get_db),
):
    """从用户勾选的一套或多套试卷（真题/模拟题）生成结构模板。"""
    paper_ids = data.paper_ids or []
    if not paper_ids:
        raise HTTPException(status_code=400, detail="请至少选择一套试卷")

    result = await db.execute(select(ExamPaper).where(ExamPaper.id.in_(paper_ids)))
    papers = list(result.scalars().all())
    found = {p.id for p in papers}
    missing = [i for i in paper_ids if i not in found]
    if missing:
        raise HTTPException(status_code=404, detail=f"试卷不存在: {missing}")

    scheme = None
    if data.scheme_id:
        sres = await db.execute(select(ExamScoreScheme).where(ExamScoreScheme.id == data.scheme_id))
        scheme = sres.scalar_one_or_none()
        if not scheme:
            raise HTTPException(status_code=404, detail="分值方案不存在")

    try:
        template = await tpl_svc.build_template_for_papers(db, papers, scheme=scheme)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    meta = getattr(template, "_build_meta", None)
    return await _template_to_response(db, template, include_stats=True, build_meta=meta)


@router.get("/templates", response_model=List[ExamStructureTemplateResponse])
async def list_templates(
    subject: Optional[str] = None,
    region: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(ExamStructureTemplate).order_by(ExamStructureTemplate.updated_at.desc())
    if subject:
        query = query.where(ExamStructureTemplate.subject == subject)
    if region:
        query = query.where(ExamStructureTemplate.region == region)
    result = await db.execute(query)
    out: List[ExamStructureTemplateResponse] = []
    for t in result.scalars().all():
        try:
            out.append(await _template_to_response(db, t, include_stats=False))
        except Exception as e:
            logger.warning("跳过无法序列化的模板 id=%s: %s", t.id, e)
    return out


def _coerce_paper_ids(raw: Any) -> List[int]:
    """兼容 JSON 列被读成 list / 字符串 '[1,2]' 的情况。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        import json
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


@router.get("/templates/latest-average", response_model=ExamStructureTemplateResponse)
async def get_latest_average_template(db: AsyncSession = Depends(get_db)):
    """最近一份多套平均结构模板（来源卷 ≥ 2）。"""
    all_tpl = (await db.execute(
        select(ExamStructureTemplate).order_by(ExamStructureTemplate.updated_at.desc())
    )).scalars().all()
    for t in all_tpl:
        if len(_coerce_paper_ids(t.source_paper_ids)) >= 2:
            return await _template_to_response(db, t, include_stats=True)
    raise HTTPException(
        status_code=404,
        detail="暂无平均模板，请先勾选多套试卷并点击「从所选试卷生成模板」",
    )


@router.get("/templates/by-source", response_model=ExamStructureTemplateResponse)
async def get_template_by_source_papers(
    paper_ids: str = Query(..., description="逗号分隔的试卷ID，如 1,2"),
    db: AsyncSession = Depends(get_db),
):
    """按来源卷组合查找已生成的模板（用于「查看平均模板」）。"""
    try:
        ids = tpl_svc._normalize_paper_ids(
            [int(x.strip()) for x in paper_ids.split(",") if x.strip()]
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="paper_ids 格式无效")
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="查看平均模板请至少指定两套试卷")

    all_tpl = (await db.execute(
        select(ExamStructureTemplate).order_by(ExamStructureTemplate.updated_at.desc())
    )).scalars().all()
    for t in all_tpl:
        stored = _coerce_paper_ids(t.source_paper_ids)
        if tpl_svc._paper_ids_match(stored, ids):
            return await _template_to_response(db, t, include_stats=True)
    raise HTTPException(
        status_code=404,
        detail="尚未生成该组合的平均模板，请先勾选试卷并点击「从所选试卷生成模板」",
    )


@router.get("/templates/{template_id}", response_model=ExamStructureTemplateResponse)
async def get_template(template_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExamStructureTemplate).where(ExamStructureTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return await _template_to_response(db, template, include_stats=True)


@router.post("/templates/{template_id}/set-default", response_model=ExamStructureTemplateResponse)
async def set_default_template(template_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExamStructureTemplate).where(ExamStructureTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        template = await tpl_svc.set_default_template(db, template)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _template_to_response(db, template, include_stats=True)


@router.post("/templates/{template_id}/unset-default", response_model=ExamStructureTemplateResponse)
async def unset_default_template(template_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExamStructureTemplate).where(ExamStructureTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    template = await tpl_svc.unset_default_template(db, template)
    return await _template_to_response(db, template, include_stats=False)


@router.delete("/templates/{template_id}")
async def delete_template(template_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExamStructureTemplate).where(ExamStructureTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    if template.is_default:
        raise HTTPException(status_code=400, detail="请先取消默认后再删除")
    await db.execute(delete(ExamKpScoreStat).where(ExamKpScoreStat.template_id == template_id))
    await db.execute(delete(ExamStructureTemplate).where(ExamStructureTemplate.id == template_id))
    await db.commit()
    return {"message": "模板已删除", "id": template_id}


@router.post("/ai-generate")
async def ai_generate_questions(
    data: AIGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """调用 LLM 为指定知识点生成题目（不入库，返回给前端审核编辑）"""
    from app.services.ai_question_service import generate_questions as ai_gen

    try:
        items = await ai_gen(
            db=db,
            kp_id=data.kp_id,
            question_type=data.question_type,
            count=data.count,
            sample_ids=data.sample_ids,
            difficulty=data.difficulty,
        )
        return AIGenerateResponse(
            questions=[AIGeneratedQuestionItem(**q) for q in items]
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
