"""动态组卷：平均模板 π(k,t) × 已学集合 L → 快照卷"""
from __future__ import annotations

import asyncio
import math
import random
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint
from app.models.question import ExamKpScoreStat, ExamScoreScheme, ExamStructureTemplate, Question
from app.models.student.goal import LearningGoal
from app.models.student.test_paper import TestAnswer, TestPaper, TestQuestion
from app.schemas.student.test import (
    AssemblePreview,
    TestPaperDetail,
    TestPaperSummary,
    TestQuestionPublic,
    TypeStructureItem,
)
from app.services.learning import goal_service
from app.services.learning.chapter_kp import expand_learned_scope_to_kp_ids
from app.services.exam_template_service import (
    ZHEJIANG_ZHONGKAO_MATH_RULES,
    _rule_for_type,
    ensure_default_score_scheme,
)

ALGORITHM_VERSION = "v1"
DEFAULT_LAMBDA = 0.35
TYPE_ORDER = ("choice", "fill", "answer", "proof")
# 正式环境优先 published/reviewed；当前题库多为 draft，已挂主知识点的 draft 亦可入池
POOL_STATUSES = ("published", "reviewed", "draft")

_assemble_locks: Dict[int, asyncio.Lock] = {}


def _user_lock(user_id: int) -> asyncio.Lock:
    lock = _assemble_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _assemble_locks[user_id] = lock
    return lock


def map_exam_type(exam_type: str) -> str:
    t = (exam_type or "").strip()
    if t in ("中考", "zhongkao"):
        return "zhongkao"
    if t in ("高考", "gaokao"):
        return "gaokao"
    return "zhongkao"


def largest_remainder(weights: Dict[str, float], n: int) -> Dict[str, int]:
    """将权重分配为整数，使总和 = n。"""
    if n <= 0 or not weights:
        return {k: 0 for k in weights}
    total_w = sum(max(0.0, w) for w in weights.values())
    if total_w <= 0:
        keys = list(weights.keys())
        base = {k: 0 for k in keys}
        for i in range(n):
            base[keys[i % len(keys)]] += 1
        return base

    raw = {k: n * max(0.0, w) / total_w for k, w in weights.items()}
    floors = {k: int(math.floor(v)) for k, v in raw.items()}
    rem = n - sum(floors.values())
    order = sorted(
        raw.keys(),
        key=lambda k: (raw[k] - floors[k], weights.get(k, 0)),
        reverse=True,
    )
    for i in range(rem):
        floors[order[i % len(order)]] += 1
    return floors


def _is_average_template(tpl: ExamStructureTemplate) -> bool:
    """多套来源卷生成的平均结构模板（非单卷「本卷模板」）。"""
    ids = tpl.source_paper_ids or []
    return isinstance(ids, list) and len(ids) >= 2


async def resolve_template(
    db: AsyncSession,
    subject: str,
    region: Optional[str],
    exam_type: str,
    template_id: Optional[int] = None,
) -> ExamStructureTemplate:
    """
    选择顺序：
    1. 指定 template_id
    2. 考区默认 ready
    3. 多套「平均结构模板」ready（优先于单卷模板）
    4. 多套平均模板（含 incomplete，仍优先用平均结构）
    5. 任意 ready 单卷模板
    6. 最近任意模板
    """
    if template_id:
        tpl = (
            await db.execute(
                select(ExamStructureTemplate).where(ExamStructureTemplate.id == template_id)
            )
        ).scalar_one_or_none()
        if tpl is None:
            raise HTTPException(status_code=404, detail="结构模板不存在")
        return tpl

    et = map_exam_type(exam_type)
    region = region or "浙江"

    q_base = select(ExamStructureTemplate).where(
        ExamStructureTemplate.subject == subject,
        ExamStructureTemplate.exam_type == et,
    )
    all_tpl = (
        await db.execute(q_base.order_by(ExamStructureTemplate.updated_at.desc()))
    ).scalars().all()

    def _region_ok(t: ExamStructureTemplate, reg: Optional[str]) -> bool:
        if not reg:
            return True
        return (t.region or "") == reg or reg in (t.region or "")

    def _pick(pred):
        for reg in (region, "浙江", None):
            for t in all_tpl:
                if _region_ok(t, reg) and pred(t):
                    return t
        return None

    tpl = _pick(lambda t: t.is_default == 1 and t.status == "ready")
    if tpl:
        return tpl
    # 平均模板优先（解答题多为 8 题那套），避免误用「2023 单卷 · 7 道解答」
    tpl = _pick(lambda t: _is_average_template(t) and t.status == "ready")
    if tpl:
        return tpl
    tpl = _pick(lambda t: _is_average_template(t))
    if tpl:
        return tpl
    tpl = _pick(lambda t: t.status == "ready")
    if tpl:
        return tpl
    if all_tpl:
        return all_tpl[0]
    raise HTTPException(
        status_code=400,
        detail="暂无可用结构模板，请先在管理端勾选多套试卷生成平均模板，并设为默认",
    )


