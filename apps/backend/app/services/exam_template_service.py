"""真题结构模板：分值方案套用、π(k,t) 统计、默认模板"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint
from app.models.question import (
    ExamKpScoreStat,
    ExamPaper,
    ExamScoreScheme,
    ExamStructureTemplate,
    Question,
)

logger = logging.getLogger(__name__)

LINK_RATE_READY = 0.9

# 题型展示/统计顺序：选择 → 填空 → 解答 → 证明
TYPE_STRUCTURE_ORDER = ("choice", "fill", "answer", "proof")


def sort_question_types(types: List[str]) -> List[str]:
    order = {t: i for i, t in enumerate(TYPE_STRUCTURE_ORDER)}
    return sorted(types, key=lambda t: (order.get(t, 99), t))


# 浙江中考数学默认分值种子（近年常见：选择/填空每题3分见真题「每小题3分」；
# 解答题 17–21 每题8分、22–23 每题10分、24题12分，共72分。
# 若 Word 已解析出每题分，以题目 score 为准；此处仅作空分回填。）
ZHEJIANG_ZHONGKAO_MATH_RULES: Dict[str, Any] = {
    "choice": {"score_each": 3},
    "fill": {"score_each": 3},
    "answer": {
        "per_number": {
            "17": 8,
            "18": 8,
            "19": 8,
            "20": 8,
            "21": 8,
            "22": 10,
            "23": 10,
            "24": 12,
        }
    },
    "proof": {"use_type": "answer"},
}


def _rule_for_type(rules: Dict[str, Any], qtype: str) -> Dict[str, Any]:
    raw = rules.get(qtype) or {}
    if isinstance(raw, dict) and raw.get("use_type"):
        return rules.get(str(raw["use_type"])) or {}
    return raw if isinstance(raw, dict) else {}


def resolve_score_from_scheme(
    qtype: str,
    question_number: Optional[int],
    rules: Dict[str, Any],
) -> Optional[float]:
    """按方案解析单题分值；无法匹配返回 None。"""
    rule = _rule_for_type(rules, qtype)
    if not rule:
        return None
    if "score_each" in rule and rule["score_each"] is not None:
        try:
            return float(rule["score_each"])
        except (TypeError, ValueError):
            return None
    per_number = rule.get("per_number") or {}
    if question_number is not None and str(question_number) in per_number:
        try:
            return float(per_number[str(question_number)])
        except (TypeError, ValueError):
            return None
    return None


def resolve_score_with_fallback(
    q: Question,
    rules: Dict[str, Any],
    answer_order_scores: Optional[List[float]] = None,
    answer_index_map: Optional[Dict[int, int]] = None,
) -> Tuple[Optional[float], bool]:
    """
    返回 (score, used_temp)。
    已有 score 优先；否则套 scheme；解答题题号不匹配时按卷内顺序回退。
    """
    if q.score is not None:
        try:
            return float(q.score), False
        except (TypeError, ValueError):
            pass

    direct = resolve_score_from_scheme(q.question_type, q.question_number, rules)
    if direct is not None:
        return direct, True

    qtype = q.question_type
    rule = _rule_for_type(rules, qtype)
    if answer_order_scores and answer_index_map is not None and q.id in answer_index_map:
        idx = answer_index_map[q.id]
        if 0 <= idx < len(answer_order_scores):
            return answer_order_scores[idx], True

    if "score_each" in (rule or {}):
        try:
            return float(rule["score_each"]), True
        except (TypeError, ValueError):
            return None, False
    return None, False


def _build_answer_fallback(questions: List[Question], rules: Dict[str, Any]) -> Tuple[List[float], Dict[int, int]]:
    """解答/证明题：按题号排序后，用 per_number 的值序列按序回退。"""
    answer_like = [
        q for q in questions
        if q.question_type in ("answer", "proof")
    ]
    answer_like.sort(key=lambda q: (q.question_number is None, q.question_number or 0, q.id))
    rule = _rule_for_type(rules, "answer")
    per = rule.get("per_number") or {}
    # 按题号数字排序的分值列表
    try:
        ordered_vals = [
            float(per[k]) for k in sorted(per.keys(), key=lambda x: int(x) if str(x).isdigit() else 0)
        ]
    except (TypeError, ValueError):
        ordered_vals = []
    index_map = {q.id: i for i, q in enumerate(answer_like)}
    return ordered_vals, index_map


async def ensure_default_score_scheme(db: AsyncSession) -> ExamScoreScheme:
    result = await db.execute(
        select(ExamScoreScheme).where(
            ExamScoreScheme.subject == "数学",
            ExamScoreScheme.region == "浙江",
            ExamScoreScheme.exam_type == "zhongkao",
        ).limit(1)
    )
    scheme = result.scalar_one_or_none()
    if scheme:
        # 同步内置题号分值表（补 23/24、纠正旧版 17=6 等），避免本卷模板因缺分失败
        rules = dict(scheme.rules or {})
        seed_ans = (ZHEJIANG_ZHONGKAO_MATH_RULES.get("answer") or {}).get("per_number") or {}
        cur_ans = dict((rules.get("answer") or {}).get("per_number") or {})
        merged = {**seed_ans, **cur_ans}  # 库内自定义优先
        # 若仍缺种子中的题号，用种子补齐
        for k, v in seed_ans.items():
            if k not in cur_ans:
                merged[k] = v
        # 旧种子仅有 17–22 且 17=6：视为过期，整体替换为现行种子
        if set(cur_ans.keys()) <= {"17", "18", "19", "20", "21", "22"} and str(cur_ans.get("17")) in ("6", "6.0"):
            merged = dict(seed_ans)
        ans_rule = dict(rules.get("answer") or {})
        ans_rule["per_number"] = merged
        rules["answer"] = ans_rule
        if not (rules.get("choice") or {}).get("score_each"):
            rules["choice"] = dict(ZHEJIANG_ZHONGKAO_MATH_RULES["choice"])
        if not (rules.get("fill") or {}).get("score_each"):
            rules["fill"] = dict(ZHEJIANG_ZHONGKAO_MATH_RULES["fill"])
        if rules != (scheme.rules or {}):
            scheme.rules = rules
            await db.commit()
            await db.refresh(scheme)
        return scheme

    scheme = ExamScoreScheme(
        name="浙江中考数学（默认）",
        exam_type="zhongkao",
        subject="数学",
        region="浙江",
        rules=ZHEJIANG_ZHONGKAO_MATH_RULES,
        is_default=1,
    )
    db.add(scheme)
    await db.commit()
    await db.refresh(scheme)
    logger.info("已种子化默认分值方案：浙江中考数学")
    return scheme


async def apply_score_scheme(
    db: AsyncSession,
    paper: ExamPaper,
    scheme: ExamScoreScheme,
    overwrite: bool = False,
) -> Dict[str, Any]:
    result = await db.execute(
        select(Question).where(Question.exam_paper_id == paper.id)
    )
    questions = list(result.scalars().all())
    questions.sort(key=lambda q: (q.question_number is None, q.question_number or 0, q.id))
    rules = scheme.rules or {}
    order_scores, index_map = _build_answer_fallback(questions, rules)

    updated = 0
    skipped = 0
    unmatched: List[int] = []

    for q in questions:
        if q.score is not None and not overwrite:
            skipped += 1
            continue
        # overwrite 时忽略已有 score，直接按方案/顺序回退解析
        saved = q.score
        if overwrite:
            q.score = None
        final, _ = resolve_score_with_fallback(q, rules, order_scores, index_map)
        if final is None:
            q.score = saved
            unmatched.append(q.question_number if q.question_number is not None else q.id)
            continue
        q.score = final
        updated += 1

    await db.commit()
    return {
        "updated": updated,
        "skipped": skipped,
        "unmatched_numbers": unmatched,
        "scheme_id": scheme.id,
        "scheme_name": scheme.name,
        "overwrite": overwrite,
    }


def _normalize_paper_ids(paper_ids: List[int]) -> List[int]:
    return sorted({int(x) for x in paper_ids})


def _coerce_paper_id_list(stored: Optional[Any]) -> List[int]:
    """兼容 source_paper_ids 为 list 或 JSON 字符串。"""
    if not stored:
        return []
    if isinstance(stored, str):
        import json
        try:
            stored = json.loads(stored)
        except Exception:
            return []
    if not isinstance(stored, (list, tuple)):
        return []
    try:
        return _normalize_paper_ids([int(x) for x in stored])
    except (TypeError, ValueError):
        return []


def _paper_ids_match(stored: Optional[Any], target: List[int]) -> bool:
    return _coerce_paper_id_list(stored) == _normalize_paper_ids(target)


def _paper_leaf_maps(
    resolved: List[Tuple[Any, float, bool]],
    kp_meta: Dict[str, KnowledgePoint],
) -> Dict[str, Any]:
    """单卷：题型总分 + (题型,一级,二级) 分值/题量。"""
    type_total: Dict[str, float] = defaultdict(float)
    leaf_sum: Dict[Tuple[str, str, str], float] = defaultdict(float)
    leaf_cnt: Dict[Tuple[str, str, str], int] = defaultdict(int)
    kp_sum: Dict[str, float] = defaultdict(float)
    kp_cnt: Dict[str, int] = defaultdict(int)
    kp_type_sum: Dict[Tuple[str, str], float] = defaultdict(float)
    kp_type_cnt: Dict[Tuple[str, str], int] = defaultdict(int)

    for q, score, _ in resolved:
        qtype = q.question_type or "answer"
        sc = float(score)
        type_total[qtype] += sc
        if not q.primary_kp_id:
            continue
        kp = kp_meta.get(q.primary_kp_id)
        cat1 = (kp.category_1 if kp and (kp.category_1 or "").strip() else "") or "未分类"
        cat2 = ((kp.category_2 if kp and kp.category_2 else "") or "").strip()
        leaf_sum[(qtype, cat1, cat2)] += sc
        leaf_cnt[(qtype, cat1, cat2)] += 1
        kp_sum[q.primary_kp_id] += sc
        kp_cnt[q.primary_kp_id] += 1
        kp_type_sum[(q.primary_kp_id, qtype)] += sc
        kp_type_cnt[(q.primary_kp_id, qtype)] += 1

    attributed = sum(kp_sum.values())
    return {
        "type_total": dict(type_total),
        "leaf_sum": dict(leaf_sum),
        "leaf_cnt": dict(leaf_cnt),
        "kp_sum": dict(kp_sum),
        "kp_cnt": dict(kp_cnt),
        "kp_type_sum": dict(kp_type_sum),
        "kp_type_cnt": dict(kp_type_cnt),
        "attributed": attributed,
    }


def compute_category_score_stats(
    resolved: List[Tuple[Any, float, bool]],
    kp_meta: Dict[str, KnowledgePoint],
    type_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """单卷（或已合并的题目列表）知识点分值占比。"""
    return average_category_score_stats(
        [_paper_leaf_maps(resolved, kp_meta)],
        type_order=type_order,
    )


def average_category_score_stats(
    per_paper: List[Dict[str, Any]],
    type_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    多套等权平均后的知识点分值占比。
    - 各卷先算：该分类分值 / 该题型总分 → 卷内占比
    - 多套：占比 = mean(各卷占比)；展示分值 = 平均占比 × 该题型平均总分
      （与合卷加总 sum(s)/sum(d) 不同，避免大卷主导）
    """
    n = len(per_paper) or 1
    all_keys: set = set()
    all_types: set = set()
    for m in per_paper:
        all_keys.update(m.get("leaf_sum") or {})
        all_types.update((m.get("type_total") or {}).keys())

    type_totals: Dict[str, float] = {}
    for qt in all_types:
        type_totals[qt] = sum(float((m.get("type_total") or {}).get(qt, 0.0)) for m in per_paper) / n

    effective_order = list(type_order) if type_order else list(TYPE_STRUCTURE_ORDER)
    order_index = {t: i for i, t in enumerate(effective_order)}

    def _leaf_sort_key(key: Tuple[str, str, str]):
        qt, c1, c2 = key
        oi = order_index.get(qt)
        if oi is None:
            oi = 100 + (
                TYPE_STRUCTURE_ORDER.index(qt) if qt in TYPE_STRUCTURE_ORDER else 99
            )
        return (oi, qt, c1, c2 == "", c2)

    ratio_rows: List[Dict[str, Any]] = []
    for key in sorted(all_keys, key=_leaf_sort_key):
        qtype, cat1, cat2 = key
        ratios: List[float] = []
        cnts: List[int] = []
        for m in per_paper:
            s = float((m.get("leaf_sum") or {}).get(key, 0.0))
            d = float((m.get("type_total") or {}).get(qtype, 0.0))
            ratios.append((s / d) if d > 0 else 0.0)
            cnts.append(int((m.get("leaf_cnt") or {}).get(key, 0)))
        avg_ratio = sum(ratios) / n
        if avg_ratio <= 0:
            continue
        denom = type_totals.get(qtype) or 0.0
        avg_score = avg_ratio * denom
        ratio_rows.append({
            "question_type": qtype,
            "category_1": cat1,
            "category_2": cat2,
            "score_sum": round(avg_score, 2),
            "score_ratio": round(avg_ratio, 4),
            "question_count": int(round(sum(cnts) / n)),
        })

    note = (
        "分值来自各卷题目 score；有二级细化到二级，仅一级则二级列为空。"
        "多套时：各卷先算「分类分值÷题型总分」，再对占比等权平均；展示分值=平均占比×题型平均总分。"
        if n > 1
        else "分值来自题目 score；占比=该行分值÷该题型总分（含未挂载）。"
    )
    return {
        "ratio_rows": ratio_rows,
        "type_totals": {k: round(v, 2) for k, v in type_totals.items()},
        "paper_count": n,
        "aggregate": "equal_weight_mean_ratio" if n > 1 else "single",
        "note": note,
    }


