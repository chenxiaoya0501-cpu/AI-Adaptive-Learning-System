"""学生端资产只读：章节目录、就绪状态（不含题目答案/解析）"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_student
from app.database import get_db
from app.models.chapter import TextbookChapter
from app.models.knowledge import KnowledgePoint
from app.models.question import ExamPaper, Question
from app.models.system import UploadedFile
from app.models.user import User
from app.services.learning.chapter_kp import kp_counts_for_chapters
from app.services.exam_template_service import has_default_ready_template

router = APIRouter(prefix="/assets")


async def compute_readiness(db: AsyncSession) -> Dict[str, Any]:
    chapter_count = (
        await db.execute(
            select(func.count()).select_from(TextbookChapter).where(
                TextbookChapter.level == "chapter"
            )
        )
    ).scalar() or 0

    published_kp = (
        await db.execute(
            select(func.count()).select_from(KnowledgePoint).where(
                KnowledgePoint.status.in_(["published", "reviewed"])
            )
        )
    ).scalar() or 0

    real_q_total = (
        await db.execute(
            select(func.count()).select_from(Question).where(Question.bank_type == "real")
        )
    ).scalar() or 0

    linked_q = (
        await db.execute(
            select(func.count()).select_from(Question).where(
                Question.bank_type == "real",
                Question.primary_kp_id.isnot(None),
            )
        )
    ).scalar() or 0

    link_rate = (linked_q / real_q_total) if real_q_total else 0.0
    has_default_template = await has_default_ready_template(db, subject="数学")

    reasons = []  # type: List[str]
    if chapter_count <= 0:
        reasons.append("尚未建设教材章节目录")
    if published_kp <= 0:
        reasons.append("暂无已发布/已审核的知识点")
    if real_q_total <= 0:
        reasons.append("暂无真题题目")
    elif link_rate < 0.5:
        reasons.append("真题主知识点挂载率偏低（{:.0%}）".format(link_rate))
    if not has_default_template:
        reasons.append("尚未配置默认真题结构模板")

    ready = (
        chapter_count > 0
        and published_kp > 0
        and real_q_total > 0
        and link_rate >= 0.5
        and has_default_template
    )

    return {
        "ready_for_diagnostic": ready,
        "chapter_count": chapter_count,
        "published_knowledge_point_count": published_kp,
        "real_question_total": real_q_total,
        "real_question_linked": linked_q,
        "link_rate": round(link_rate, 4),
        "has_default_template": has_default_template,
        "reasons": reasons if not ready else [],
        "message": "资产已就绪，可正式测评" if ready else "题库/模板建设中，暂不可正式测评（仍可设置学习目标）",
    }


@router.get("/readiness")
async def asset_readiness(
    _: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await compute_readiness(db)


def _parse_grade_stage(grade_stage: Optional[str]):
    """
    解析「九年级下」→ (年级别名列表, 学期或 None)。
    「九年级全册」→ 学期为 None（该年级上下册都可）。
    """
    if not grade_stage:
        return None, None
    s = grade_stage.strip()
    grade_name = None
    for name in ("七年级", "八年级", "九年级"):
        if name in s:
            grade_name = name
            break
    if not grade_name:
        return None, None

    num = {"七年级": "7", "八年级": "8", "九年级": "9"}[grade_name]
    aliases = [grade_name, num]

    if "全册" in s:
        semester = None
    elif "下" in s:
        semester = "下"
    elif "上" in s:
        semester = "上"
    else:
        semester = None
    return aliases, semester


def _norm_sem(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip()
    if "下" in v:
        return "下"
    if "上" in v:
        return "上"
    return v or None


def _match_grade_value(value: Optional[str], aliases: List[str]) -> bool:
    if value is None:
        return False
    raw = str(value).strip()
    if raw in aliases:
        return True
    for a in aliases:
        if a and a in raw:
            return True
    return False


def _file_matches_stage(f: UploadedFile, aliases: List[str], semester: Optional[str]) -> bool:
    name = f.original_name or f.filename or ""
    grade_ok = _match_grade_value(f.grade, aliases) or any(a in name for a in aliases if len(a) > 1)
    if not grade_ok:
        return False
    if semester is None:
        return True
    file_sem = _norm_sem(f.semester)
    if file_sem:
        return file_sem == semester
    # 学期字段空时用文件名兜底：上册/下册
    if semester == "上" and ("上册" in name or "上学期" in name):
        return True
    if semester == "下" and ("下册" in name or "下学期" in name):
        return True
    if "上册" not in name and "下册" not in name:
        return True
    return False


def _chapter_matches_stage(ch: TextbookChapter, aliases: List[str], semester: Optional[str]) -> bool:
    if ch.grade and not _match_grade_value(ch.grade, aliases):
        return False
    if semester is None:
        return True
    ch_sem = _norm_sem(ch.semester)
    if ch_sem is None:
        return True
    return ch_sem == semester


@router.get("/chapters")
async def list_chapter_trees(
    grade: Optional[str] = Query(None, description="兼容旧参数，如 九年级"),
    grade_stage: Optional[str] = Query(None, description="如 九年级下 / 八年级上 / 九年级全册"),
    _: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """只读章节目录树（供目标设定勾选已学章节）；可按年级阶段过滤。"""
    stage = grade_stage or grade
    aliases, semester = _parse_grade_stage(stage) if stage else (None, None)
    # 旧参数仅年级名时：semester 保持 None
    if grade and not grade_stage and aliases is None:
        # 尝试把「九年级」当全册
        aliases, semester = _parse_grade_stage(grade + "全册") if grade else (None, None)
        if aliases is None and grade:
            aliases, semester = ([grade], None)

    chapter_file_ids = list(
        (await db.execute(select(TextbookChapter.uploaded_file_id).distinct())).scalars().all()
    )
    if not chapter_file_ids:
        return []

    file_q = select(UploadedFile).where(UploadedFile.id.in_(chapter_file_ids))
    files = (await db.execute(file_q.order_by(UploadedFile.id.desc()))).scalars().all()

    trees = []  # type: List[Dict[str, Any]]
    for f in files:
        if aliases and not _file_matches_stage(f, aliases, semester):
            continue

        ch_q = select(TextbookChapter).where(TextbookChapter.uploaded_file_id == f.id)
        chapters = (
            await db.execute(ch_q.order_by(TextbookChapter.sort_order, TextbookChapter.id))
        ).scalars().all()
        if aliases:
            chapters = [c for c in chapters if _chapter_matches_stage(c, aliases, semester)]
        if not chapters:
            continue

        # 若过滤后只剩节、父章被滤掉，保留仍在列表中的节点建树
        id_set = {c.id for c in chapters}
        by_parent = {}  # type: Dict[Optional[int], List[TextbookChapter]]
        for c in chapters:
            parent = c.parent_id if c.parent_id in id_set else None
            by_parent.setdefault(parent, []).append(c)

        kp_map = await kp_counts_for_chapters(db, chapters)

        def build(parent_id):
            # type: (Optional[int]) -> List[Dict[str, Any]]
            nodes = []
            for c in by_parent.get(parent_id, []):
                nodes.append(
                    {
                        "id": c.id,
                        "title": c.title,
                        "level": c.level,
                        "grade": c.grade,
                        "semester": c.semester,
                        "sort_order": c.sort_order,
                        "kp_count": kp_map.get(c.id, 0),
                        "children": build(c.id),
                    }
                )
            return nodes

        grade_label = f.grade or (chapters[0].grade if chapters else None)
        semester_label = f.semester or (chapters[0].semester if chapters else None)
        trees.append(
            {
                "uploaded_file_id": f.id,
                "filename": f.original_name or f.filename,
                "grade": grade_label,
                "semester": semester_label,
                "nodes": build(None),
            }
        )
    return trees


@router.get("/summary")
async def asset_summary(
    _: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    papers = (
        await db.execute(
            select(func.count()).select_from(ExamPaper).where(ExamPaper.parse_status == "parsed")
        )
    ).scalar() or 0
    readiness = await compute_readiness(db)
    return {
        "parsed_papers": papers,
        "readiness": readiness,
    }