def parse_type_structure(raw: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not raw:
        return items
    for row in raw:
        if not isinstance(row, dict):
            continue
        qt = row.get("question_type") or row.get("type")
        if not qt:
            continue
        count = int(row.get("count") or 0)
        subtotal = float(row.get("subtotal") or 0)
        score_each = row.get("score_each")
        if score_each is None and count > 0 and subtotal > 0:
            score_each = subtotal / count
        items.append(
            {
                "question_type": str(qt),
                "count": count,
                "subtotal": subtotal,
                "score_each": float(score_each) if score_each is not None else None,
            }
        )
    # 稳定顺序
    order_idx = {t: i for i, t in enumerate(TYPE_ORDER)}
    items.sort(key=lambda x: order_idx.get(x["question_type"], 99))
    return items


async def load_pi_kt(
    db: AsyncSession, template_id: int
) -> Dict[str, Dict[str, float]]:
    """返回 {question_type: {kp_id: score_ratio}}，仅题型维度 π(k,t)。"""
    rows = (
        await db.execute(
            select(ExamKpScoreStat).where(
                ExamKpScoreStat.template_id == template_id,
                ExamKpScoreStat.question_type.isnot(None),
            )
        )
    ).scalars().all()
    out: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in rows:
        qt = str(r.question_type)
        ratio = float(r.score_ratio or 0)
        if ratio < 0:
            ratio = 0
        # 多行同 KP 取较大值（一般唯一）
        out[qt][r.kp_id] = max(out[qt].get(r.kp_id, 0.0), ratio)
    return out


async def kp_category_map(db: AsyncSession, kp_ids: Set[str]) -> Dict[str, str]:
    if not kp_ids:
        return {}
    rows = (
        await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(list(kp_ids))))
    ).scalars().all()
    return {r.id: (r.category_1 or r.domain or "") for r in rows}


