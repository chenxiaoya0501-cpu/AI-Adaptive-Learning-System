"""章节标题 ↔ 知识点 chapter 字段匹配（与 Admin 章节页口径对齐）"""
import re
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chapter import TextbookChapter
from app.models.knowledge import KnowledgePoint

# 学段顺序：当前年级阶段之前的册次视为「已全部学完」
GRADE_STAGE_ORDER = [
    "七年级上",
    "七年级下",
    "八年级上",
    "八年级下",
    "九年级上",
    "九年级下",
]


def re_sub_chapter_prefix(title: str) -> str:
    t = re.sub(r"^第[一二三四五六七八九十百零\d]+章\s*", "", title or "")
    return t.strip()


def normalize_chapter_title(s: str) -> str:
    """统一空白：全角空格/不间断空格 → 半角，再压缩连续空白。"""
    if not s:
        return ""
    s = s.replace("\u3000", " ").replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", s)


async def query_related_kps(
    db: AsyncSession, title: str, level: str, limit: int = 200
) -> List[KnowledgePoint]:
    """章：规范化空白后完整章标题相等（兼容全角/半角空格差异）。"""
    raw = (title or "").strip()
    if not raw or level != "chapter":
        return []
    target = normalize_chapter_title(raw)
    if not target:
        return []

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
        ch = normalize_chapter_title(kp.chapter or "")
        if not ch:
            continue
        if ch == target or ch.startswith(target + ";") or ch.startswith(target + "；"):
            matched.append(kp)
        elif ";" in ch or "；" in ch:
            parts = re.split(r"[;；]", ch)
            if any(normalize_chapter_title(p) == target for p in parts):
                matched.append(kp)
    return matched[:limit]

async def count_related_kps(db: AsyncSession, title: str, level: str) -> int:
    return len(await query_related_kps(db, title, level))


async def expand_chapter_ids_to_kp_ids(
    db: AsyncSession, chapter_ids: List[int]
) -> List[str]:
    """勾选章节 → 知识点 ID 集合（去重保序）。"""
    if not chapter_ids:
        return []
    chapters = (
        await db.execute(
            select(TextbookChapter).where(TextbookChapter.id.in_(chapter_ids))
        )
    ).scalars().all()
    seen: Set[str] = set()
    ordered: List[str] = []
    for ch in chapters:
        level = ch.level or "chapter"
        # 仅章参与展开关联；节不按标题模糊挂知识点
        if level != "chapter":
            continue
        for kp in await query_related_kps(db, ch.title, level):
            if kp.id not in seen:
                seen.add(kp.id)
                ordered.append(kp.id)
    return ordered


def normalize_grade_stage(grade_stage: Optional[str]) -> Optional[str]:
    """「九年级上」「九年级上册」等 → GRADE_STAGE_ORDER 中的标准名。"""
    if not grade_stage:
        return None
    s = grade_stage.strip()
    grade_name = None
    for name in ("七年级", "八年级", "九年级"):
        if name in s:
            grade_name = name
            break
    if not grade_name:
        return None
    if "全册" in s:
        # 全册按该年级「下」处理（上下都算已覆盖时用 prior 逻辑另议）
        return grade_name + "下"
    if "下" in s:
        return grade_name + "下"
    if "上" in s:
        return grade_name + "上"
    return None


def prior_grade_stages(grade_stage: Optional[str]) -> List[str]:
    """当前学段之前的全部册次（不含当前）。例：九年级上 → 七上…八下。"""
    cur = normalize_grade_stage(grade_stage)
    if not cur or cur not in GRADE_STAGE_ORDER:
        return []
    idx = GRADE_STAGE_ORDER.index(cur)
    return GRADE_STAGE_ORDER[:idx]


def _parse_stage_to_grade_sem(stage: str) -> Tuple[List[str], str]:
    """「八年级上」→ (年级别名, 学期)。"""
    grade_name = stage[:3]  # 七年级/八年级/九年级
    sem = "下" if stage.endswith("下") else "上"
    num = {"七年级": "7", "八年级": "8", "九年级": "9"}.get(grade_name, "")
    aliases = [grade_name, num] if num else [grade_name]
    return aliases, sem


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


def _norm_sem(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip()
    if "下" in v:
        return "下"
    if "上" in v:
        return "上"
    return v or None


async def chapter_ids_for_grade_stage(db: AsyncSession, grade_stage: str) -> List[int]:
    """某册次下全部章级节点 id。"""
    aliases, semester = _parse_stage_to_grade_sem(grade_stage)
    rows = (
        await db.execute(
            select(TextbookChapter).where(TextbookChapter.level == "chapter")
        )
    ).scalars().all()
    ids: List[int] = []
    for ch in rows:
        if ch.grade and not _match_grade_value(ch.grade, aliases):
            continue
        if not ch.grade:
            # 无年级字段则无法可靠归入先验册次，跳过
            continue
        ch_sem = _norm_sem(ch.semester)
        if ch_sem is not None and ch_sem != semester:
            continue
        ids.append(ch.id)
    return ids


async def expand_learned_scope_to_kp_ids(
    db: AsyncSession,
    grade_stage: Optional[str],
    selected_chapter_ids: List[int],
) -> List[str]:
    """
    已学范围 → 知识点：
    - 当前年级阶段之前的各册（七/八…）全部章 → 知识点
    - 再加上用户在本册勾选的章 → 知识点
    例：九年级上勾了前几章 ⇒ 七上～八下全覆盖 + 九年级上已勾章。
    """
    chapter_ids: List[int] = []
    for st in prior_grade_stages(grade_stage):
        chapter_ids.extend(await chapter_ids_for_grade_stage(db, st))
    chapter_ids.extend(selected_chapter_ids or [])
    # 去重保序
    chapter_ids = list(dict.fromkeys(chapter_ids))
    return await expand_chapter_ids_to_kp_ids(db, chapter_ids)


async def kp_counts_for_chapters(
    db: AsyncSession, chapters: List[TextbookChapter]
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for ch in chapters:
        level = ch.level or "chapter"
        if level != "chapter":
            out[ch.id] = 0
        else:
            out[ch.id] = await count_related_kps(db, ch.title, level)
    return out
