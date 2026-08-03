"""交卷批改后的能力评估：整体分析 / 错题分析 / 逐题知识点分析。"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint
from app.models.question import Question
from app.models.student.test_paper import TestAnswer, TestPaper, TestQuestion
from app.models.system import SystemConfig
from app.schemas.question import ABILITY_DIMENSIONS
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)

ABILITY_ORDER = list(ABILITY_DIMENSIONS)
ERROR_LINKS = ("审题", "建模", "表达", "计算", "推理", "记忆", "粗心", "熟练度", "速度")
DIFF_BUCKETS = ("简单", "中等", "困难")
IMG_RE = re.compile(r"\[IMG:[^\]]+\]")

NARRATIVE_SYSTEM = """你是中考数学学情诊断老师。根据给定的量化统计与错题摘要，输出 JSON：
{
  "overall_summary": "200字内：整体表现、擅长点与欠缺点",
  "progress_comment": "120字内：相对历史测试的进步/退步（若无历史则说明首次测评）",
  "wrong_qualitative": "180字内：错题共性原因，对应审题/建模/表达/计算/推理/记忆/粗心/熟练度/速度等环节",
  "item_comments": [
    {"seq": 1, "error_links": ["计算","粗心"], "ability_gap": "计算", "reason": "一句话说明做错原因与能力缺陷"}
  ]
}
规则：只分析提供的错题 seq；error_links 从给定枚举中选 1～3 个；不要编造未给出的分数。"""


def _diff_bucket(d: Optional[int]) -> str:
    try:
        v = int(d) if d is not None else 3
    except (TypeError, ValueError):
        v = 3
    if v <= 2:
        return "简单"
    if v >= 4:
        return "困难"
    return "中等"


def _clean(text: Optional[str], limit: int = 180) -> str:
    s = IMG_RE.sub(" ", text or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def _guess_error_links(
    *,
    ability: str,
    diff_bucket: str,
    qtype: str,
    uncertain: bool,
) -> List[str]:
    links: List[str] = []
    if uncertain:
        links.append("熟练度")
    if diff_bucket == "简单":
        links.append("粗心")
        if ability in ("计算", "记忆"):
            links.append(ability)
        else:
            links.append("审题")
    elif diff_bucket == "困难":
        if ability in ("推理", "空间"):
            links.append(ability if ability in ERROR_LINKS else "推理")
        elif ability == "信息提取":
            links.extend(["审题", "建模"])
        else:
            links.extend(["建模", "推理"])
    else:
        if ability == "计算":
            links.extend(["计算", "熟练度"])
        elif ability == "记忆":
            links.append("记忆")
        elif ability in ("推理", "空间"):
            links.append(ability if ability in ERROR_LINKS else "推理")
        elif ability == "信息提取":
            links.append("审题")
        else:
            links.append("审题")
        if qtype in ("fill", "answer", "proof"):
            links.append("表达")
    out: List[str] = []
    for x in links:
        if x in ERROR_LINKS and x not in out:
            out.append(x)
    return out[:3] or ["审题"]


def _rule_overall(
    *,
    earned: float,
    total: float,
    correct: int,
    n: int,
    strong: List[str],
    weak: List[str],
    progress: Dict[str, Any],
) -> Tuple[str, str]:
    rate = (earned / total * 100) if total else 0
    strong_txt = "、".join(strong) if strong else "尚不明显"
    weak_txt = "、".join(weak) if weak else "暂不明显"
    overall = (
        f"本次得分 {earned:g}/{total:g}（约 {rate:.0f}%），答对 {correct}/{n} 题。"
        f"相对擅长的能力维度：{strong_txt}；相对欠缺：{weak_txt}。"
        f"后续建议优先针对薄弱维度与高频错题知识点进行巩固练习。"
    )
    hist = progress.get("history") or []
    if not hist:
        progress_comment = (
            "这是该目标下可对比的首次正式测评结果，暂无历史对比，后续测评将持续跟踪进步。"
        )
    else:
        deltas = progress.get("score_delta")
        prev = progress.get("previous_score")
        if deltas is None:
            progress_comment = f"此前共有 {len(hist)} 次测评记录，本次得分 {earned:g}。"
        elif deltas > 0.5:
            progress_comment = (
                f"相较上次得分 {prev:g}，本次提高约 {deltas:g} 分，整体呈进步趋势；"
                f"请继续巩固已掌握部分，重点突破仍偏弱的能力维度。"
            )
        elif deltas < -0.5:
            progress_comment = (
                f"相较上次得分 {prev:g}，本次下降约 {abs(deltas):g} 分。"
                f"建议复盘本次错题中的简单题与薄弱知识点，减少非智力因素失分。"
            )
        else:
            progress_comment = (
                f"相较上次得分 {prev:g}，本次基本持平（变化约 {deltas:g} 分）。"
                f"能力结构仍需针对薄弱维度做专项提升。"
            )
    return overall, progress_comment


async def _load_kp_map(db: AsyncSession, kp_ids: List[str]) -> Dict[str, KnowledgePoint]:
    ids = [k for k in set(kp_ids) if k]
    if not ids:
        return {}
    rows = (
        await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(ids)))
    ).scalars().all()
    return {r.id: r for r in rows}


async def enrich_knowledge_labels(
    db: AsyncSession, report: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """为历史评估补齐知识点短名称与描述。"""
    if not report:
        return report

    enriched = json.loads(json.dumps(report, ensure_ascii=False))
    wrong_analysis = enriched.get("wrong_analysis") or {}
    distributions = wrong_analysis.get("knowledge_distribution") or []
    knowledge_items = enriched.get("knowledge_items") or []
    rows = [*distributions, *knowledge_items]
    kp_ids = {
        str(row.get("kp_id") or row.get("primary_kp_id"))
        for row in rows
        if row.get("kp_id") or row.get("primary_kp_id")
    }
    kp_map = await _load_kp_map(db, list(kp_ids))

    for row in rows:
        kp_id = row.get("kp_id") or row.get("primary_kp_id")
        kp = kp_map.get(str(kp_id)) if kp_id else None
        if kp is None:
            continue
        row["kp_name"] = (kp.short_name or "").strip() or kp.name
        row["kp_description"] = kp.name

    return enriched


async def _load_source_ability(
    db: AsyncSession, source_ids: List[int]
) -> Dict[int, str]:
    ids = [i for i in set(source_ids) if i]
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Question.id, Question.ability_dimension).where(Question.id.in_(ids))
        )
    ).all()
    return {int(i): (d or "") for i, d in rows if d}


async def _history_for_goal(
    db: AsyncSession, user_id: int, goal_id: int, exclude_paper_id: int
) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(TestPaper)
            .where(
                TestPaper.user_id == user_id,
                TestPaper.goal_id == goal_id,
                TestPaper.status == "graded",
                TestPaper.id != exclude_paper_id,
            )
            .order_by(TestPaper.updated_at.desc())
            .limit(8)
        )
    ).scalars().all()
    out = []
    for p in rows:
        total = float(p.total_score or 0)
        earned = float(p.earned_score or 0)
        out.append(
            {
                "paper_id": p.id,
                "title": p.title,
                "earned_score": earned,
                "total_score": total,
                "rate": round(earned / total * 100, 1) if total else 0,
                "created_at": str(p.updated_at or p.created_at or ""),
            }
        )
    return out


async def build_assessment(
    db: AsyncSession,
    *,
    paper: TestPaper,
    questions: List[TestQuestion],
    answers_map: Dict[int, TestAnswer],
    use_llm: bool = True,
) -> Dict[str, Any]:
    """生成完整能力评估报告（含规则兜底；可选 LLM 润色）。"""
    source_ability = await _load_source_ability(
        db, [q.source_question_id for q in questions if q.source_question_id]
    )
    kp_ids = [q.primary_kp_id for q in questions if q.primary_kp_id]
    kp_map = await _load_kp_map(db, kp_ids)

    items: List[Dict[str, Any]] = []
    wrong_items: List[Dict[str, Any]] = []
    ability_stats: Dict[str, Dict[str, Any]] = {
        d: {
            "dimension": d,
            "attempted": 0,
            "correct": 0,
            "wrong": 0,
            "score_full": 0.0,
            "score_got": 0.0,
            "wrong_seqs": [],
        }
        for d in ABILITY_ORDER
    }
    diff_wrong: Counter = Counter()
    diff_all: Counter = Counter()
    kp_wrong: Dict[str, Dict[str, Any]] = {}
    cat_wrong: Dict[str, Dict[str, Any]] = {}

    correct_count = 0
    graded_count = 0
    pending_count = 0

    for q in questions:
        ans = answers_map.get(q.id)
        dim = (q.ability_dimension or "").strip()
        if not dim and q.source_question_id:
            dim = (source_ability.get(q.source_question_id) or "").strip()
        if dim not in ABILITY_ORDER:
            dim = "未标注"
        diff = q.difficulty if q.difficulty is not None else 3
        bucket = _diff_bucket(diff)
        diff_all[bucket] += 1
        kp = kp_map.get(q.primary_kp_id) if q.primary_kp_id else None
        kp_name = (
            ((kp.short_name or "").strip() or kp.name)
            if kp
            else (q.primary_kp_id or "未标注知识点")
        )
        kp_description = kp.name if kp else None
        cat1 = (kp.category_1 if kp else None) or "未分类"
        cat2 = (kp.category_2 if kp else None) or ""

        is_correct = ans.is_correct if ans else False
        score_got = float(ans.score_got or 0) if ans else 0.0
        uncertain = bool(ans.is_marked_uncertain) if ans else False
        if ans and ans.is_correct is None:
            pending_count += 1
            status = "pending"
        elif is_correct:
            correct_count += 1
            graded_count += 1
            status = "correct"
        else:
            graded_count += 1
            status = "wrong"

        if dim in ability_stats:
            ability_stats[dim]["attempted"] += 1
            ability_stats[dim]["score_full"] += float(q.score or 0)
            ability_stats[dim]["score_got"] += score_got
            if status == "correct":
                ability_stats[dim]["correct"] += 1
            elif status == "wrong":
                ability_stats[dim]["wrong"] += 1
                ability_stats[dim]["wrong_seqs"].append(q.seq)

        row: Dict[str, Any] = {
            "question_id": q.id,
            "seq": q.seq,
            "question_type": q.question_type,
            "score": float(q.score or 0),
            "score_got": score_got,
            "is_correct": is_correct if status != "pending" else None,
            "status": status,
            "ability_dimension": dim if dim != "未标注" else None,
            "difficulty": diff,
            "difficulty_bucket": bucket,
            "primary_kp_id": q.primary_kp_id,
            "kp_name": kp_name,
            "kp_description": kp_description,
            "category_1": cat1,
            "category_2": cat2,
            "student_answer": (ans.selected_option or ans.answer_text) if ans else None,
            "is_marked_uncertain": uncertain,
            "content_preview": _clean(q.content, 120),
        }

        if status == "wrong":
            diff_wrong[bucket] += 1
            links = _guess_error_links(
                ability=dim if dim != "未标注" else "理解",
                diff_bucket=bucket,
                qtype=q.question_type or "",
                uncertain=uncertain,
            )
            row["error_links"] = links
            row["ability_gap"] = dim if dim in ABILITY_ORDER else (links[0] if links else "审题")
            row["reason"] = (
                f"第{q.seq}题（{bucket}/{dim if dim != '未标注' else '能力未标注'}）做错，"
                f"更可能卡在「{'、'.join(links)}」环节。"
            )
            wrong_items.append(row)

            kid = q.primary_kp_id or f"unknown:{kp_name}"
            if kid not in kp_wrong:
                kp_wrong[kid] = {
                    "kp_id": q.primary_kp_id,
                    "kp_name": kp_name,
                    "kp_description": kp_description,
                    "category_1": cat1,
                    "category_2": cat2,
                    "wrong_count": 0,
                    "seqs": [],
                }
            kp_wrong[kid]["wrong_count"] += 1
            kp_wrong[kid]["seqs"].append(q.seq)

            if cat1 not in cat_wrong:
                cat_wrong[cat1] = {"category_1": cat1, "wrong_count": 0, "seqs": []}
            cat_wrong[cat1]["wrong_count"] += 1
            cat_wrong[cat1]["seqs"].append(q.seq)

        items.append(row)

    dim_rates: List[Tuple[str, float]] = []
    for d, st in ability_stats.items():
        if st["attempted"] <= 0:
            continue
        rate = (
            (st["score_got"] / st["score_full"])
            if st["score_full"]
            else (st["correct"] / st["attempted"])
        )
        dim_rates.append((d, rate))
    dim_rates.sort(key=lambda x: x[1], reverse=True)
    strong = [d for d, r in dim_rates if r >= 0.7][:3]
    weak = [d for d, r in sorted(dim_rates, key=lambda x: x[1]) if r < 0.6][:3]
    if not strong and dim_rates:
        strong = [dim_rates[0][0]]
    if not weak and dim_rates:
        weak = [dim_rates[-1][0]]

    hist = await _history_for_goal(db, paper.user_id, paper.goal_id, paper.id)
    earned = float(paper.earned_score or 0)
    total = float(paper.total_score or 0)
    prev = hist[0]["earned_score"] if hist else None
    progress = {
        "history": hist,
        "previous_score": prev,
        "score_delta": round(earned - prev, 2) if prev is not None else None,
        "history_count": len(hist),
    }
    overall_summary, progress_comment = _rule_overall(
        earned=earned,
        total=total,
        correct=correct_count,
        n=len(questions),
        strong=strong,
        weak=weak,
        progress=progress,
    )

    wrong_ability = []
    for d in ABILITY_ORDER:
        st = ability_stats[d]
        if st["wrong"] <= 0:
            continue
        wrong_ability.append(
            {
                "dimension": d,
                "wrong_count": st["wrong"],
                "attempted": st["attempted"],
                "wrong_rate": round(st["wrong"] / st["attempted"], 3) if st["attempted"] else 0,
                "seqs": st["wrong_seqs"],
            }
        )
    wrong_ability.sort(key=lambda x: (-x["wrong_count"], -x["wrong_rate"]))

    wrong_diff = []
    for b in DIFF_BUCKETS:
        wc = int(diff_wrong.get(b, 0))
        ac = int(diff_all.get(b, 0))
        if wc <= 0 and ac <= 0:
            continue
        wrong_diff.append(
            {
                "bucket": b,
                "wrong_count": wc,
                "attempted": ac,
                "wrong_rate": round(wc / ac, 3) if ac else 0,
            }
        )

    if not wrong_items:
        wrong_qual = "本次没有判定为错误的题目（或错题均待人工核验），整体掌握较好。"
    else:
        top_dims = [x["dimension"] for x in wrong_ability[:2]]
        top_diff = max(wrong_diff, key=lambda x: x["wrong_count"])["bucket"] if wrong_diff else "中等"
        link_counter: Counter = Counter()
        for w in wrong_items:
            link_counter.update(w.get("error_links") or [])
        top_links = [k for k, _ in link_counter.most_common(3)]
        if top_diff == "简单":
            diff_msg = "错题里简单题占比较高，更可能存在审题不细或粗心失分。"
        elif top_diff == "困难":
            diff_msg = "错题更多集中在困难题，说明挑战题的建模与推理仍需加强。"
        else:
            diff_msg = "错题难度以中等为主，需同时关注方法选择与运算准确性。"
        wrong_qual = (
            f"错题共 {len(wrong_items)} 道，能力维度上较多涉及「{'、'.join(top_dims) or '综合'}」；"
            f"{diff_msg}共性失误环节偏向「{'、'.join(top_links) or '审题'}」。"
        )

    report: Dict[str, Any] = {
        "version": "v1",
        "status": "ready",
        "score": {
            "earned": earned,
            "total": total,
            "correct_count": correct_count,
            "total_count": len(questions),
            "pending_count": pending_count,
            "graded_count": graded_count,
        },
        "overall": {
            "summary": overall_summary,
            "strengths": strong,
            "weaknesses": weak,
            "progress_comment": progress_comment,
            "progress": progress,
        },
        "wrong_analysis": {
            "ability_distribution": wrong_ability,
            "difficulty_distribution": wrong_diff,
            "knowledge_distribution": sorted(
                kp_wrong.values(), key=lambda x: -x["wrong_count"]
            ),
            "category_distribution": sorted(
                cat_wrong.values(), key=lambda x: -x["wrong_count"]
            ),
            "qualitative": wrong_qual,
        },
        "knowledge_items": wrong_items,
        "ability_overview": [
            {
                **st,
                "accuracy": round(
                    (st["score_got"] / st["score_full"])
                    if st["score_full"]
                    else (st["correct"] / st["attempted"] if st["attempted"] else 0),
                    3,
                ),
            }
            for st in ability_stats.values()
            if st["attempted"] > 0
        ],
        "llm_used": False,
    }

    if use_llm and wrong_items:
        try:
            enriched = await _enrich_with_llm(db, report)
            if enriched:
                report = enriched
                report["llm_used"] = True
        except Exception as e:
            logger.warning("能力评估 LLM 润色失败，使用规则结果: %s", e)
            report["llm_error"] = str(e)[:200]

    return report


async def _enrich_with_llm(
    db: AsyncSession, report: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    rows = (await db.execute(select(SystemConfig))).scalars().all()
    configs = {r.key: r.value for r in rows}
    if not (configs.get("llm_api_key") or "").strip():
        return None
    llm = create_llm_client(configs)
    wrong = report.get("knowledge_items") or []
    payload = {
        "score": report.get("score"),
        "strengths": (report.get("overall") or {}).get("strengths"),
        "weaknesses": (report.get("overall") or {}).get("weaknesses"),
        "progress": (report.get("overall") or {}).get("progress"),
        "wrong_ability": (report.get("wrong_analysis") or {}).get("ability_distribution"),
        "wrong_difficulty": (report.get("wrong_analysis") or {}).get(
            "difficulty_distribution"
        ),
        "wrong_kp": ((report.get("wrong_analysis") or {}).get("knowledge_distribution") or [])[
            :8
        ],
        "wrong_items": [
            {
                "seq": w["seq"],
                "ability_dimension": w.get("ability_dimension"),
                "difficulty_bucket": w.get("difficulty_bucket"),
                "kp_name": w.get("kp_name"),
                "category_1": w.get("category_1"),
                "preview": w.get("content_preview"),
                "rule_guess": w.get("reason"),
            }
            for w in wrong[:12]
        ],
        "error_link_enum": list(ERROR_LINKS),
        "ability_enum": list(ABILITY_ORDER),
    }
    data = await llm.extract_json(
        NARRATIVE_SYSTEM,
        "请基于以下学情数据生成诊断 JSON：\n" + json.dumps(payload, ensure_ascii=False),
    )
    if not isinstance(data, dict):
        return None

    overall = report.setdefault("overall", {})
    if data.get("overall_summary"):
        overall["summary"] = str(data["overall_summary"]).strip()
    if data.get("progress_comment"):
        overall["progress_comment"] = str(data["progress_comment"]).strip()
    wa = report.setdefault("wrong_analysis", {})
    if data.get("wrong_qualitative"):
        wa["qualitative"] = str(data["wrong_qualitative"]).strip()

    comments = data.get("item_comments") or []
    by_seq = {
        int(c.get("seq")): c
        for c in comments
        if isinstance(c, dict) and c.get("seq") is not None
    }
    for item in report.get("knowledge_items") or []:
        c = by_seq.get(int(item["seq"]))
        if not c:
            continue
        links = [x for x in (c.get("error_links") or []) if x in ERROR_LINKS]
        if links:
            item["error_links"] = links[:3]
        if c.get("ability_gap"):
            item["ability_gap"] = str(c["ability_gap"])
        if c.get("reason"):
            item["reason"] = str(c["reason"]).strip()
    return report


async def generate_and_store(
    db: AsyncSession,
    *,
    paper: TestPaper,
    questions: List[TestQuestion],
    answers_map: Dict[int, TestAnswer],
    use_llm: bool = True,
) -> Dict[str, Any]:
    paper.assessment_status = "pending"
    await db.flush()
    try:
        report = await build_assessment(
            db,
            paper=paper,
            questions=questions,
            answers_map=answers_map,
            use_llm=use_llm,
        )
        paper.assessment_json = report
        paper.assessment_status = "ready"
    except Exception as e:
        logger.exception("能力评估生成失败")
        paper.assessment_status = "failed"
        paper.assessment_json = {
            "version": "v1",
            "status": "failed",
            "error": str(e)[:300],
        }
        raise
    await db.flush()
    return paper.assessment_json or {}