def allocate_quotas(
    type_structure: List[Dict[str, Any]],
    pi_kt: Dict[str, Dict[str, float]],
    learned: Set[str],
    lambda_value: float,
) -> Tuple[Dict[str, Dict[str, int]], List[str], bool]:
    """
    返回 m[question_type][kp_id] = 题数；warnings；degraded（题量是否将在选题阶段可能再降）。
    题型题数 n_t 与题型总分 S_t 保持模板不变；已学 KP 占比同比例放大（重归一）后再混 λ。
    """
    warnings: List[str] = []
    quotas: Dict[str, Dict[str, int]] = {}
    L = list(learned)
    if not L:
        raise HTTPException(status_code=400, detail="已学知识点为空，请先勾选已学章节")

    for ts in type_structure:
        qt = ts["question_type"]
        n_t = int(ts["count"] or 0)
        if n_t <= 0:
            continue
        S_t = float(ts["subtotal"] or 0)
        s_each = ts.get("score_each")
        if not s_each or s_each <= 0:
            s_each = S_t / n_t if n_t else 1.0
        if S_t <= 0:
            S_t = s_each * n_t

        pi_all = pi_kt.get(qt) or {}
        # 裁剪到 L 并同比例放大
        clipped = {k: pi_all[k] for k in L if pi_all.get(k, 0) > 0}
        sum_clip = sum(clipped.values())
        if sum_clip > 1e-12:
            hat = {k: v / sum_clip for k, v in clipped.items()}
            # 对 L 中模板占比为 0 的点：先不分配，仅靠 λ 均匀项覆盖
            for k in L:
                hat.setdefault(k, 0.0)
        else:
            hat = {k: 1.0 / len(L) for k in L}
            warnings.append("题型「{}」在模板中无已学知识点占比，已改为在已学范围内均匀出题".format(qt))

        # G = S_t * hat；G' = (1-λ)G + λ*S_t/|L|；再归一到 S_t
        g_prime: Dict[str, float] = {}
        for k in L:
            g = S_t * hat.get(k, 0.0)
            g_prime[k] = (1.0 - lambda_value) * g + lambda_value * (S_t / len(L))
        g_sum = sum(g_prime.values())
        if g_sum <= 0:
            g_prime = {k: S_t / len(L) for k in L}
        else:
            g_prime = {k: v * S_t / g_sum for k, v in g_prime.items()}

        # 按分值配额 → 题数（Largest Remainder），权重用 G'/s_each
        weights = {k: g_prime[k] / s_each for k in L}
        m = largest_remainder(weights, n_t)
        # 去掉 0
        quotas[qt] = {k: c for k, c in m.items() if c > 0}
        # 若因舍入全空（极端），均匀塞
        if sum(quotas[qt].values()) != n_t:
            quotas[qt] = largest_remainder({k: 1.0 for k in L}, n_t)
            quotas[qt] = {k: c for k, c in quotas[qt].items() if c > 0}

    return quotas, warnings, False


