"""学习目标知识图谱：知识点依赖、测评题目与掌握状态推断。"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha1
from math import exp
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint, KnowledgeRelation
from app.models.student.test_paper import TestAnswer, TestPaper, TestQuestion
from app.models.student.mastery_sync import CourseMasterySync
from app.services.learning import goal_service
from app.services.learning.chapter_kp import expand_learned_scope_to_kp_ids


def _question_kp_ids(question: TestQuestion) -> List[str]:
    ids: List[str] = []
    if question.primary_kp_id:
        ids.append(question.primary_kp_id)
    for kp_id in question.secondary_kp_ids or []:
        if kp_id and kp_id not in ids:
            ids.append(str(kp_id))
    return ids


def _question_identity(question: TestQuestion) -> str:
    """Return a stable key for grouping the same question across test attempts."""
    if question.source_question_id:
        return f"source:{question.source_question_id}"
    normalized_content = " ".join((question.content or "").split())
    digest = sha1(normalized_content.encode("utf-8")).hexdigest()[:16]
    return f"content:{digest}"


def _iso_datetime(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


ATTEMPT_DECAY = 0.75
MAX_ATTEMPTS = 10
FORWARD_NEGATIVE_FACTOR = 0.50
BACKWARD_POSITIVE_FACTOR = 0.60
MAX_INFERENCE_DEPTH = 3


def _difficulty_weights(difficulty: Optional[int]) -> tuple[float, float]:
    value = difficulty or 3
    if value <= 2:
        return 0.8, 1.2
    if value >= 4:
        return 1.2, 0.8
    return 1.0, 1.0


def _mastery_level(score: Optional[float]) -> str:
    if score is None:
        return "l0"
    if score <= 20:
        return "l1"
    if score <= 40:
        return "l2"
    if score < 60:
        return "l3"
    if score < 75:
        return "l4"
    if score < 90:
        return "l5"
    return "l6"


def _reachable_with_distance(
    start: str, adjacency: Dict[str, Set[str]]
) -> Dict[str, int]:
    distances: Dict[str, int] = {}
    frontier = {start}
    for distance in range(1, MAX_INFERENCE_DEPTH + 1):
        next_frontier: Set[str] = set()
        for node_id in frontier:
            for neighbor in adjacency.get(node_id, set()):
                if neighbor == start or neighbor in distances:
                    continue
                distances[neighbor] = distance
                next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    return distances


def _calculate_mastery(
    events_by_kp: Dict[str, List[Dict[str, float]]],
    prerequisite_edges: List[tuple[str, str]],
    visible_ids: Set[str],
) -> Dict[str, Dict[str, Any]]:
    direct: Dict[str, Dict[str, Any]] = {}
    for kp_id in visible_ids:
        events = events_by_kp.get(kp_id, [])[-MAX_ATTEMPTS:]
        positive = 0.0
        negative = 0.0
        for distance, event in enumerate(reversed(events)):
            attempt_weight = ATTEMPT_DECAY ** distance
            correct_weight, wrong_weight = _difficulty_weights(
                int(event["difficulty"])
            )
            base = attempt_weight * event["role_weight"]
            positive += base * event["correctness"] * correct_weight
            negative += base * (1 - event["correctness"]) * wrong_weight

        correct_streak = 0
        wrong_streak = 0
        for event in reversed(events):
            if event["correctness"] >= 0.8 and wrong_streak == 0:
                correct_streak += 1
            elif event["correctness"] <= 0.4 and correct_streak == 0:
                wrong_streak += 1
            else:
                break
        direct[kp_id] = {
            "positive": positive,
            "negative": negative,
            "attempt_count": len(events),
            "correct_streak": correct_streak,
            "wrong_streak": wrong_streak,
        }

    forward: Dict[str, Set[str]] = defaultdict(set)
    backward: Dict[str, Set[str]] = defaultdict(set)
    for prerequisite, dependent in prerequisite_edges:
        forward[prerequisite].add(dependent)
        backward[dependent].add(prerequisite)

    inferred_positive: Dict[str, float] = defaultdict(float)
    inferred_negative: Dict[str, float] = defaultdict(float)
    inferred_positive_sources: Dict[str, Set[str]] = defaultdict(set)
    inferred_negative_sources: Dict[str, Set[str]] = defaultdict(set)

    for source_id, evidence in direct.items():
        if evidence["positive"] > 0:
            for target_id, distance in _reachable_with_distance(
                source_id, backward
            ).items():
                value = evidence["positive"] * (
                    BACKWARD_POSITIVE_FACTOR ** distance
                )
                inferred_positive[target_id] += value
                inferred_positive_sources[target_id].add(source_id)
        if evidence["negative"] > 0:
            for target_id, distance in _reachable_with_distance(
                source_id, forward
            ).items():
                value = evidence["negative"] * (
                    FORWARD_NEGATIVE_FACTOR ** distance
                )
                inferred_negative[target_id] += value
                inferred_negative_sources[target_id].add(source_id)

    result: Dict[str, Dict[str, Any]] = {}
    for kp_id in visible_ids:
        evidence = direct[kp_id]
        direct_total = evidence["positive"] + evidence["negative"]
        inferred_pos = inferred_positive[kp_id]
        inferred_neg = inferred_negative[kp_id]
        inferred_total = inferred_pos + inferred_neg
        inferred_cap = max(1.5, direct_total * 0.6) if direct_total else 2.5
        if inferred_total > inferred_cap:
            scale = inferred_cap / inferred_total
            inferred_pos *= scale
            inferred_neg *= scale

        total_evidence = direct_total + inferred_pos + inferred_neg
        # 没有直接作答的知识点保持未测评状态。关系证据只用于修正已有
        # 直接作答节点的最终掌握分，不单独生成另一套“推断状态”。
        if direct_total <= 0:
            score = None
            confidence = 0.0
            status = "untested"
            source = "none"
        else:
            score = round(
                (0.5 + evidence["positive"] + inferred_pos)
                / (1.0 + total_evidence)
                * 100,
                1,
            )
            confidence = 1 - exp(-total_evidence / 3)
            confidence = round(min(1.0, max(0.0, confidence)), 3)
            if (
                score >= 75
                and confidence >= 0.60
                and evidence["correct_streak"] >= 2
            ):
                status = "mastered"
            elif (
                score <= 40
                and confidence >= 0.60
                and evidence["wrong_streak"] >= 1
            ):
                status = "unmastered"
            else:
                status = "uncertain"
            source = "combined"

        result[kp_id] = {
            "mastery_score": score,
            "mastery_level": _mastery_level(score),
            "confidence": confidence,
            "status": status,
            "status_source": source,
            "direct_positive": round(evidence["positive"], 3),
            "direct_negative": round(evidence["negative"], 3),
            "inferred_positive": round(inferred_pos, 3),
            "inferred_negative": round(inferred_neg, 3),
            "attempt_count": evidence["attempt_count"],
            "recent_correct_streak": evidence["correct_streak"],
            "recent_wrong_streak": evidence["wrong_streak"],
        }
    return result


async def build_learning_map(
    db: AsyncSession, user_id: int, goal_id: int
) -> Dict[str, Any]:
    goal = await goal_service.get_owned_goal(db, goal_id, user_id)
    # 目标中的 learned_kp_ids 是创建/编辑目标时生成的快照。知识点或章节归属在
    # 后台更新后，该快照不会自动变化，因此学习地图必须按目标章节实时展开范围。
    chapter_ids = await goal_service.get_chapter_ids(db, goal.id)
    scope_ids = list(
        dict.fromkeys(
            await expand_learned_scope_to_kp_ids(
                db, goal.grade_stage, chapter_ids
            )
        )
    )

    goal_papers = list(
        (
            await db.execute(
                select(TestPaper)
                .where(
                    TestPaper.user_id == user_id,
                    TestPaper.goal_id == goal_id,
                    TestPaper.status == "graded",
                )
                .order_by(TestPaper.updated_at, TestPaper.id)
            )
        )
        .scalars()
        .all()
    )
    latest_paper = goal_papers[-1] if goal_papers else None

    all_questions: List[TestQuestion] = []
    all_answers: Dict[int, TestAnswer] = {}
    paper_ids = [paper.id for paper in goal_papers]
    if paper_ids:
        all_questions = list(
            (
                await db.execute(
                    select(TestQuestion)
                    .where(TestQuestion.test_paper_id.in_(paper_ids))
                    .order_by(
                        TestQuestion.test_paper_id,
                        TestQuestion.seq,
                        TestQuestion.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        all_answer_rows = (
            await db.execute(
                select(TestAnswer).where(TestAnswer.test_paper_id.in_(paper_ids))
            )
        ).scalars().all()
        all_answers = {row.test_question_id: row for row in all_answer_rows}
        paper_order = {paper.id: index for index, paper in enumerate(goal_papers)}
        all_questions.sort(
            key=lambda question: (
                paper_order.get(question.test_paper_id, len(paper_order)),
                question.seq,
                question.id,
            )
        )

    # 学习地图展示知识库中的最新完整图谱；目标范围只负责标识本目标覆盖的节点，
    # 不再把后台新增的知识点和跨范围关系过滤掉。
    all_kp_ids = (
        await db.execute(select(KnowledgePoint.id).order_by(KnowledgePoint.id))
    ).scalars().all()
    visible_ids: Set[str] = set(all_kp_ids)
    for question in all_questions:
        visible_ids.update(_question_kp_ids(question))

    if visible_ids:
        relation_rows = (
            await db.execute(
                select(KnowledgeRelation).where(
                    KnowledgeRelation.from_point_id.in_(visible_ids),
                    KnowledgeRelation.to_point_id.in_(visible_ids),
                )
            )
        ).scalars().all()
        kp_rows = (
            await db.execute(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(visible_ids))
            )
        ).scalars().all()
    else:
        relation_rows = []
        kp_rows = []

    kp_map = {row.id: row for row in kp_rows}
    stats: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"correct": 0, "wrong": 0, "pending": 0}
    )
    events_by_kp: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    question_nodes: List[Dict[str, Any]] = []
    question_summary_nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    paper_by_id = {paper.id: paper for paper in goal_papers}
    paper_attempt_index = {
        paper.id: index for index, paper in enumerate(goal_papers, start=1)
    }

    for question in all_questions:
        answer = all_answers.get(question.id)
        kp_ids = [kp_id for kp_id in _question_kp_ids(question) if kp_id in kp_map]
        if answer is None or answer.is_correct is None:
            correctness = 0.0
            for index, kp_id in enumerate(kp_ids):
                stats[kp_id]["wrong"] += 1
                events_by_kp[kp_id].append(
                    {
                        "correctness": correctness,
                        "difficulty": float(question.difficulty or 3),
                        "role_weight": 1.0 if index == 0 else 0.5,
                    }
                )
            continue
        full_score = float(question.score or 0)
        correctness = (
            min(1.0, max(0.0, float(answer.score_got or 0) / full_score))
            if full_score > 0
            else (1.0 if answer.is_correct else 0.0)
        )
        for index, kp_id in enumerate(kp_ids):
            stats[kp_id]["correct" if correctness >= 0.8 else "wrong"] += 1
            events_by_kp[kp_id].append(
                {
                    "correctness": correctness,
                    "difficulty": float(question.difficulty or 3),
                    "role_weight": 1.0 if index == 0 else 0.5,
                }
            )

    for question in all_questions:
        answer = all_answers.get(question.id)
        paper = paper_by_id.get(question.test_paper_id)
        score_full = float(question.score or 0)
        score_got = float(answer.score_got or 0) if answer else 0.0
        score_percent = (
            round(min(100.0, max(0.0, score_got / score_full * 100)), 1)
            if score_full > 0
            else (100.0 if answer is not None and answer.is_correct is True else 0.0)
        )
        question_status = (
            "correct"
            if score_percent >= 100
            else "partial"
            if score_percent > 0
            else "wrong"
        )
        kp_ids = [kp_id for kp_id in _question_kp_ids(question) if kp_id in kp_map]
        for kp_id in kp_ids:
            edges.append(
                {
                    "id": f"question:{question.id}:{kp_id}",
                    "source": f"kp:{kp_id}",
                    "target": f"question:{question.id}",
                    "type": "question",
                    "label": "考查",
                }
            )
        user_answer = None
        if answer:
            user_answer = answer.selected_option or answer.answer_text or None
        question_identity = _question_identity(question)
        question_nodes.append(
            {
                "id": f"question:{question.id}",
                "node_type": "question",
                "label": f"第 {question.seq} 题",
                "status": question_status,
                "view_scope": "attempt",
                "seq": question.seq,
                "question_type": question.question_type,
                "score": score_full,
                "score_got": score_got,
                "score_percent": score_percent,
                "score_level": _mastery_level(score_percent),
                "content": question.content,
                "options": question.options,
                "source_paper_id": question.source_exam_paper_id,
                "user_answer": user_answer,
                "correct_answer": question.answer,
                "analysis": question.analysis,
                "kp_ids": kp_ids,
                "question_identity": question_identity,
                "source_question_id": question.source_question_id,
                "test_paper_id": question.test_paper_id,
                "test_paper_title": paper.title if paper else None,
                "test_attempt_index": paper_attempt_index.get(
                    question.test_paper_id
                ),
                "tested_at": _iso_datetime(
                    answer.updated_at
                    if answer
                    else paper.updated_at
                    if paper
                    else None
                ),
                "attempt_count": 1,
            }
        )

    question_groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for node in question_nodes:
        question_groups[node["question_identity"]].append(node)

    for identity, attempts in question_groups.items():
        latest = attempts[-1]
        weighted_score = 0.0
        total_weight = 0.0
        for distance, attempt in enumerate(reversed(attempts[-MAX_ATTEMPTS:])):
            weight = ATTEMPT_DECAY ** distance
            weighted_score += float(attempt["score_percent"]) * weight
            total_weight += weight
        score_percent = round(weighted_score / total_weight, 1) if total_weight else 0.0
        summary_status = (
            "correct"
            if score_percent >= 100
            else "partial"
            if score_percent > 0
            else "wrong"
        )
        summary_id = f"question-summary:{identity}"
        kp_ids = list(
            dict.fromkeys(
                kp_id
                for attempt in attempts
                for kp_id in attempt.get("kp_ids", [])
            )
        )
        for kp_id in kp_ids:
            edges.append(
                {
                    "id": f"{summary_id}:{kp_id}",
                    "source": f"kp:{kp_id}",
                    "target": summary_id,
                    "type": "question",
                    "label": "考查",
                }
            )
        question_summary_nodes.append(
            {
                **latest,
                "id": summary_id,
                "label": (
                    f"同题 {len(attempts)} 次"
                    if len(attempts) > 1
                    else latest["label"]
                ),
                "status": summary_status,
                "view_scope": "summary",
                "score": 100.0,
                "score_got": score_percent,
                "score_percent": score_percent,
                "score_level": _mastery_level(score_percent),
                "kp_ids": kp_ids,
                "test_paper_id": None,
                "test_paper_title": "全部测试汇总",
                "test_attempt_index": None,
                "tested_at": latest.get("tested_at"),
                "attempt_count": len(attempts),
            }
        )

    prerequisite_edges = []
    for relation in relation_rows:
        edge = {
            "id": f"relation:{relation.id}",
            "source": f"kp:{relation.from_point_id}",
            "target": f"kp:{relation.to_point_id}",
            "type": relation.relation_type,
            "label": "前置依赖" if relation.relation_type == "prerequisite" else "相关",
        }
        edges.append(edge)
        if relation.relation_type == "prerequisite":
            prerequisite_edges.append((relation.from_point_id, relation.to_point_id))

    mastery = _calculate_mastery(
        events_by_kp, prerequisite_edges, visible_ids
    )
    course_syncs = list(
        (
            await db.execute(
                select(CourseMasterySync).where(
                    CourseMasterySync.user_id == user_id,
                    CourseMasterySync.goal_id == goal_id,
                )
            )
        ).scalars().all()
    )
    latest_assessment_at = (
        (latest_paper.updated_at or latest_paper.created_at)
        if latest_paper is not None
        else None
    )
    for sync in course_syncs:
        # 同步后完成的新测评代表更新的正式证据，学习地图恢复使用测评算法结果。
        if latest_assessment_at and sync.synced_at and latest_assessment_at > sync.synced_at:
            continue
        if sync.kp_id not in mastery:
            continue
        score = round(float(sync.mastery_score), 1)
        confidence = round(float(sync.confidence), 3)
        if bool(sync.achieved):
            status = "mastered"
        elif score <= 40 and confidence >= 0.55:
            status = "unmastered"
        else:
            status = "uncertain"
        evidence = sync.evidence_json or {}
        mastery[sync.kp_id].update(
            {
                "mastery_score": score,
                "mastery_level": _mastery_level(score),
                "confidence": confidence,
                "status": status,
                "status_source": "course_sync",
                "attempt_count": int(evidence.get("answered_count") or 0),
                "recent_correct_streak": 0,
                "recent_wrong_streak": 0,
                "course_synced_at": _iso_datetime(sync.synced_at),
            }
        )

    kp_nodes: List[Dict[str, Any]] = []
    for kp_id in scope_ids + sorted(visible_ids - set(scope_ids)):
        kp = kp_map.get(kp_id)
        if kp is None:
            continue
        mastery_data = mastery[kp_id]
        kp_nodes.append(
            {
                "id": f"kp:{kp.id}",
                "node_type": "knowledge",
                "label": (kp.short_name or "").strip() or kp.name,
                "status": mastery_data["status"],
                "inferred_status": None,
                **mastery_data,
                "kp_id": kp.id,
                "description": kp.name,
                "domain": kp.domain,
                "category_1": kp.category_1,
                "category_2": kp.category_2,
                "grade": kp.grade,
                "chapter": kp.chapter,
                "cognitive_level": kp.cognitive_level,
                "is_in_goal_scope": kp.id in scope_ids,
                "question_stats": stats[kp_id],
            }
        )

    return {
        "goal": {
            "id": goal.id,
            "title": goal.title
            or f"{goal.exam_type}{goal.subject}冲{goal.target_score:g}",
            "subject": goal.subject,
            "grade_stage": goal.grade_stage,
            "target_score": goal.target_score,
        },
        "paper": (
            {
                "id": latest_paper.id,
                "title": latest_paper.title,
                "earned_score": latest_paper.earned_score,
                "total_score": latest_paper.total_score,
            }
            if latest_paper
            else None
        ),
        "papers": [
            {
                "id": paper.id,
                "title": paper.title or f"第 {paper_attempt_index[paper.id]} 次测试",
                "earned_score": paper.earned_score,
                "total_score": paper.total_score,
                "attempt_index": paper_attempt_index[paper.id],
                "tested_at": _iso_datetime(paper.updated_at or paper.created_at),
                "question_count": sum(
                    1
                    for question in all_questions
                    if question.test_paper_id == paper.id
                ),
            }
            for paper in reversed(goal_papers)
        ],
        "nodes": [*kp_nodes, *question_nodes, *question_summary_nodes],
        "edges": edges,
        "summary": {
            "knowledge_count": len(kp_nodes),
            "question_count": len(question_nodes),
            "summary_question_count": len(question_summary_nodes),
            "test_count": len(goal_papers),
            "relation_count": len(relation_rows),
            "has_assessment": latest_paper is not None,
        },
    }