async def build_template_for_paper(
    db: AsyncSession,
    paper: ExamPaper,
    scheme: Optional[ExamScoreScheme] = None,
) -> ExamStructureTemplate:
    """兼容：单卷生成 = 只选这一套。"""
    return await build_template_for_papers(db, [paper], scheme=scheme)


async def build_template_for_papers(
    db: AsyncSession,
    papers: List[ExamPaper],
    scheme: Optional[ExamScoreScheme] = None,
    auto_apply_scores: bool = False,
) -> ExamStructureTemplate:
    """
    按用户勾选的多套试卷生成一份结构模板（平均模板）。
    - 分值只使用题库已有 score（来自 Word 识别或人工填写），禁止默认分值表自动写库
    - 题型结构：各套题型题量/分值等权平均（题量四舍五入）
    - 知识点占比 / π(k,t)：各套先各自统计，再等权平均（不是合卷加总）
    """
    if not papers:
        raise ValueError("请至少选择一套真题")

    if scheme is None:
        scheme = await ensure_default_score_scheme(db)

    paper_ids = _normalize_paper_ids([p.id for p in papers])
    papers_by_id = {p.id: p for p in papers}

    # 兼容旧参数：即使传入 True 也不再自动套方案写库（分值必须来自原文件或手改）
    apply_summaries: List[Dict[str, Any]] = []
    if auto_apply_scores:
        logger.warning(
            "build_template_for_papers: auto_apply_scores 已禁用，忽略自动补分请求 paper_ids=%s",
            paper_ids,
        )

    # 每卷独立统计 → 题型结构与知识点占比均做等权平均
    # score 可为 None（缺分仍纳入题量，分值小计/占比只统计已填分的题）
    all_resolved: List[Tuple[Question, Optional[float], bool]] = []
    per_paper_resolved: List[List[Tuple[Question, Optional[float], bool]]] = []
    per_paper_type: List[Dict[str, Dict[str, Any]]] = []
    used_temp = False
    missing_scores: List[str] = []

    for pid in paper_ids:
        paper = papers_by_id[pid]
        result = await db.execute(select(Question).where(Question.exam_paper_id == paper.id))
        questions = list(result.scalars().all())
        questions.sort(key=lambda q: (q.question_number is None, q.question_number or 0, q.id))
        if not questions:
            raise ValueError(f"试卷「{paper.title}」内无题目，无法生成模板")

        resolved: List[Tuple[Question, Optional[float], bool]] = []
        for q in questions:
            score: Optional[float] = None
            if q.score is not None:
                try:
                    score = float(q.score)
                except (TypeError, ValueError):
                    score = None
            if score is None:
                missing_scores.append(
                    f"「{paper.title}」#{q.question_number or q.id}（{q.question_type}）"
                )
            resolved.append((q, score, False))
        all_resolved.extend(resolved)
        per_paper_resolved.append(resolved)

    for resolved in per_paper_resolved:
        by_type: Dict[str, List[Optional[float]]] = defaultdict(list)
        for q, score, _ in resolved:
            by_type[q.question_type].append(score)
        paper_types: Dict[str, Dict[str, Any]] = {}
        for qtype, scores in by_type.items():
            known = [s for s in scores if s is not None]
            entry: Dict[str, Any] = {
                "count": len(scores),
                "subtotal": round(sum(known), 2) if known else 0.0,
                "missing_score_count": len(scores) - len(known),
            }
            if known and len(known) == len(scores) and len(set(known)) == 1:
                entry["score_each"] = known[0]
            paper_types[qtype] = entry
        per_paper_type.append(paper_types)

    n_papers = len(paper_ids)
    all_qtypes = sort_question_types(list({t for pt in per_paper_type for t in pt.keys()}))
    type_structure: List[Dict[str, Any]] = []
    total_score = 0.0
    for qtype in all_qtypes:
        counts = [pt[qtype]["count"] if qtype in pt else 0 for pt in per_paper_type]
        subtots = [pt[qtype]["subtotal"] if qtype in pt else 0.0 for pt in per_paper_type]
        avg_count = int(round(sum(counts) / n_papers))
        avg_subtotal = round(sum(subtots) / n_papers, 2)
        total_score += avg_subtotal
        entry = {
            "question_type": qtype,
            "count": avg_count,
            "subtotal": avg_subtotal,
        }
        each_vals = [
            pt[qtype]["score_each"]
            for pt in per_paper_type
            if qtype in pt and pt[qtype].get("score_each") is not None
        ]
        if each_vals:
            entry["score_each"] = round(sum(each_vals) / len(each_vals), 2)
        type_structure.append(entry)

    total = len(all_resolved)
    linked = sum(1 for q, _, _ in all_resolved if q.primary_kp_id)
    unlinked = total - linked
    link_rate = linked / total if total else 0.0

    unlinked_score = 0.0
    unlinked_items: List[Dict[str, Any]] = []
    for q, score, _ in all_resolved:
        if q.primary_kp_id:
            continue
        if score is not None:
            unlinked_score += score
        unlinked_items.append({
            "question_id": q.id,
            "exam_paper_id": q.exam_paper_id,
            "question_number": q.question_number,
            "question_type": q.question_type,
            "score": score,
        })

    kp_ids = list({q.primary_kp_id for q, _, _ in all_resolved if q.primary_kp_id})
    kp_meta: Dict[str, KnowledgePoint] = {}
    if kp_ids:
        krows = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids)))
        kp_meta = {k.id: k for k in krows.scalars().all()}

    # 知识点占比：仅用已填分值的题目
    per_paper_maps = [
        _paper_leaf_maps([(q, float(s), t) for q, s, t in r if s is not None], kp_meta)
        for r in per_paper_resolved
    ]
    type_order = [e["question_type"] for e in type_structure]
    category_score_stats = average_category_score_stats(per_paper_maps, type_order=type_order)

    # π(k)、π(k,t)：各卷占比等权平均；分值为各卷分值等权平均
    all_kp_ids = set()
    all_kp_type: set = set()
    for m in per_paper_maps:
        all_kp_ids.update((m.get("kp_sum") or {}).keys())
        all_kp_type.update((m.get("kp_type_sum") or {}).keys())

    avg_kp_sum: Dict[str, float] = {}
    avg_kp_cnt: Dict[str, int] = {}
    avg_kp_ratio: Dict[str, float] = {}
    for kp_id in all_kp_ids:
        scores = [float((m.get("kp_sum") or {}).get(kp_id, 0.0)) for m in per_paper_maps]
        cnts = [int((m.get("kp_cnt") or {}).get(kp_id, 0)) for m in per_paper_maps]
        ratios = []
        for m in per_paper_maps:
            att = float(m.get("attributed") or 0.0)
            s = float((m.get("kp_sum") or {}).get(kp_id, 0.0))
            ratios.append((s / att) if att > 0 else 0.0)
        avg_kp_sum[kp_id] = sum(scores) / n_papers
        avg_kp_cnt[kp_id] = int(round(sum(cnts) / n_papers))
        avg_kp_ratio[kp_id] = sum(ratios) / n_papers

    avg_kp_type_sum: Dict[Tuple[str, str], float] = {}
    avg_kp_type_cnt: Dict[Tuple[str, str], int] = {}
    avg_kp_type_ratio: Dict[Tuple[str, str], float] = {}
    for key in all_kp_type:
        scores = [float((m.get("kp_type_sum") or {}).get(key, 0.0)) for m in per_paper_maps]
        cnts = [int((m.get("kp_type_cnt") or {}).get(key, 0)) for m in per_paper_maps]
        ratios = []
        for m in per_paper_maps:
            att = float(m.get("attributed") or 0.0)
            s = float((m.get("kp_type_sum") or {}).get(key, 0.0))
            ratios.append((s / att) if att > 0 else 0.0)
        avg_kp_type_sum[key] = sum(scores) / n_papers
        avg_kp_type_cnt[key] = int(round(sum(cnts) / n_papers))
        avg_kp_type_ratio[key] = sum(ratios) / n_papers

    attributed_total = sum(avg_kp_sum.values())

    status = "ready"
    if (
        missing_scores
        or unlinked > 0
        or link_rate < LINK_RATE_READY
        or attributed_total <= 0
    ):
        status = "incomplete"

    all_tpl = (await db.execute(select(ExamStructureTemplate))).scalars().all()
    template = None
    for t in all_tpl:
        if _paper_ids_match(t.source_paper_ids, paper_ids):
            template = t
            break

    first = papers_by_id[paper_ids[0]]
    if n_papers == 1:
        name = f"{first.title or '真题'} · 结构模板"
        year = first.year
    else:
        name = f"平均结构模板（{n_papers}套）"
        years = [papers_by_id[i].year for i in paper_ids if papers_by_id[i].year]
        year = years[0] if len(set(years)) == 1 else None

    region = first.region or scheme.region or "浙江"
    subject = first.subject or "数学"
    was_default = bool(template.is_default) if template else False

    if template is None:
        template = ExamStructureTemplate(
            name=name,
            exam_type=scheme.exam_type or "zhongkao",
            subject=subject,
            region=region,
            year=year,
            source_paper_ids=paper_ids,
            type_structure=type_structure,
            category_score_stats=category_score_stats,
            total_score=round(total_score, 2),
            scheme_id=scheme.id,
            status=status,
            is_default=0,
            used_temp_scores=1 if used_temp else 0,
        )
        db.add(template)
        await db.flush()
    else:
        template.name = name
        template.exam_type = scheme.exam_type or "zhongkao"
        template.subject = subject
        template.region = region
        template.year = year
        template.source_paper_ids = paper_ids
        template.type_structure = type_structure
        template.category_score_stats = category_score_stats
        template.total_score = round(total_score, 2)
        template.scheme_id = scheme.id
        template.status = status
        template.used_temp_scores = 1 if used_temp else 0
        if status != "ready":
            template.is_default = 0
        elif was_default:
            template.is_default = 1

    await db.execute(
        delete(ExamKpScoreStat).where(ExamKpScoreStat.template_id == template.id)
    )

    for kp_id, s in avg_kp_sum.items():
        db.add(ExamKpScoreStat(
            template_id=template.id,
            kp_id=kp_id,
            question_type=None,
            score_sum=round(s, 2),
            score_ratio=round(avg_kp_ratio.get(kp_id, 0.0), 4),
            question_count=avg_kp_cnt.get(kp_id, 0),
        ))
    for (kp_id, qtype), s in avg_kp_type_sum.items():
        db.add(ExamKpScoreStat(
            template_id=template.id,
            kp_id=kp_id,
            question_type=qtype,
            score_sum=round(s, 2),
            score_ratio=round(avg_kp_type_ratio.get((kp_id, qtype), 0.0), 4),
            question_count=avg_kp_type_cnt.get((kp_id, qtype), 0),
        ))

    await db.commit()
    await db.refresh(template)

    scores_filled = sum(s.get("updated", 0) for s in apply_summaries)
    unmatched_all: List[Any] = []
    for s in apply_summaries:
        for n in s.get("unmatched_numbers") or []:
            unmatched_all.append({"paper_id": s.get("paper_id"), "number": n})

    template._build_meta = {  # type: ignore[attr-defined]
        "paper_ids": paper_ids,
        "paper_count": n_papers,
        "link_rate": round(link_rate, 4),
        "linked_count": linked,
        "unlinked_count": unlinked,
        "unlinked_score": unlinked_score,
        "unlinked_items": unlinked_items[:50],
        "missing_score_count": len(missing_scores),
        "missing_score_items": missing_scores[:50],
        "used_temp_scores": used_temp,
        "attributed_score": round(attributed_total, 2),
        "total_score": template.total_score,
        "type_structure_note": "多套时为各套题型结构等权平均；缺分题计入题量、不计入小计",
        "kp_stat_note": "多套时：各卷先算分类占比，再对占比等权平均（非合卷加总）",
        "auto_applied_scores": False,
        "scores_filled_count": 0,
        "score_unmatched": unmatched_all[:30],
        "score_source_note": "分值仅来自原文件识别或手工填写；可在单卷模板「题目明细」中补填并回写题目",
    }
    return template