def _per_number_ladder(rules: Optional[Dict[str, Any]], qtype: str) -> List[float]:
    if not rules:
        return []
    rule = _rule_for_type(rules, qtype)
    per = (rule or {}).get("per_number") or {}
    if not per:
        return []
    try:
        return [
            float(per[k])
            for k in sorted(per.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        ]
    except (TypeError, ValueError):
        return []


def distribute_exact_total(total: float, n: int) -> List[float]:
    """把 total 拆成 n 份（最多两位小数），总和严格等于 total。"""
    if n <= 0:
        return []
    if total <= 0:
        return [0.0] * n
    cents = int(round(float(total) * 100))
    base, rem = divmod(cents, n)
    out = [(base + (1 if i < rem else 0)) / 100.0 for i in range(n)]
    drift = round(float(total) - sum(out), 2)
    if abs(drift) >= 0.01:
        out[-1] = round(out[-1] + drift, 2)
    return out


def allocate_type_slot_scores(
    ts: Dict[str, Any],
    n: int,
    scheme_rules: Optional[Dict[str, Any]] = None,
) -> List[float]:
    """
    按模板题型小计给本型 n 道题赋分（不用题库原分）。
    - 满题量：总和 = 模板 subtotal
    - 题源不足降级：仍把该型 subtotal 摊到已抽到的题上，保证卷面总分仍对齐模板
    """
    if n <= 0:
        return []
    qt = str(ts.get("question_type") or "")
    n_full = int(ts.get("count") or 0) or n
    target = float(ts.get("subtotal") or 0)
    score_each = ts.get("score_each")
    if target <= 0 and score_each and float(score_each) > 0:
        target = float(score_each) * n_full
    if target <= 0:
        target = 3.0 * n

    ladder = _per_number_ladder(scheme_rules, qt)
    if ladder and abs(sum(ladder) - target) < 0.05:
        if n == len(ladder):
            return [float(x) for x in ladder]
        # 降级：按梯子权重把 target 摊到 n 题
        weights = ladder[:n] if n <= len(ladder) else ladder + [ladder[-1]] * (n - len(ladder))
        wsum = sum(weights) or 1.0
        cents = int(round(target * 100))
        raw = [cents * w / wsum for w in weights]
        floors = [int(math.floor(v)) for v in raw]
        rem = cents - sum(floors)
        order = sorted(range(n), key=lambda i: raw[i] - floors[i], reverse=True)
        for i in range(rem):
            floors[order[i % n]] += 1
        return [c / 100.0 for c in floors]

    if (
        score_each is not None
        and float(score_each) > 0
        and n == n_full
        and abs(float(score_each) * n_full - target) < 0.05
    ):
        return [float(score_each)] * n

    return distribute_exact_total(target, n)


async def load_scheme_rules(
    db: AsyncSession, tpl: ExamStructureTemplate
) -> Dict[str, Any]:
    """组卷赋分用的分值方案；无则回退浙江中考默认。"""
    if tpl.scheme_id:
        row = (
            await db.execute(
                select(ExamScoreScheme).where(ExamScoreScheme.id == tpl.scheme_id)
            )
        ).scalar_one_or_none()
        if row and row.rules:
            return dict(row.rules)
    try:
        scheme = await ensure_default_score_scheme(db)
        if scheme and scheme.rules:
            return dict(scheme.rules)
    except Exception:
        pass
    return dict(ZHEJIANG_ZHONGKAO_MATH_RULES)


async def fetch_pool(
    db: AsyncSession,
    bank_type: str,
    question_type: str,
    kp_ids: Set[str],
    exclude_ids: Set[int],
) -> List[Question]:
    if not kp_ids:
        return []
    q = select(Question).where(
        Question.bank_type == bank_type,
        Question.question_type == question_type,
        Question.primary_kp_id.in_(list(kp_ids)),
        Question.status.in_(list(POOL_STATUSES)),
    )
    rows = (await db.execute(q)).scalars().all()
    return [r for r in rows if r.id not in exclude_ids]


async def pick_questions(
    db: AsyncSession,
    bank_type: str,
    quotas: Dict[str, Dict[str, int]],
    type_structure: List[Dict[str, Any]],
    learned: Set[str],
    scheme_rules: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[str], bool]:
    """按配额选题；不足时同 category_1 借题；仍不足则降题量。分值一律按模板赋，不用题库原分。"""
    warnings: List[str] = []
    degraded = False
    used: Set[int] = set()
    picked: List[Dict[str, Any]] = []
    cat_map = await kp_category_map(db, learned)

    # 预取各题型全池（已学 KP）
    pool_by_type: Dict[str, List[Question]] = {}
    for ts in type_structure:
        qt = ts["question_type"]
        pool_by_type[qt] = await fetch_pool(db, bank_type, qt, learned, set())

    for ts in type_structure:
        qt = ts["question_type"]
        n_t = int(ts["count"] or 0)
        if n_t <= 0:
            continue

        need = quotas.get(qt) or {}
        type_picked: List[Question] = []

        # 按配额逐 KP
        for kp_id, cnt in sorted(need.items(), key=lambda x: -x[1]):
            if cnt <= 0:
                continue
            candidates = [
                q
                for q in pool_by_type.get(qt, [])
                if q.primary_kp_id == kp_id and q.id not in used
            ]
            random.shuffle(candidates)
            take = candidates[:cnt]
            for q in take:
                used.add(q.id)
                type_picked.append(q)
            shortage = cnt - len(take)
            if shortage <= 0:
                continue
            # 同一级分类借题
            cat = cat_map.get(kp_id, "")
            borrow = [
                q
                for q in pool_by_type.get(qt, [])
                if q.id not in used
                and q.primary_kp_id in learned
                and (not cat or cat_map.get(q.primary_kp_id or "", "") == cat)
            ]
            random.shuffle(borrow)
            for q in borrow[:shortage]:
                used.add(q.id)
                type_picked.append(q)
            if len(borrow) < shortage:
                # 任意已学 KP 补齐
                any_left = [
                    q for q in pool_by_type.get(qt, []) if q.id not in used
                ]
                random.shuffle(any_left)
                still = shortage - min(len(borrow), shortage)
                for q in any_left[:still]:
                    used.add(q.id)
                    type_picked.append(q)

        # 仍不足：从剩余池随机补到 n_t
        if len(type_picked) < n_t:
            rest = [q for q in pool_by_type.get(qt, []) if q.id not in used]
            random.shuffle(rest)
            for q in rest[: n_t - len(type_picked)]:
                used.add(q.id)
                type_picked.append(q)

        if len(type_picked) < n_t:
            degraded = True
            warnings.append(
                "题型「{}」题源不足：需要 {} 题，仅抽到 {} 题".format(
                    qt, n_t, len(type_picked)
                )
            )

        slot_scores = allocate_type_slot_scores(
            ts, len(type_picked), scheme_rules=scheme_rules
        )
        for q, score in zip(type_picked, slot_scores):
            picked.append(
                {
                    "source": q,
                    "question_type": qt,
                    "score": float(score),
                }
            )

    return picked, warnings, degraded


_IMG_PLACEHOLDER_RE = re.compile(r"\[IMG:([^,\]]+)(?:,([\d.]+),([\d.]+))?\]")


def _is_block_image(w_pt: float, h_pt: float) -> bool:
    """区分行内公式 vs 独立示意图（几何/函数图/数轴等）。"""
    if h_pt <= 0 and w_pt <= 0:
        return False
    # 偏高：几何图、坐标系
    if h_pt > 45:
        return True
    # 偏宽：数轴、行程图、宽示意图（即使高度不大）
    if w_pt > 80:
        return True
    # 中等面积的独立图
    if w_pt >= 55 and h_pt >= 28:
        return True
    return False


def expand_img_placeholders(text: Optional[str], exam_paper_id: Optional[int]) -> str:
    """把 [IMG:file,W,H] 转成可直接展示的 <img>；公式与大图分别缩放。"""
    if not text:
        return ""
    if not exam_paper_id:
        return text

    def _repl(m: re.Match[str]) -> str:  # type: ignore[type-arg]
        filename = m.group(1)
        url = f"/uploads/papers/paper_{exam_paper_id}_images/{filename}"
        w_pt = float(m.group(2)) if m.group(2) else 0.0
        h_pt = float(m.group(3)) if m.group(3) else 0.0

        if _is_block_image(w_pt, h_pt):
            # 独立图：可读但不占满整卡
            max_h, max_w = 150.0, 320.0
            scale = 1.25
            if h_pt > 0:
                scale = min(scale, max_h / h_pt)
            if w_pt > 0:
                scale = min(scale, max_w / w_pt)
            disp_h = h_pt * scale if h_pt > 0 else max_h
            disp_w = w_pt * scale if w_pt > 0 else max_w
            cls = "rich-q-img rich-q-img--block"
            style = (
                f"height:{disp_h:.1f}px;width:{disp_w:.1f}px;"
                "display:block;margin:6px 0;max-width:100%"
            )
        elif h_pt > 0 and w_pt > 0:
            # 行内公式：与管理端一致，按 pt×1.5，并限制不超过约一行半
            scale = 1.5
            if h_pt * scale > 30:
                scale = 30 / h_pt
            cls = "rich-q-img rich-q-img--inline"
            style = (
                f"height:{h_pt * scale:.1f}px;width:{w_pt * scale:.1f}px;"
                "vertical-align:middle;margin:0 3px"
            )
        else:
            cls = "rich-q-img rich-q-img--inline"
            style = "max-height:28px;vertical-align:middle;margin:0 3px"
        return f'<img class="{cls}" src="{url}" alt="" style="{style}" />'

    return _IMG_PLACEHOLDER_RE.sub(_repl, text)


def expand_options_images(options: Any, exam_paper_id: Optional[int]) -> Any:
    if not options or not exam_paper_id:
        return options
    if isinstance(options, dict):
        return {
            k: expand_img_placeholders(str(v), exam_paper_id) if v is not None else v
            for k, v in options.items()
        }
    if isinstance(options, list):
        return [
            expand_img_placeholders(str(v), exam_paper_id) if v is not None else v
            for v in options
        ]
    return options


def to_public_question(
    tq: TestQuestion, source_exam_paper_id: Optional[int] = None
) -> TestQuestionPublic:
    paper_id = (
        source_exam_paper_id
        if source_exam_paper_id is not None
        else getattr(tq, "source_exam_paper_id", None)
    )
    return TestQuestionPublic(
        id=tq.id,
        seq=tq.seq,
        question_type=tq.question_type,
        content=expand_img_placeholders(tq.content, paper_id),
        options=expand_options_images(tq.options, paper_id),
        score=float(tq.score or 0),
        primary_kp_id=tq.primary_kp_id,
        images=tq.images,
        difficulty=tq.difficulty,
        source_exam_paper_id=paper_id,
    )


async def resolve_source_exam_paper_ids(
    db: AsyncSession, questions: List[TestQuestion]
) -> Dict[int, Optional[int]]:
    """返回 test_question.id -> source_exam_paper_id，旧快照可回查源题。"""
    out: Dict[int, Optional[int]] = {}
    need_lookup: List[int] = []
    tq_by_source: Dict[int, List[int]] = defaultdict(list)
    for tq in questions:
        sid = getattr(tq, "source_exam_paper_id", None)
        if sid:
            out[tq.id] = sid
        elif tq.source_question_id:
            need_lookup.append(tq.source_question_id)
            tq_by_source[tq.source_question_id].append(tq.id)
        else:
            out[tq.id] = None
    if need_lookup:
        rows = (
            await db.execute(
                select(Question.id, Question.exam_paper_id).where(
                    Question.id.in_(list(set(need_lookup)))
                )
            )
        ).all()
        src_map = {r[0]: r[1] for r in rows}
        for source_id, tq_ids in tq_by_source.items():
            paper_id = src_map.get(source_id)
            for tid in tq_ids:
                out[tid] = paper_id
    return out


def paper_summary(paper: TestPaper, qcount: int) -> TestPaperSummary:
    return TestPaperSummary(
        id=paper.id,
        goal_id=paper.goal_id,
        template_id=paper.template_id,
        paper_kind=paper.paper_kind,
        bank_type=paper.bank_type,
        status=paper.status,
        title=paper.title,
        total_score=float(paper.total_score or 0),
        earned_score=paper.earned_score,
        question_count=qcount,
        degraded=bool(paper.degraded),
        warnings=list(paper.warnings or []),
        created_at=paper.created_at,
    )


async def get_owned_paper(db: AsyncSession, paper_id: int, user_id: int) -> TestPaper:
    paper = (
        await db.execute(
            select(TestPaper).where(TestPaper.id == paper_id, TestPaper.user_id == user_id)
        )
    ).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=404, detail="试卷不存在")
    return paper


async def preview_assemble(
    db: AsyncSession, user_id: int, goal_id: int
) -> AssemblePreview:
    goal = await goal_service.get_owned_goal(db, goal_id, user_id)
    chapter_ids = await goal_service.get_chapter_ids(db, goal.id)
    # 始终按「本册勾选 + 先前册次全学」重算，避免旧缓存偏窄
    kp_ids = await expand_learned_scope_to_kp_ids(db, goal.grade_stage, chapter_ids)

    messages: List[str] = []
    readiness_ok = True
    if not chapter_ids:
        readiness_ok = False
        messages.append("请先勾选已学章节")
    if not kp_ids:
        readiness_ok = False
        messages.append("已学章节未关联到知识点，请检查管理端章节/知识点挂载")

    try:
        tpl = await resolve_template(
            db, goal.subject or "数学", goal.region, goal.exam_type
        )
    except HTTPException as e:
        readiness_ok = False
        messages.append(str(e.detail))
        return AssemblePreview(
            goal_id=goal.id,
            goal_title=goal.title,
            grade_stage=goal.grade_stage,
            region=goal.region,
            learned_chapter_count=len(chapter_ids),
            learned_kp_count=len(kp_ids),
            readiness_ok=False,
            readiness_messages=messages,
        )

    ts = parse_type_structure(tpl.type_structure)
    if tpl.status != "ready":
        messages.append("当前模板状态为 incomplete，组卷可能不够准确")

    return AssemblePreview(
        goal_id=goal.id,
        goal_title=goal.title,
        grade_stage=goal.grade_stage,
        region=goal.region,
        learned_chapter_count=len(chapter_ids),
        learned_kp_count=len(kp_ids),
        template_id=tpl.id,
        template_name=tpl.name,
        template_status=tpl.status,
        total_score=float(tpl.total_score or sum(x["subtotal"] for x in ts)),
        type_structure=[TypeStructureItem(**x) for x in ts],
        readiness_ok=readiness_ok and bool(ts),
        readiness_messages=messages,
    )