async def set_default_template(
    db: AsyncSession,
    template: ExamStructureTemplate,
) -> ExamStructureTemplate:
    if template.status != "ready":
        raise ValueError("仅 status=ready 的模板可设为默认")

    others = await db.execute(
        select(ExamStructureTemplate).where(
            ExamStructureTemplate.subject == template.subject,
            ExamStructureTemplate.region == (template.region or "浙江"),
            ExamStructureTemplate.exam_type == (template.exam_type or "zhongkao"),
            ExamStructureTemplate.id != template.id,
            ExamStructureTemplate.is_default == 1,
        )
    )
    for o in others.scalars().all():
        o.is_default = 0
    template.is_default = 1
    await db.commit()
    await db.refresh(template)
    return template


async def unset_default_template(db: AsyncSession, template: ExamStructureTemplate) -> ExamStructureTemplate:
    template.is_default = 0
    await db.commit()
    await db.refresh(template)
    return template


async def has_default_ready_template(
    db: AsyncSession,
    subject: str = "数学",
    region: Optional[str] = None,
    exam_type: str = "zhongkao",
) -> bool:
    q = select(ExamStructureTemplate).where(
        ExamStructureTemplate.is_default == 1,
        ExamStructureTemplate.status == "ready",
        ExamStructureTemplate.subject == subject,
        ExamStructureTemplate.exam_type == exam_type,
    )
    if region:
        q = q.where(ExamStructureTemplate.region == region)
    result = await db.execute(q.limit(1))
    return result.scalar_one_or_none() is not None