async def assemble_paper(
    db: AsyncSession,
    user_id: int,
    goal_id: int,
    bank_type: str = "real",
    lambda_value: Optional[float] = None,
    template_id: Optional[int] = None,
    paper_kind: str = "diagnostic",
) -> TestPaperDetail:
    if bank_type not in ("real", "mock"):
        raise HTTPException(status_code=400, detail="bank_type 须为 real 或 mock")
    lam = DEFAULT_LAMBDA if lambda_value is None else float(lambda_value)
    if lam < 0 or lam > 1:
        raise HTTPException(status_code=400, detail="lambda 须在 0～1")

    lock = _user_lock(user_id)
    if lock.locked():
        raise HTTPException(status_code=429, detail="正在组卷，请勿重复点击")

    async with lock:
        goal = await goal_service.get_owned_goal(db, goal_id, user_id)
        if goal.status == "archived":
            raise HTTPException(status_code=400, detail="已归档目标不可组卷")

        chapter_ids = await goal_service.get_chapter_ids(db, goal.id)
        if not chapter_ids:
            raise HTTPException(status_code=400, detail="请先勾选已学章节后再组卷")

        # 九年级上勾选若干章 ⇒ 自动包含七、八年级全部已学知识点
        kp_ids = await expand_learned_scope_to_kp_ids(db, goal.grade_stage, chapter_ids)
        goal.learned_kp_ids = kp_ids
        learned = set(kp_ids)
        if not learned:
            raise HTTPException(
                status_code=400,
                detail="已学章节范围内没有可出题知识点，请调整已学章节或完善知识点挂载",
            )

        tpl = await resolve_template(
            db,
            goal.subject or "数学",
            goal.region,
            goal.exam_type,
            template_id=template_id,
        )
        type_structure = parse_type_structure(tpl.type_structure)
        if not type_structure:
            raise HTTPException(status_code=400, detail="结构模板缺少题型结构，请在管理端重新生成")

        pi_kt = await load_pi_kt(db, tpl.id)
        scheme_rules = await load_scheme_rules(db, tpl)
        quotas, warn_a, _ = allocate_quotas(type_structure, pi_kt, learned, lam)
        picked, warn_b, degraded = await pick_questions(
            db,
            bank_type,
            quotas,
            type_structure,
            learned,
            scheme_rules=scheme_rules,
        )
        if not picked:
            raise HTTPException(
                status_code=400,
                detail="所选题库在已学知识点范围内没有可用题目（须已挂主知识点；建议在管理端发布题目）",
            )

        warnings = warn_a + warn_b
        # 实际题型结构（分值已按模板小计赋分）
        actual_counts: Dict[str, int] = defaultdict(int)
        actual_sub: Dict[str, float] = defaultdict(float)
        for item in picked:
            actual_counts[item["question_type"]] += 1
            actual_sub[item["question_type"]] += float(item["score"])

        actual_ts = []
        for ts in type_structure:
            qt = ts["question_type"]
            c = actual_counts.get(qt, 0)
            if c <= 0:
                continue
            # 展示用小计对齐模板（与赋分一致）
            sub = round(float(ts.get("subtotal") or actual_sub.get(qt, 0)), 2)
            actual_ts.append(
                {
                    "question_type": qt,
                    "count": c,
                    "subtotal": sub,
                    "score_each": ts.get("score_each"),
                }
            )

        scored_sum = round(sum(float(x["score"]) for x in picked), 2)
        template_total = float(tpl.total_score or 0)
        if template_total <= 0:
            template_total = round(
                sum(float(ts.get("subtotal") or 0) for ts in type_structure), 2
            )
        # 各题型已按模板小计赋分 → 正常情况合计应等于模板总分
        total_score = scored_sum
        if template_total > 0 and abs(scored_sum - template_total) < 0.05:
            total_score = round(template_total, 2)
        elif template_total > 0 and not degraded:
            # 浮点/边界差：微调最后一题，卷面钉死模板总分
            drift = round(template_total - scored_sum, 2)
            if picked and abs(drift) < 5:
                picked[-1]["score"] = round(float(picked[-1]["score"]) + drift, 2)
                total_score = round(template_total, 2)
                warnings.append(
                    f"已校正卷面总分至模板 {total_score:g} 分（原合计 {scored_sum:g}）"
                )
            else:
                warnings.append(
                    f"卷面合计 {scored_sum:g} 与模板总分 {template_total:g} 不一致，请检查模板题型小计"
                )
        bank_label = "真题" if bank_type == "real" else "模拟题"
        title = "{}·{}诊断测评".format(goal.title or "学习目标", bank_label)

        paper = TestPaper(
            user_id=user_id,
            goal_id=goal.id,
            template_id=tpl.id,
            paper_kind=paper_kind or "diagnostic",
            bank_type=bank_type,
            status="assembled",
            title=title,
            total_score=total_score,
            type_structure=actual_ts,
            algorithm_version=ALGORITHM_VERSION,
            lambda_value=lam,
            degraded=degraded,
            warnings=warnings,
        )
        db.add(paper)
        await db.flush()

        # 卷内排序：题型顺序
        order_idx = {t: i for i, t in enumerate(TYPE_ORDER)}
        picked.sort(key=lambda x: (order_idx.get(x["question_type"], 99), x["source"].id))

        questions_out: List[TestQuestion] = []
        for i, item in enumerate(picked, start=1):
            q: Question = item["source"]
            tq = TestQuestion(
                test_paper_id=paper.id,
                seq=i,
                source_question_id=q.id,
                source_exam_paper_id=q.exam_paper_id,
                question_type=item["question_type"],
                content=q.content or "",
                options=q.options,
                answer=q.answer,
                analysis=q.analysis,
                images=q.images,
                score=float(item["score"]),
                primary_kp_id=q.primary_kp_id,
                secondary_kp_ids=q.secondary_kp_ids,
                difficulty=q.difficulty,
                ability_dimension=getattr(q, "ability_dimension", None),
            )
            db.add(tq)
            questions_out.append(tq)

        await db.commit()
        await db.refresh(paper)
        for tq in questions_out:
            await db.refresh(tq)

        return TestPaperDetail(
            **paper_summary(paper, len(questions_out)).model_dump(),
            type_structure=actual_ts,
            algorithm_version=paper.algorithm_version,
            lambda_value=float(paper.lambda_value),
            questions=[
                to_public_question(tq, tq.source_exam_paper_id) for tq in questions_out
            ],
        )


async def list_papers(
    db: AsyncSession, user_id: int, goal_id: Optional[int] = None
) -> List[TestPaperSummary]:
    q = select(TestPaper).where(TestPaper.user_id == user_id)
    if goal_id:
        q = q.where(TestPaper.goal_id == goal_id)
    q = q.order_by(TestPaper.created_at.desc())
    papers = (await db.execute(q)).scalars().all()
    out = []
    for p in papers:
        cnt = (
            await db.execute(
                select(TestQuestion.id).where(TestQuestion.test_paper_id == p.id)
            )
        ).scalars().all()
        out.append(paper_summary(p, len(cnt)))
    return out


async def get_paper_detail(
    db: AsyncSession, user_id: int, paper_id: int
) -> TestPaperDetail:
    paper = await get_owned_paper(db, paper_id, user_id)
    rows = (
        await db.execute(
            select(TestQuestion)
            .where(TestQuestion.test_paper_id == paper.id)
            .order_by(TestQuestion.seq.asc())
        )
    ).scalars().all()
    paper_ids = await resolve_source_exam_paper_ids(db, list(rows))
    return TestPaperDetail(
        **paper_summary(paper, len(rows)).model_dump(),
        type_structure=paper.type_structure,
        algorithm_version=paper.algorithm_version or ALGORITHM_VERSION,
        lambda_value=float(paper.lambda_value or DEFAULT_LAMBDA),
        questions=[to_public_question(tq, paper_ids.get(tq.id)) for tq in rows],
    )


async def delete_paper(db: AsyncSession, user_id: int, paper_id: int) -> None:
    paper = await get_owned_paper(db, paper_id, user_id)
    await db.execute(delete(TestAnswer).where(TestAnswer.test_paper_id == paper.id))
    await db.execute(delete(TestQuestion).where(TestQuestion.test_paper_id == paper.id))
    await db.delete(paper)
    await db.commit()