async def template_for_paper(db: AsyncSession, paper_id: int) -> Optional[ExamStructureTemplate]:
    all_tpl = (await db.execute(select(ExamStructureTemplate))).scalars().all()
    for t in all_tpl:
        ids = t.source_paper_ids or []
        if paper_id in ids and len(ids) == 1:
            return t
    return None


async def list_question_detail_rows(
    db: AsyncSession,
    paper_ids: Optional[List[int]],
) -> List[Dict[str, Any]]:
    """模板详情用：来源卷每题的题型/分值/知识点一二级分类（按选择→填空→解答、题号排序）。"""
    ids = _normalize_paper_ids(paper_ids or [])
    if not ids:
        return []
    result = await db.execute(select(Question).where(Question.exam_paper_id.in_(ids)))
    questions = list(result.scalars().all())
    kp_ids = {q.primary_kp_id for q in questions if q.primary_kp_id}
    kp_meta: Dict[str, KnowledgePoint] = {}
    if kp_ids:
        krows = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(list(kp_ids))))
        kp_meta = {k.id: k for k in krows.scalars().all()}

    type_rank = {t: i for i, t in enumerate(TYPE_STRUCTURE_ORDER)}

    def _q_key(q: Question):
        return (
            type_rank.get(q.question_type or "", 99),
            q.question_type or "",
            q.exam_paper_id or 0,
            q.question_number is None,
            q.question_number or 0,
            q.id,
        )

    rows: List[Dict[str, Any]] = []
    for q in sorted(questions, key=_q_key):
        kp = kp_meta.get(q.primary_kp_id) if q.primary_kp_id else None
        rows.append({
            "question_id": q.id,
            "exam_paper_id": q.exam_paper_id,
            "question_number": q.question_number,
            "question_type": q.question_type,
            "score": float(q.score) if q.score is not None else None,
            "category_1": (kp.category_1 or "").strip() if kp and kp.category_1 else None,
            "category_2": (kp.category_2 or "").strip() if kp and kp.category_2 else None,
            "primary_kp_id": q.primary_kp_id,
        })
    return rows


def normalize_type_structure_order(
    type_structure: Optional[List[Dict[str, Any]]],
) -> Optional[List[Dict[str, Any]]]:
    if not type_structure:
        return type_structure
    order = {t: i for i, t in enumerate(TYPE_STRUCTURE_ORDER)}
    return sorted(
        type_structure,
        key=lambda e: (order.get(e.get("question_type") or "", 99), e.get("question_type") or ""),
    )


async def enrich_stats_with_kp_names(
    db: AsyncSession,
    stats: List[ExamKpScoreStat],
) -> List[Dict[str, Any]]:
    kp_ids = {s.kp_id for s in stats if s.kp_id}
    names: Dict[str, KnowledgePoint] = {}
    if kp_ids:
        rows = await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(list(kp_ids))))
        names = {kp.id: kp for kp in rows.scalars().all()}
    out = []
    for s in stats:
        kp = names.get(s.kp_id)
        out.append({
            "id": s.id,
            "template_id": s.template_id,
            "kp_id": s.kp_id,
            "kp_name": kp.name if kp else s.kp_id,
            "category_1": kp.category_1 if kp else None,
            "domain": kp.domain if kp else None,
            "question_type": s.question_type,
            "score_sum": s.score_sum,
            "score_ratio": s.score_ratio,
            "question_count": s.question_count,
        })
    return out
