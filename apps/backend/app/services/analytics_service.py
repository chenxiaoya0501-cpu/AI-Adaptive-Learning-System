"""后台学习规律分析。

所有曲线都只使用数据库中的真实行为记录。样本不足时返回空曲线和明确状态，
避免把路径规划中的经验参数伪装成学生统计结果。
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint, KnowledgeRelation
from app.models.question import ExamKpScoreStat, Question
from app.schemas.question import ABILITY_DIMENSIONS
from app.models.student.goal import LearningGoal
from app.models.student.learning_path import LearningPath, LearningPathNode, LearningTask
from app.models.student.mastery_sync import CourseMasterySync
from app.models.student.test_paper import TestAnswer, TestPaper, TestQuestion
from app.models.user import User
from app.services.learning.mastery_evaluator import evaluate_mastery
from app.services.learning import assembly, targeted_question_selector
from app.services.learning.diagnostic_priority import calculate_diagnostic_priority
from app.services.learning.mastery_snapshot import build_mastery_snapshot
from app.services.learning.path_planner import UNLOCK_ALPHA
from app.services.learning.path_service import load_exam_weights


def _json(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _mean(values: Iterable[float]) -> Optional[float]:
    items = list(values)
    return round(sum(items) / len(items), 2) if items else None


def _point(label: str, value: Optional[float], sample_size: int) -> Dict[str, Any]:
    return {
        "label": label,
        "value": None if value is None else round(float(value), 2),
        "sample_size": sample_size,
    }


def _parameter(
    key: str,
    name: str,
    description: str,
    unit: str,
    points: List[Dict[str, Any]],
    *,
    minimum_sample: int = 5,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    sample_size = sum(int(point.get("sample_size") or 0) for point in points)
    valid_points = [point for point in points if point.get("value") is not None]
    status = (
        "unavailable"
        if not valid_points
        else "ready"
        if sample_size >= minimum_sample
        else "limited"
    )
    return {
        "key": key,
        "name": name,
        "description": description,
        "unit": unit,
        "status": status,
        "sample_size": sample_size,
        "curve": points,
        "note": note
        or (
            "暂无可计算的历史行为记录"
            if status == "unavailable"
            else "当前样本量较少，仅供观察，不建议直接用于模型校准"
            if status == "limited"
            else None
        ),
    }


def _bucket(value: Optional[float]) -> str:
    score = 50.0 if value is None else max(0.0, min(100.0, float(value)))
    low = int(score // 20) * 20
    if low >= 80:
        return "80–100"
    return f"{low}–{low + 19}"


async def _practice_records(
    db: AsyncSession,
    user_id: Optional[int] = None,
    kp_ids: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    query = (
        select(LearningTask, LearningPathNode, LearningPath)
        .join(LearningPathNode, LearningTask.path_node_id == LearningPathNode.id)
        .join(LearningPath, LearningTask.path_id == LearningPath.id)
        .where(
            LearningTask.task_type.in_(("practice", "training", "checkpoint")),
            LearningTask.result_json.is_not(None),
        )
    )
    if user_id is not None:
        query = query.where(LearningTask.user_id == user_id)
    if kp_ids is not None:
        query = query.where(
            LearningPathNode.kp_id.in_(kp_ids if kp_ids else {"__empty_scope__"})
        )
    rows = (await db.execute(query)).all()

    # practice/checkpoint 可能保存同一轮结果，每个路径节点只保留信息最完整的一份。
    by_node: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for task, node, path in rows:
        result = _json(task.result_json)
        evaluation = _json(result.get("evaluation"))
        history = result.get("answer_history")
        history = history if isinstance(history, list) else []
        if not evaluation and not history:
            continue
        record = {
            "user_id": task.user_id,
            "goal_id": path.goal_id,
            "path_id": path.id,
            "node_id": node.id,
            "kp_id": node.kp_id,
            "target_mastery": node.target_mastery,
            "estimated_minutes": task.estimated_minutes,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "created_at": task.created_at,
            "evaluation": evaluation,
            "history": history,
        }
        key = (task.user_id, node.id)
        previous = by_node.get(key)
        if previous is None or len(history) > len(previous["history"]):
            by_node[key] = record
    return list(by_node.values())


async def _answer_events(
    db: AsyncSession,
    user_id: Optional[int] = None,
    kp_ids: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    query = (
        select(TestAnswer, TestQuestion, TestPaper)
        .join(TestQuestion, TestAnswer.test_question_id == TestQuestion.id)
        .join(TestPaper, TestAnswer.test_paper_id == TestPaper.id)
        .where(TestPaper.status == "graded", TestAnswer.is_correct.is_not(None))
    )
    if user_id is not None:
        query = query.where(TestPaper.user_id == user_id)
    if kp_ids is not None:
        query = query.where(
            TestQuestion.primary_kp_id.in_(
                kp_ids if kp_ids else {"__empty_scope__"}
            )
        )
    events = []
    for answer, question, paper in (await db.execute(query)).all():
        events.append(
            {
                "user_id": paper.user_id,
                "goal_id": paper.goal_id,
                "kp_id": question.primary_kp_id,
                "difficulty": max(1, min(5, int(question.difficulty or 3))),
                "ability_dimension": (
                    question.ability_dimension.strip()
                    if question.ability_dimension
                    else None
                ),
                "correct": bool(answer.is_correct),
                "created_at": answer.updated_at or answer.created_at or paper.updated_at,
                "paper_id": paper.id,
            }
        )
    return events


def _difficulty_curve(
    practices: List[Dict[str, Any]], events: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    buckets: Dict[int, List[float]] = defaultdict(list)
    for record in practices:
        for answer in record["history"]:
            difficulty = max(1, min(5, int(answer.get("difficulty") or 3)))
            buckets[difficulty].append(100.0 if answer.get("is_correct") else 0.0)
    for event in events:
        buckets[event["difficulty"]].append(100.0 if event["correct"] else 0.0)
    return [
        _point(f"难度 {difficulty}", _mean(buckets[difficulty]), len(buckets[difficulty]))
        for difficulty in range(1, 6)
    ]


async def _ability_dimension_curve(
    db: AsyncSession,
    practices: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """按题库统一的六个能力维度统计个人作答正确率。"""
    question_ids = {
        int(answer["question_id"])
        for record in practices
        for answer in record["history"]
        if answer.get("question_id") is not None
        and str(answer.get("question_id")).isdigit()
    }
    dimension_by_question: Dict[int, Optional[str]] = {}
    if question_ids:
        rows = (
            await db.execute(
                select(Question.id, Question.ability_dimension).where(
                    Question.id.in_(question_ids)
                )
            )
        ).all()
        dimension_by_question = {
            question_id: (dimension.strip() if dimension else None)
            for question_id, dimension in rows
        }

    buckets: Dict[str, List[float]] = defaultdict(list)
    for record in practices:
        for answer in record["history"]:
            raw_id = answer.get("question_id")
            if raw_id is None or not str(raw_id).isdigit():
                continue
            dimension = dimension_by_question.get(int(raw_id))
            if dimension in ABILITY_DIMENSIONS:
                buckets[dimension].append(
                    100.0 if answer.get("is_correct") else 0.0
                )
    for event in events:
        dimension = event.get("ability_dimension")
        if dimension in ABILITY_DIMENSIONS:
            buckets[dimension].append(100.0 if event["correct"] else 0.0)

    return [
        _point(
            dimension,
            _mean(buckets[dimension]),
            len(buckets[dimension]),
        )
        for dimension in ABILITY_DIMENSIONS
    ]


def _mastery_growth_curve(practices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: Dict[int, List[float]] = defaultdict(list)
    for record in practices:
        history = record["history"]
        evaluation = record["evaluation"]
        prior = evaluation.get("prior_mastery")
        for count in range(1, len(history) + 1):
            result = evaluate_mastery(history[:count], record["target_mastery"], prior)
            values[count].append(float(result["mastery_score"]))
    return [
        _point(f"{count}题", _mean(values[count]), len(values[count]))
        for count in sorted(values)
    ]


def _initial_gain_curve(practices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: Dict[str, List[float]] = defaultdict(list)
    order = ("0–19", "20–39", "40–59", "60–79", "80–100")
    for record in practices:
        evaluation = record["evaluation"]
        prior = evaluation.get("prior_mastery")
        mastery = evaluation.get("mastery_score")
        if mastery is None:
            continue
        baseline = 50.0 if prior is None else float(prior)
        values[_bucket(prior)].append(float(mastery) - baseline)
    return [_point(label, _mean(values[label]), len(values[label])) for label in order]


def _success_curve(practices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: Dict[str, List[float]] = defaultdict(list)
    order = ("0–19", "20–39", "40–59", "60–79", "80–100")
    for record in practices:
        evaluation = record["evaluation"]
        values[_bucket(evaluation.get("prior_mastery"))].append(
            100.0 if evaluation.get("achieved") else 0.0
        )
    return [_point(label, _mean(values[label]), len(values[label])) for label in order]


def _duration_curve(practices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: Dict[str, List[float]] = defaultdict(list)
    for record in practices:
        started = record.get("started_at")
        completed = record.get("completed_at")
        if not started or not completed:
            continue
        minutes = (completed - started).total_seconds() / 60
        # 过滤误触、倒置时间和明显挂机记录，避免异常值扭曲时长依据。
        if minutes < 1 or minutes > 180:
            continue
        values[_bucket(record["evaluation"].get("prior_mastery"))].append(minutes)
    order = ("0–19", "20–39", "40–59", "60–79", "80–100")
    return [_point(label, _mean(values[label]), len(values[label])) for label in order]


def _forgetting_curve(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["kp_id"] and event["created_at"]:
            grouped[(event["user_id"], event["kp_id"])].append(event)
    buckets: Dict[str, List[float]] = defaultdict(list)
    for items in grouped.values():
        items.sort(key=lambda item: item["created_at"])
        for previous, current in zip(items, items[1:]):
            days = max(0, (current["created_at"] - previous["created_at"]).days)
            label = "0–1天" if days <= 1 else "2–3天" if days <= 3 else "4–7天" if days <= 7 else "8天以上"
            buckets[label].append(100.0 if current["correct"] else 0.0)
    order = ("0–1天", "2–3天", "4–7天", "8天以上")
    return [_point(label, _mean(buckets[label]), len(buckets[label])) for label in order]


async def _transfer_curve(
    db: AsyncSession,
    events: List[Dict[str, Any]],
    user_id: Optional[int] = None,
    kp_ids: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    query = select(CourseMasterySync)
    if user_id is not None:
        query = query.where(CourseMasterySync.user_id == user_id)
    if kp_ids is not None:
        query = query.where(
            CourseMasterySync.kp_id.in_(kp_ids if kp_ids else {"__empty_scope__"})
        )
    syncs = (await db.execute(query)).scalars().all()
    buckets: Dict[str, List[float]] = defaultdict(list)
    for sync in syncs:
        later = [
            event
            for event in events
            if event["user_id"] == sync.user_id
            and event["kp_id"] == sync.kp_id
            and event["created_at"]
            and sync.synced_at
            and event["created_at"] > sync.synced_at
        ]
        if later:
            buckets[_bucket(sync.mastery_score)].extend(
                100.0 if event["correct"] else 0.0 for event in later
            )
    order = ("0–19", "20–39", "40–59", "60–79", "80–100")
    return [_point(label, _mean(buckets[label]), len(buckets[label])) for label in order]


async def _prerequisite_impact_curve(
    db: AsyncSession,
    events: List[Dict[str, Any]],
    dependent_ids: Optional[set[str]] = None,
) -> List[Dict[str, Any]]:
    relations = (
        await db.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.relation_type == "prerequisite"
            )
        )
    ).scalars().all()
    relation_pairs = {
        (relation.from_point_id, relation.to_point_id)
        for relation in relations
        if dependent_ids is None or relation.to_point_id in dependent_ids
    }
    by_paper_kp: Dict[Tuple[int, str], List[float]] = defaultdict(list)
    for event in events:
        if event["kp_id"]:
            by_paper_kp[(event["paper_id"], event["kp_id"])].append(
                100.0 if event["correct"] else 0.0
            )
    buckets: Dict[str, List[float]] = defaultdict(list)
    paper_ids = {event["paper_id"] for event in events}
    for paper_id in paper_ids:
        for prerequisite, dependent in relation_pairs:
            prerequisite_values = by_paper_kp.get((paper_id, prerequisite))
            dependent_values = by_paper_kp.get((paper_id, dependent))
            if not prerequisite_values or not dependent_values:
                continue
            label = (
                "前置表现较好"
                if sum(prerequisite_values) / len(prerequisite_values) >= 60
                else "前置表现较弱"
            )
            buckets[label].extend(dependent_values)
    order = ("前置表现较弱", "前置表现较好")
    return [_point(label, _mean(buckets[label]), len(buckets[label])) for label in order]


def _streak_curve(practices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: Dict[int, List[float]] = defaultdict(list)
    for record in practices:
        streak = 0
        for index, answer in enumerate(record["history"], start=1):
            correct = bool(answer.get("is_correct"))
            if correct:
                streak = streak + 1 if streak >= 0 else 1
            else:
                streak = streak - 1 if streak <= 0 else -1
            values[index].append(float(streak))
    return [
        _point(f"第{index}题", _mean(values[index]), len(values[index]))
        for index in sorted(values)
    ]


def _confidence_curve(practices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    values: Dict[int, List[float]] = defaultdict(list)
    for record in practices:
        prior = record["evaluation"].get("prior_mastery")
        for count in range(1, len(record["history"]) + 1):
            evaluated = evaluate_mastery(
                record["history"][:count], record["target_mastery"], prior
            )
            values[count].append(float(evaluated["confidence"]) * 100)
    return [
        _point(f"{count}题", _mean(values[count]), len(values[count]))
        for count in sorted(values)
    ]


async def knowledge_scope(
    db: AsyncSession,
    domain: Optional[str] = None,
    category_1: Optional[str] = None,
    category_2: Optional[str] = None,
    kp_id: Optional[str] = None,
) -> Dict[str, Any]:
    filters = [KnowledgePoint.id == kp_id] if kp_id else []
    if domain:
        filters.append(KnowledgePoint.domain == domain)
    if category_1:
        filters.append(KnowledgePoint.category_1 == category_1)
    if category_2:
        filters.append(KnowledgePoint.category_2 == category_2)
    query = select(KnowledgePoint)
    if filters:
        query = query.where(*filters)
    points = (await db.execute(query.order_by(KnowledgePoint.id.asc()))).scalars().all()
    selected = points[0] if kp_id and points else None
    return {
        "kp_ids": {point.id for point in points},
        "filtered": bool(domain or category_1 or category_2 or kp_id),
        "selection": {
            "domain": domain,
            "category_1": category_1,
            "category_2": category_2,
            "kp_id": kp_id,
            "kp_name": (
                selected.short_name or selected.name if selected is not None else None
            ),
            "knowledge_point_count": len(points),
        },
    }


async def knowledge_options(db: AsyncSession) -> Dict[str, Any]:
    points = (
        await db.execute(
            select(KnowledgePoint).order_by(
                KnowledgePoint.domain.asc(),
                KnowledgePoint.category_1.asc(),
                KnowledgePoint.category_2.asc(),
                KnowledgePoint.id.asc(),
            )
        )
    ).scalars().all()
    domains = sorted({point.domain for point in points if point.domain})
    categories_1 = sorted(
        {
            (point.domain, point.category_1)
            for point in points
            if point.domain and point.category_1
        }
    )
    categories_2 = sorted(
        {
            (point.domain, point.category_1, point.category_2)
            for point in points
            if point.domain and point.category_1 and point.category_2
        }
    )
    return {
        "domains": [{"value": value, "label": value} for value in domains],
        "categories_1": [
            {"domain": domain, "value": value, "label": value}
            for domain, value in categories_1
        ],
        "categories_2": [
            {
                "domain": domain,
                "category_1": category_1,
                "value": value,
                "label": value,
            }
            for domain, category_1, value in categories_2
        ],
        "knowledge_points": [
            {
                "domain": point.domain,
                "category_1": point.category_1,
                "category_2": point.category_2,
                "value": point.id,
                "label": point.short_name or point.name,
            }
            for point in points
        ],
    }


async def population_analysis(
    db: AsyncSession,
    domain: Optional[str] = None,
    category_1: Optional[str] = None,
    category_2: Optional[str] = None,
    kp_id: Optional[str] = None,
) -> Dict[str, Any]:
    scope = await knowledge_scope(db, domain, category_1, category_2, kp_id)
    kp_ids = scope["kp_ids"] if scope["filtered"] else None
    practices = await _practice_records(db, kp_ids=kp_ids)
    events = await _answer_events(db, kp_ids=kp_ids)
    relation_events = (
        await _answer_events(db) if scope["filtered"] else events
    )
    student_count = (
        await db.execute(select(User.id).where(User.role == "student"))
    ).scalars().all()
    graded_count = {event["paper_id"] for event in events}
    relevant_student_ids = {
        *(event["user_id"] for event in events),
        *(record["user_id"] for record in practices),
    }
    transfer = await _transfer_curve(db, events, kp_ids=kp_ids)
    prerequisite_impact = await _prerequisite_impact_curve(
        db, relation_events, kp_ids
    )

    parameters = [
        _parameter(
            "learning_duration",
            "平均学习时长",
            "不同初始掌握度学生完成知识点学习所需的真实平均时间",
            "分钟",
            _duration_curve(practices),
            minimum_sample=10,
        ),
        _parameter(
            "mastery_gain",
            "平均掌握度提升",
            "不同初始水平完成一轮学习后的平均掌握度增量",
            "分",
            _initial_gain_curve(practices),
            minimum_sample=10,
        ),
        _parameter(
            "difficulty_accuracy",
            "题目难度—正确率",
            "全体学生在不同难度题目上的平均正确率，用于校准难度权重",
            "%",
            _difficulty_curve(practices, events),
            minimum_sample=20,
        ),
        _parameter(
            "learning_success",
            "知识点学习成功率",
            "不同初始掌握度下，一轮学习达到目标掌握度的比例",
            "%",
            _success_curve(practices),
            minimum_sample=10,
        ),
        _parameter(
            "mastery_growth",
            "练习题量—掌握度",
            "随着有效练习题量增加，全体学生的平均掌握度变化",
            "分",
            _mastery_growth_curve(practices),
            minimum_sample=20,
        ),
        _parameter(
            "transfer_rate",
            "学习成果迁移率",
            "课程学习同步后，在后续正式测评中正确应用该知识点的比例",
            "%",
            transfer,
            minimum_sample=10,
        ),
        _parameter(
            "forgetting",
            "复习间隔—保持率",
            "同一知识点两次正式测评间隔增长时，后一次作答的正确率",
            "%",
            _forgetting_curve(events),
            minimum_sample=20,
        ),
        _parameter(
            "prerequisite_impact",
            "前置知识影响",
            "前置知识表现较好或较弱时，后续知识点在同次测评中的正确率差异",
            "%",
            prerequisite_impact,
            minimum_sample=20,
        ),
    ]
    return {
        "scope": "population",
        "knowledge_scope": scope["selection"],
        "generated_at": datetime.utcnow().isoformat(),
        "summary": {
            "student_count": (
                len(relevant_student_ids) if scope["filtered"] else len(student_count)
            ),
            "graded_paper_count": len(graded_count),
            "answer_event_count": len(events),
            "course_session_count": len(practices),
            "ready_parameter_count": sum(p["status"] == "ready" for p in parameters),
        },
        "parameters": parameters,
    }


async def list_students(db: AsyncSession) -> List[Dict[str, Any]]:
    students = (
        await db.execute(
            select(User).where(User.role == "student").order_by(User.id.asc())
        )
    ).scalars().all()
    return [
        {
            "id": student.id,
            "name": student.nickname or student.email or student.phone or f"学生 {student.id}",
            "email": student.email,
        }
        for student in students
    ]


async def student_analysis(
    db: AsyncSession,
    user_id: int,
    domain: Optional[str] = None,
    category_1: Optional[str] = None,
    category_2: Optional[str] = None,
    kp_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    student = (
        await db.execute(
            select(User).where(User.id == user_id, User.role == "student")
        )
    ).scalar_one_or_none()
    if not student:
        return None
    scope = await knowledge_scope(db, domain, category_1, category_2, kp_id)
    kp_ids = scope["kp_ids"] if scope["filtered"] else None
    practices = await _practice_records(db, user_id, kp_ids)
    events = await _answer_events(db, user_id, kp_ids)
    transfer = await _transfer_curve(db, events, user_id, kp_ids)
    ability_accuracy = await _ability_dimension_curve(db, practices, events)

    goals = (
        await db.execute(
            select(LearningGoal)
            .where(LearningGoal.user_id == user_id)
            .order_by(LearningGoal.created_at.asc())
        )
    ).scalars().all()
    availability = [
        _point(
            goal.created_at.strftime("%m-%d") if goal.created_at else f"目标{goal.id}",
            goal.daily_study_minutes,
            1 if goal.daily_study_minutes is not None else 0,
        )
        for goal in goals
    ]

    reinforcement_values: Dict[int, List[float]] = defaultdict(list)
    reinforcement_rows = (
        await db.execute(
            select(LearningTask).where(
                LearningTask.user_id == user_id,
                LearningTask.task_type == "reinforcement",
                LearningTask.result_json.is_not(None),
            )
        )
    ).scalars().all()
    for task in reinforcement_rows:
        result = _json(task.result_json)
        evaluation = _json(result.get("evaluation"))
        before = evaluation.get("prior_mastery")
        after = evaluation.get("mastery_score")
        pass_index = int(result.get("pass_index") or 1)
        if before is not None and after is not None:
            reinforcement_values[pass_index].append(float(after) - float(before))
    reinforcement = [
        _point(f"第{index}轮", _mean(reinforcement_values[index]), len(reinforcement_values[index]))
        for index in sorted(reinforcement_values)
    ]

    parameters = [
        _parameter(
            "mastery_trajectory",
            "个人掌握度变化",
            "每完成一道课程练习题后，个人掌握度的实时变化",
            "分",
            _mastery_growth_curve(practices),
            minimum_sample=4,
        ),
        _parameter(
            "ability_accuracy",
            "不同能力维度的题目准确率分析",
            "按题库能力维度统计该学生的真实作答正确率；能力维度包括计算、理解、信息提取、推理、空间和记忆",
            "%",
            ability_accuracy,
            minimum_sample=8,
            note=(
                "仅统计已标注能力维度的题目；未标注题目不纳入本图"
                if any(point["sample_size"] for point in ability_accuracy)
                else None
            ),
        ),
        _parameter(
            "difficulty_accuracy",
            "个人难度正确率",
            "该学生在不同难度题目上的正确率",
            "%",
            _difficulty_curve(practices, events),
            minimum_sample=8,
        ),
        _parameter(
            "recent_streak",
            "近期连续表现",
            "正数表示连续答对，负数表示连续答错",
            "连续题数",
            _streak_curve(practices),
            minimum_sample=4,
        ),
        _parameter(
            "learning_duration",
            "个人学习时长",
            "不同初始掌握度下完成知识点学习的实际用时",
            "分钟",
            _duration_curve(practices),
            minimum_sample=3,
        ),
        _parameter(
            "mastery_gain",
            "学习前后提升",
            "按学习前掌握度分段统计的一轮学习提升幅度",
            "分",
            _initial_gain_curve(practices),
            minimum_sample=3,
        ),
        _parameter(
            "transfer_rate",
            "个人知识迁移率",
            "课程同步后在后续正式测评中的知识点正确率",
            "%",
            transfer,
            minimum_sample=5,
        ),
        _parameter(
            "forgetting",
            "个人遗忘曲线",
            "不同复习间隔下，同一知识点再次作答的保持率",
            "%",
            _forgetting_curve(events),
            minimum_sample=5,
        ),
        _parameter(
            "reinforcement_gain",
            "多轮强化收益",
            "每轮强化学习带来的掌握度增量",
            "分",
            reinforcement,
            minimum_sample=3,
        ),
        _parameter(
            "daily_capacity",
            "每日可投入时间",
            "该学生不同学习目标中配置的每日学习时间",
            "分钟",
            availability,
            minimum_sample=1,
        ),
    ]
    return {
        "scope": "student",
        "knowledge_scope": scope["selection"],
        "generated_at": datetime.utcnow().isoformat(),
        "student": {
            "id": student.id,
            "name": student.nickname or student.email or student.phone or f"学生 {student.id}",
            "email": student.email,
        },
        "summary": {
            "goal_count": len(goals),
            "graded_paper_count": len({event["paper_id"] for event in events}),
            "answer_event_count": len(events),
            "course_session_count": len(practices),
            "ready_parameter_count": sum(p["status"] == "ready" for p in parameters),
        },
        "parameters": parameters,
    }


def _metric_curve(
    key: str,
    name: str,
    unit: str,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    points = [
        _point(
            str(row["name"])[:12],
            row.get(key),
            1 if row.get(key) is not None else 0,
        )
        for row in rows[:12]
    ]
    return {
        "key": key,
        "name": name,
        "unit": unit,
        "sample_size": sum(point["sample_size"] for point in points),
        "curve": points,
    }


async def marginal_value_analysis(
    db: AsyncSession,
    user_id: int,
    domain: Optional[str] = None,
    category_1: Optional[str] = None,
    category_2: Optional[str] = None,
    kp_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    student = (
        await db.execute(
            select(User).where(User.id == user_id, User.role == "student")
        )
    ).scalar_one_or_none()
    if not student:
        return None

    scope = await knowledge_scope(db, domain, category_1, category_2, kp_id)
    kp_ids = scope["kp_ids"] if scope["filtered"] else None
    path = (
        await db.execute(
            select(LearningPath)
            .where(LearningPath.user_id == user_id)
            .order_by(LearningPath.id.desc())
        )
    ).scalars().first()
    if path is None:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "student": {
                "id": student.id,
                "name": student.nickname or student.email or f"学生 {student.id}",
            },
            "knowledge_scope": scope["selection"],
            "path": None,
            "summary": {"node_count": 0},
            "metrics": [],
        }

    query = (
        select(LearningPathNode, KnowledgePoint)
        .join(KnowledgePoint, LearningPathNode.kp_id == KnowledgePoint.id)
        .where(LearningPathNode.path_id == path.id)
        .order_by(LearningPathNode.order_index.asc())
    )
    if kp_ids is not None:
        query = query.where(
            LearningPathNode.kp_id.in_(kp_ids if kp_ids else {"__empty_scope__"})
        )
    node_rows = (await db.execute(query)).all()

    planning = _json(path.planning_params)
    goal_snapshot = _json(path.goal_snapshot)
    unlock_alpha = float(planning.get("unlock_alpha") or UNLOCK_ALPHA)
    total_score = planning.get("total_score")
    total_score = float(total_score) if total_score is not None else None

    rows: List[Dict[str, Any]] = []
    for node, point in node_rows:
        reason = _json(node.reason_json)
        effective = float(
            reason.get("effective_mastery")
            if reason.get("effective_mastery") is not None
            else 50.0
        )
        base_target = float(
            reason.get("base_target_mastery")
            if reason.get("base_target_mastery") is not None
            else node.target_mastery
        )
        learned_probability = reason.get("learnability")
        applied_transfer = reason.get("transfer_rate")
        direct_gain = float(reason.get("direct_gain") or node.expected_gain or 0)
        unlock_gain = float(reason.get("unlock_gain") or 0)
        strategic_value = direct_gain + unlock_alpha * unlock_gain
        marginal_value = strategic_value / max(int(node.estimated_minutes or 0), 1)
        rows.append(
            {
                "kp_id": node.kp_id,
                "name": point.short_name or point.name,
                "current_mastery": node.current_mastery,
                "target_mastery": base_target,
                "confidence": round(float(node.confidence or 0) * 100, 2),
                "total_score": total_score,
                "exam_weight": round(float(node.exam_weight or 0) * 100, 3),
                "unlock_alpha": unlock_alpha,
                "effective_mastery": round(effective, 2),
                "mastery_gap": round(max(0.0, base_target - effective), 2),
                "learnability": (
                    round(float(learned_probability) * 100, 2)
                    if learned_probability is not None
                    else None
                ),
                "transfer_rate": (
                    round(float(applied_transfer) * 100, 2)
                    if applied_transfer is not None
                    else None
                ),
                "cognitive_level": point.cognitive_level,
                "recent_correct_streak": int(reason.get("recent_correct_streak") or 0),
                "recent_wrong_streak": int(reason.get("recent_wrong_streak") or 0),
                "estimated_minutes": node.estimated_minutes,
                "unlock_gain": unlock_gain,
                "direct_gain": direct_gain,
                "strategic_value": strategic_value,
                "marginal_value": marginal_value,
            }
        )

    analyzed_kp_ids = {str(row["kp_id"]) for row in rows}
    practices = await _practice_records(
        db,
        user_id,
        analyzed_kp_ids if analyzed_kp_ids else {"__empty_scope__"},
    )
    answer_events = await _answer_events(
        db,
        user_id,
        analyzed_kp_ids if analyzed_kp_ids else {"__empty_scope__"},
    )
    practice_answer_count = sum(len(record["history"]) for record in practices)
    history_answer_count = len(answer_events) + practice_answer_count
    duration_sample_count = sum(
        bool(record.get("started_at") and record.get("completed_at"))
        for record in practices
    )
    mastery_change_sample_count = sum(
        bool(
            record.get("evaluation")
            and (
                record["evaluation"].get("prior_mastery") is not None
                or record["evaluation"].get("mastery") is not None
                or record["evaluation"].get("mastery_score") is not None
            )
        )
        for record in practices
    )
    relation_count = 0
    if analyzed_kp_ids:
        relation_count = len(
            (
                await db.execute(
                    select(KnowledgeRelation).where(
                        KnowledgeRelation.relation_type == "prerequisite",
                        KnowledgeRelation.from_point_id.in_(analyzed_kp_ids),
                        KnowledgeRelation.to_point_id.in_(analyzed_kp_ids),
                    )
                )
            ).scalars().all()
        )

    def evidence_status(sample_size: int, sufficient: int = 10) -> str:
        return (
            "ready"
            if sample_size >= sufficient
            else "limited"
            if sample_size > 0
            else "unavailable"
        )

    estimation_evidence = [
        {
            "key": "direct_gain",
            "name": "直接提分价值",
            "symbol": "D",
            "unit": "分",
            "current_mean": _mean(row["direct_gain"] for row in rows),
            "status": evidence_status(history_answer_count),
            "sample_size": history_answer_count,
            "sample_label": "历史有效作答",
            "estimation_type": "个体历史状态 + 统计模型估计",
            "formula": "D = S × W × G × L × τ",
            "history_inputs": [
                "历史作答形成的当前掌握度与可信度",
                "近期连续答对/答错对可学会概率的修正",
                "学习后正式测评用于迁移率校准",
            ],
            "model_inputs": [
                "目标试卷总分与考试权重",
                "认知层级可学会概率基线",
                "迁移率基线",
            ],
            "snapshot_note": "页面显示的是路径生成时保存的估计结果，不是原始行为字段。",
        },
        {
            "key": "unlock_gain",
            "name": "后继解锁预计收益",
            "symbol": "K",
            "unit": "分",
            "current_mean": _mean(row["unlock_gain"] for row in rows),
            "status": evidence_status(relation_count, sufficient=5),
            "sample_size": relation_count,
            "sample_label": "路径内前置关系",
            "estimation_type": "知识图谱传播估计",
            "formula": "K = Σ（后继知识点直接收益 × 关系强度 × 路径衰减）",
            "history_inputs": [
                "后继知识点由历史状态估计的直接提分价值",
                "历史学习结果可用于校准关系强度",
            ],
            "model_inputs": [
                "知识图谱前后置关系",
                "关系权重与依赖链衰减",
            ],
            "snapshot_note": "页面显示的是沿知识依赖图传播后的预计收益，不是题库中的固定分值。",
        },
        {
            "key": "estimated_minutes",
            "name": "预计学习时间",
            "symbol": "T",
            "unit": "分钟",
            "current_mean": _mean(row["estimated_minutes"] for row in rows),
            "status": evidence_status(duration_sample_count, sufficient=5),
            "sample_size": duration_sample_count,
            "sample_label": "有效学习时长样本",
            "estimation_type": (
                "历史时长样本 + 时间成本模型"
                if duration_sample_count
                else "认知层级时长基线回退"
            ),
            "formula": "T = 认知层级基准时长 × 掌握差距系数 × 不确定性系数",
            "history_inputs": [
                "同类知识点历史实际学习时长",
                "学习前掌握度与学习后掌握度变化",
            ],
            "model_inputs": [
                "认知层级基准时长",
                "掌握度差距",
                "当前评估可信度",
            ],
            "snapshot_note": (
                "已有历史时长样本可用于校准；页面值仍以路径生成时的时间模型快照为准。"
                if duration_sample_count
                else "当前缺少有效起止时间样本，因此路径值采用模型基线估计。"
            ),
        },
    ]

    daily_minutes = planning.get("daily_study_minutes")
    if daily_minutes is not None:
        rows_for_capacity = [
            {"name": "每日容量", "daily_capacity": float(daily_minutes)}
        ]
    else:
        rows_for_capacity = []
    exam_date_text = goal_snapshot.get("exam_date")
    remaining_days: Optional[int] = None
    if exam_date_text:
        try:
            remaining_days = max(
                0,
                (
                    datetime.strptime(str(exam_date_text), "%Y-%m-%d").date()
                    - datetime.utcnow().date()
                ).days,
            )
        except ValueError:
            remaining_days = None
    rows_for_deadline = (
        [{"name": "目标期限", "remaining_days": float(remaining_days)}]
        if remaining_days is not None
        else []
    )

    definitions = [
        ("current_mastery", "当前掌握度", "分"),
        ("confidence", "评估可信度", "%"),
        ("target_mastery", "首轮目标掌握度", "分"),
        ("total_score", "目标试卷总分", "分"),
        ("exam_weight", "考试权重", "%"),
        ("learnability", "可学会概率", "%"),
        ("transfer_rate", "迁移率", "%"),
        ("unlock_gain", "后继解锁预计收益", "分"),
        ("estimated_minutes", "预计学习时间", "分钟"),
        ("unlock_alpha", "解锁收益系数", ""),
        ("effective_mastery", "有效掌握度", "分"),
        ("mastery_gap", "掌握度差距", "分"),
        ("direct_gain", "直接提分价值", "分"),
        ("strategic_value", "战略价值", "分"),
        ("marginal_value", "边际价值", "分/分钟"),
    ]
    metrics = [_metric_curve(key, name, unit, rows) for key, name, unit in definitions]
    metrics.append(
        _metric_curve(
            "daily_capacity", "每日可投入时间", "分钟", rows_for_capacity
        )
    )
    metrics.append(
        _metric_curve("remaining_days", "目标剩余天数", "天", rows_for_deadline)
    )
    def learnability_baseline(level: Any) -> float:
        text = str(level or "")
        return (
            55.0
            if "运用" in text or "应用" in text
            else 65.0
            if "掌握" in text
            else 75.0
            if "理解" in text
            else 85.0
        )

    def time_baseline(level: Any) -> float:
        text = str(level or "")
        return (
            75.0
            if "运用" in text or "应用" in text
            else 55.0
            if "掌握" in text
            else 40.0
            if "理解" in text
            else 25.0
        )

    supporting_statistics = {
        "learnability": {
            "formula": "L = clamp(认知层级基线 + min(连续答对, 2)×4% - min(连续答错, 2)×5%, 35%, 90%)",
            "note": "历史学习任务按学习前掌握度分组；成功率用于检验和后续校准当前规则模型。",
            "success_by_prior_mastery": _success_curve(practices),
            "model_inputs": [
                _point(
                    "认知层级基线",
                    _mean(learnability_baseline(row["cognitive_level"]) for row in rows),
                    len(rows),
                ),
                _point(
                    "连续答对加成",
                    _mean(
                        min(row["recent_correct_streak"], 2) * 4.0
                        for row in rows
                    ),
                    len(rows),
                ),
                _point(
                    "连续答错扣减",
                    _mean(
                        min(row["recent_wrong_streak"], 2) * 5.0
                        for row in rows
                    ),
                    len(rows),
                ),
                _point(
                    "最终可学会概率",
                    _mean(row["learnability"] for row in rows if row["learnability"] is not None),
                    len(rows),
                ),
            ],
        },
        "estimated_minutes": {
            "formula": "T = clamp(认知层级基准时长 × (0.65 + 掌握差距) × [1 + 0.25×(1-可信度)], 20, 120)",
            "note": "仅统计1～180分钟且具有完整起止时间的学习任务；按学习前掌握度分组。",
            "duration_by_prior_mastery": _duration_curve(practices),
            "model_inputs": [
                _point(
                    "认知层级基准时长",
                    _mean(time_baseline(row["cognitive_level"]) for row in rows),
                    len(rows),
                ),
                _point(
                    "掌握度差距",
                    _mean(row["mastery_gap"] for row in rows),
                    len(rows),
                ),
                _point(
                    "最终预计学习时间",
                    _mean(float(row["estimated_minutes"] or 0) for row in rows),
                    len(rows),
                ),
            ],
        },
    }
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "student": {
            "id": student.id,
            "name": student.nickname or student.email or f"学生 {student.id}",
        },
        "knowledge_scope": scope["selection"],
        "path": {
            "id": path.id,
            "version": path.version,
            "status": path.status,
            "algorithm_version": path.algorithm_version,
            "daily_study_minutes": daily_minutes,
            "goal_snapshot": goal_snapshot,
        },
        "summary": {
            "node_count": len(rows),
            "average_marginal_value": _mean(
                row["marginal_value"] for row in rows
            ),
            "total_expected_gain": round(
                sum(row["direct_gain"] for row in rows), 2
            ),
            "total_estimated_minutes": sum(
                int(row["estimated_minutes"] or 0) for row in rows
            ),
            "history_answer_count": history_answer_count,
            "duration_sample_count": duration_sample_count,
            "mastery_change_sample_count": mastery_change_sample_count,
            "knowledge_relation_count": relation_count,
        },
        "metrics": metrics,
        "supporting_statistics": supporting_statistics,
        "estimation_evidence": estimation_evidence,
    }


async def diagnostic_priority_analysis(
    db: AsyncSession,
    user_id: int,
    domain: Optional[str] = None,
    category_1: Optional[str] = None,
    category_2: Optional[str] = None,
    kp_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """分析后续测评候选，不把诊断收益混入学习任务边际价值。"""
    student = (
        await db.execute(
            select(User).where(User.id == user_id, User.role == "student")
        )
    ).scalar_one_or_none()
    if not student:
        return None

    scope = await knowledge_scope(db, domain, category_1, category_2, kp_id)
    selected_kp_ids = scope["kp_ids"] if scope["filtered"] else None
    path = (
        await db.execute(
            select(LearningPath)
            .where(LearningPath.user_id == user_id)
            .order_by(LearningPath.id.desc())
        )
    ).scalars().first()
    if path is None:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "student": {
                "id": student.id,
                "name": student.nickname or student.email or f"学生 {student.id}",
            },
            "knowledge_scope": scope["selection"],
            "path": None,
            "summary": {"candidate_count": 0},
            "metrics": [],
        }

    goal = (
        await db.execute(select(LearningGoal).where(LearningGoal.id == path.goal_id))
    ).scalar_one_or_none()
    if goal is None:
        return None

    map_data = await build_mastery_snapshot(db, user_id, goal.id)
    scope_nodes = [
        node
        for node in map_data.get("nodes", [])
        if node.get("node_type") == "knowledge"
        and node.get("kp_id")
        and node.get("is_in_goal_scope")
    ]
    all_scope_ids = list(dict.fromkeys(str(node["kp_id"]) for node in scope_nodes))
    source_paper_ids = [
        int(item["id"])
        for item in map_data.get("papers", [])
        if item.get("id") is not None
    ]
    weights, weight_sources, _, total_score, warnings = await load_exam_weights(
        db,
        goal,
        all_scope_ids,
        source_paper_ids,
    )
    point_rows = (
        await db.execute(
            select(KnowledgePoint).where(
                KnowledgePoint.id.in_(
                    all_scope_ids if all_scope_ids else {"__empty_scope__"}
                )
            )
        )
    ).scalars().all()
    point_map = {point.id: point for point in point_rows}

    rows: List[Dict[str, Any]] = []
    missing_weight_count = 0
    sufficiently_known_count = 0
    for node in scope_nodes:
        kp_id_value = str(node["kp_id"])
        if selected_kp_ids is not None and kp_id_value not in selected_kp_ids:
            continue
        weight = float(weights.get(kp_id_value, 0.0))
        if weight <= 0:
            missing_weight_count += 1
            continue
        confidence = float(node.get("confidence") or 0.0)
        metrics = calculate_diagnostic_priority(
            total_score=total_score,
            exam_weight=weight,
            confidence=confidence,
        )
        if int(metrics["recommended_question_count"]) <= 0:
            sufficiently_known_count += 1
            continue
        point = point_map.get(kp_id_value)
        rows.append(
            {
                "kp_id": kp_id_value,
                "name": (
                    (point.short_name or point.name)
                    if point is not None
                    else kp_id_value
                ),
                "total_score": metrics["total_score"],
                "confidence": metrics["confidence"] * 100,
                "target_confidence": metrics["target_confidence"] * 100,
                "effective_evidence": metrics["effective_evidence"],
                "target_evidence": metrics["target_evidence"],
                "exam_weight": metrics["exam_weight"] * 100,
                "minutes_per_question": metrics["minutes_per_question"],
                "uncertainty": metrics["uncertainty"] * 100,
                "score_exposure": metrics["score_exposure"],
                "recommended_question_count": metrics[
                    "recommended_question_count"
                ],
                "diagnostic_estimated_minutes": metrics[
                    "diagnostic_estimated_minutes"
                ],
                "diagnostic_information_value": metrics[
                    "diagnostic_information_value"
                ],
                "diagnostic_priority": metrics["diagnostic_priority"],
                "weight_source": weight_sources.get(kp_id_value, "none"),
            }
        )

    rows.sort(
        key=lambda row: (
            -float(row["diagnostic_priority"]),
            -float(row["diagnostic_information_value"]),
            str(row["kp_id"]),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["diagnostic_rank"] = index

    definitions = [
        ("total_score", "目标试卷总分", "分"),
        ("confidence", "评估可信度", "%"),
        ("target_confidence", "目标可信度", "%"),
        ("effective_evidence", "诊断标准证据量", "份"),
        ("target_evidence", "目标标准证据量", "份"),
        ("exam_weight", "考试权重", "%"),
        ("minutes_per_question", "单题标准时间", "分钟/题"),
        ("uncertainty", "诊断不确定度", "%"),
        ("score_exposure", "考试分值影响范围", "分"),
        ("recommended_question_count", "建议测评题数", "题"),
        ("diagnostic_estimated_minutes", "预计测评时间", "分钟"),
        ("diagnostic_information_value", "诊断信息价值", "分"),
        ("diagnostic_priority", "诊断任务优先级", "分/分钟"),
        ("diagnostic_rank", "建议测评顺序", "位"),
    ]
    metrics = [_metric_curve(key, name, unit, rows) for key, name, unit in definitions]
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "student": {
            "id": student.id,
            "name": student.nickname or student.email or f"学生 {student.id}",
        },
        "knowledge_scope": scope["selection"],
        "path": {
            "id": path.id,
            "version": path.version,
            "status": path.status,
            "algorithm_version": path.algorithm_version,
            "goal_id": path.goal_id,
        },
        "summary": {
            "candidate_count": len(rows),
            "total_recommended_questions": sum(
                int(row["recommended_question_count"]) for row in rows
            ),
            "total_estimated_minutes": sum(
                int(row["diagnostic_estimated_minutes"]) for row in rows
            ),
            "highest_priority_kp": rows[0]["name"] if rows else None,
            "missing_weight_count": missing_weight_count,
            "sufficient_confidence_count": sufficiently_known_count,
            "warnings": warnings,
        },
        "metrics": metrics,
    }


async def targeted_practice_analysis(
    db: AsyncSession,
    user_id: int,
    domain: Optional[str] = None,
    category_1: Optional[str] = None,
    category_2: Optional[str] = None,
    kp_id: Optional[str] = None,
    question_count: int = 20,
) -> Optional[Dict[str, Any]]:
    """按真实选题口径追踪针对性刷题的数据链路与当前指标。"""
    student = (
        await db.execute(
            select(User).where(User.id == user_id, User.role == "student")
        )
    ).scalar_one_or_none()
    if not student:
        return None

    scope = await knowledge_scope(db, domain, category_1, category_2, kp_id)
    selected_kp_ids = scope["kp_ids"] if scope["filtered"] else None
    path = (
        await db.execute(
            select(LearningPath)
            .where(LearningPath.user_id == user_id)
            .order_by(LearningPath.id.desc())
        )
    ).scalars().first()
    if path is None:
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "student": {
                "id": student.id,
                "name": student.nickname or student.email or f"学生 {student.id}",
            },
            "knowledge_scope": scope["selection"],
            "path": None,
            "summary": {"knowledge_point_count": 0},
            "metrics": [],
            "type_distribution": [],
            "difficulty_distribution": [],
            "bank_distribution": [],
        }

    goal = (
        await db.execute(select(LearningGoal).where(LearningGoal.id == path.goal_id))
    ).scalar_one_or_none()
    if goal is None:
        return None

    node_query = (
        select(LearningPathNode, KnowledgePoint)
        .join(KnowledgePoint, LearningPathNode.kp_id == KnowledgePoint.id)
        .where(LearningPathNode.path_id == path.id)
        .order_by(LearningPathNode.order_index.asc())
    )
    if selected_kp_ids is not None:
        node_query = node_query.where(
            LearningPathNode.kp_id.in_(
                selected_kp_ids if selected_kp_ids else {"__empty_scope__"}
            )
        )
    node_rows = (await db.execute(node_query)).all()
    kp_ids = [str(node.kp_id) for node, _point_item in node_rows]
    kp_id_set = set(kp_ids)

    template = None
    template_warning = None
    try:
        template = await assembly.resolve_template(
            db,
            subject=goal.subject,
            region=goal.region,
            exam_type=goal.exam_type,
        )
    except Exception as exc:
        template_warning = f"平均模板不可用：{exc}"

    template_weights_by_kp: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {key: 0.0 for key in targeted_question_selector.TYPE_KEYS}
    )
    if template is not None and kp_ids:
        stats = (
            await db.execute(
                select(ExamKpScoreStat).where(
                    ExamKpScoreStat.template_id == template.id,
                    ExamKpScoreStat.kp_id.in_(kp_ids),
                    ExamKpScoreStat.question_type.is_not(None),
                )
            )
        ).scalars().all()
        for stat in stats:
            type_key = targeted_question_selector._type_key(stat.question_type)
            if type_key:
                template_weights_by_kp[str(stat.kp_id)][type_key] += max(
                    0.0, float(stat.question_count or 0)
                )

    overall_template_weights = {
        key: 0.0 for key in targeted_question_selector.TYPE_KEYS
    }
    if template is not None:
        for item in assembly.parse_type_structure(template.type_structure):
            type_key = targeted_question_selector._type_key(item["question_type"])
            if type_key:
                overall_template_weights[type_key] += max(
                    0.0, float(item["count"] or 0)
                )

    questions_by_kp: Dict[str, List[Question]] = defaultdict(list)
    if kp_ids:
        question_rows = (
            await db.execute(
                select(Question).where(
                    Question.primary_kp_id.in_(kp_ids),
                    Question.bank_type.in_(("real", "mock", "ai")),
                )
            )
        ).scalars().all()
        for question in question_rows:
            questions_by_kp[str(question.primary_kp_id)].append(question)

    events_by_kp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    answered_ids_by_kp: Dict[str, set[int]] = defaultdict(set)
    if kp_ids:
        formal_rows = (
            await db.execute(
                select(TestAnswer, TestQuestion, TestPaper)
                .join(TestQuestion, TestQuestion.id == TestAnswer.test_question_id)
                .join(TestPaper, TestPaper.id == TestAnswer.test_paper_id)
                .where(
                    TestPaper.user_id == user_id,
                    TestPaper.status == "graded",
                    TestAnswer.is_correct.is_not(None),
                    TestQuestion.primary_kp_id.in_(kp_ids),
                )
            )
        ).all()
        for answer, question, paper in formal_rows:
            event_kp_id = str(question.primary_kp_id)
            if question.source_question_id:
                answered_ids_by_kp[event_kp_id].add(int(question.source_question_id))
            events_by_kp[event_kp_id].append(
                {
                    "difficulty": question.difficulty or 3,
                    "correct": bool(answer.is_correct),
                    "created_at": (
                        answer.updated_at or answer.created_at or paper.updated_at
                    ),
                }
            )

    tasks = (
        await db.execute(
            select(LearningTask).where(
                LearningTask.user_id == user_id,
                LearningTask.task_type.in_(["practice", "training", "checkpoint"]),
                LearningTask.result_json.is_not(None),
            )
        )
    ).scalars().all()
    practice_entries: List[Tuple[Dict[str, Any], Any]] = []
    practice_question_ids: set[int] = set()
    for task in tasks:
        history = _json(task.result_json).get("answer_history") or []
        if not isinstance(history, list):
            continue
        for entry in history:
            question_id_value = entry.get("question_id")
            if not str(question_id_value or "").isdigit():
                continue
            question_id_int = int(question_id_value)
            practice_question_ids.add(question_id_int)
            practice_entries.append((entry, task.created_at))

    practice_question_map: Dict[int, Question] = {}
    if practice_question_ids:
        practice_questions = (
            await db.execute(
                select(Question).where(Question.id.in_(practice_question_ids))
            )
        ).scalars().all()
        practice_question_map = {
            question.id: question for question in practice_questions
        }
    for entry, created_at in practice_entries:
        question = practice_question_map.get(int(entry["question_id"]))
        if not question or str(question.primary_kp_id) not in kp_id_set:
            continue
        event_kp_id = str(question.primary_kp_id)
        answered_ids_by_kp[event_kp_id].add(question.id)
        events_by_kp[event_kp_id].append(
            {
                "difficulty": entry.get("difficulty") or question.difficulty or 3,
                "correct": bool(entry.get("is_correct")),
                "created_at": created_at,
            }
        )

    rows: List[Dict[str, Any]] = []
    selected_questions_by_kp: Dict[str, List[Question]] = {}
    planned_difficulty_counts: Counter[int] = Counter()
    selected_difficulty_counts: Counter[int] = Counter()
    observed_by_difficulty: Dict[int, List[bool]] = defaultdict(list)
    predicted_by_difficulty: Dict[int, List[float]] = defaultdict(list)
    warnings: List[str] = []
    if template_warning:
        warnings.append(template_warning)

    for node, point_item in node_rows:
        node_kp_id = str(node.kp_id)
        kp_template_weights = dict(template_weights_by_kp[node_kp_id])
        template_source = "kp_average_template"
        if sum(kp_template_weights.values()) <= 0:
            kp_template_weights = dict(overall_template_weights)
            template_source = (
                "template_overall"
                if sum(kp_template_weights.values()) > 0
                else "template_unavailable"
            )
        all_questions = questions_by_kp[node_kp_id]
        candidates = [
            question
            for question in all_questions
            if question.bank_type in targeted_question_selector.ALLOWED_BANK_TYPES
        ]
        events = events_by_kp[node_kp_id]
        selected_questions, diagnostics = (
            targeted_question_selector.build_selection_plan(
                candidates=candidates,
                template_weights=kp_template_weights,
                template_id=template.id if template is not None else None,
                template_source=template_source,
                events=events,
                answered_ids=answered_ids_by_kp[node_kp_id],
                current_mastery=node.current_mastery,
                question_count=question_count,
            )
        )
        selected_questions_by_kp[node_kp_id] = selected_questions
        type_total = sum(kp_template_weights.values())
        correct_count = sum(bool(event["correct"]) for event in events)
        selected_type_counts = Counter(
            targeted_question_selector._type_key(question.question_type)
            for question in selected_questions
        )
        selected_bank_counts = Counter(
            question.bank_type for question in selected_questions
        )
        repeated_count = sum(
            question.id in answered_ids_by_kp[node_kp_id]
            for question in selected_questions
        )
        difficulty = diagnostics["difficulty"]
        target_difficulty = int(difficulty["target_difficulty"])
        for level, count_value in diagnostics["difficulty_quotas"].items():
            planned_difficulty_counts[int(level)] += int(count_value)
        for question in selected_questions:
            selected_difficulty_counts[
                max(1, min(5, int(question.difficulty or 3)))
            ] += 1
        for event in events:
            event_level = max(1, min(5, int(event.get("difficulty") or 3)))
            observed_by_difficulty[event_level].append(bool(event["correct"]))
        for level, prediction in difficulty["predictions"].items():
            predicted_by_difficulty[int(level)].append(
                float(prediction["predicted_success"]) * 100
            )

        row = {
            "kp_id": node_kp_id,
            "name": point_item.short_name or point_item.name,
            "template_question_count": type_total,
            "choice_ratio": (
                kp_template_weights.get("choice", 0.0) / type_total * 100
                if type_total
                else None
            ),
            "fill_ratio": (
                kp_template_weights.get("fill", 0.0) / type_total * 100
                if type_total
                else None
            ),
            "short_answer_ratio": (
                kp_template_weights.get("short_answer", 0.0) / type_total * 100
                if type_total
                else None
            ),
            "planned_choice_count": diagnostics["type_quotas"].get("choice", 0),
            "planned_fill_count": diagnostics["type_quotas"].get("fill", 0),
            "planned_short_answer_count": diagnostics["type_quotas"].get(
                "short_answer", 0
            ),
            "history_answer_count": len(events),
            "observed_accuracy": (
                correct_count / len(events) * 100 if events else None
            ),
            "ability_estimate": float(difficulty["ability"]),
            "target_success_rate": float(difficulty["target_success_rate"]) * 100,
            "predicted_target_success": float(
                difficulty["predictions"][target_difficulty]["predicted_success"]
            )
            * 100,
            "target_difficulty": target_difficulty,
            "mock_candidate_count": diagnostics["mock_candidate_count"],
            "ai_candidate_count": diagnostics["ai_candidate_count"],
            "real_excluded_count": sum(
                question.bank_type == "real" for question in all_questions
            ),
            "selected_choice_count": selected_type_counts["choice"],
            "selected_fill_count": selected_type_counts["fill"],
            "selected_short_answer_count": selected_type_counts["short_answer"],
            "selected_mock_count": selected_bank_counts["mock"],
            "selected_ai_count": selected_bank_counts["ai"],
            "selected_question_count": len(selected_questions),
            "unique_selected_count": len(
                {question.id for question in selected_questions}
            ),
            "repeated_selected_count": repeated_count,
            "template_source": diagnostics["template_source"],
        }
        rows.append(row)
        if len(selected_questions) < question_count:
            warnings.append(
                f"{row['name']}仅有{len(selected_questions)}道可用模拟题或AI题"
            )

    metric_definitions = [
        ("template_question_count", "当前知识点模板题量", "题"),
        ("choice_ratio", "选择题比例", "%"),
        ("fill_ratio", "填空题比例", "%"),
        ("short_answer_ratio", "简答题比例", "%"),
        ("planned_choice_count", "本轮选择题配额", "题"),
        ("planned_fill_count", "本轮填空题配额", "题"),
        ("planned_short_answer_count", "本轮简答题配额", "题"),
        ("history_answer_count", "历史作答题量", "题"),
        ("observed_accuracy", "历史实际正确率", "%"),
        ("ability_estimate", "用户能力估计", "级"),
        ("target_success_rate", "目标答对概率", "%"),
        ("predicted_target_success", "目标难度预测答对概率", "%"),
        ("target_difficulty", "最近发展区难度", "级"),
        ("mock_candidate_count", "模拟题候选数", "题"),
        ("ai_candidate_count", "AI题候选数", "题"),
        ("real_excluded_count", "排除的真题数", "题"),
        ("selected_mock_count", "入选模拟题数", "题"),
        ("selected_ai_count", "入选AI题数", "题"),
        ("selected_question_count", "本轮练习题数", "题"),
        ("unique_selected_count", "去重后题数", "题"),
        ("repeated_selected_count", "历史已做题数", "题"),
    ]
    metrics = [
        _metric_curve(key, name, unit, rows)
        for key, name, unit in metric_definitions
    ]

    type_labels = {
        "choice": "选择题",
        "fill": "填空题",
        "short_answer": "简答题",
    }
    type_distribution = []
    for type_key in targeted_question_selector.TYPE_KEYS:
        ratio_key = f"{type_key}_ratio"
        type_distribution.append(
            {
                "key": type_key,
                "label": type_labels[type_key],
                "template_question_count": round(
                    sum(
                        float(row["template_question_count"] or 0)
                        * float(row.get(ratio_key) or 0)
                        / 100
                        for row in rows
                    )
                    / max(len(rows), 1),
                    2,
                ),
                "template_weight": round(
                    sum(
                        row.get(ratio_key) or 0
                        for row in rows
                    )
                    / max(len(rows), 1),
                    2,
                ),
                "planned_count": sum(
                    int(row.get(f"planned_{type_key}_count") or 0)
                    for row in rows
                ),
                "selected_count": sum(
                    int(row.get(f"selected_{type_key}_count") or 0)
                    for row in rows
                ),
            }
        )

    difficulty_distribution = [
        {
            "difficulty": level,
            "observed_accuracy": (
                round(
                    sum(observed_by_difficulty[level])
                    / len(observed_by_difficulty[level])
                    * 100,
                    2,
                )
                if observed_by_difficulty[level]
                else None
            ),
            "observed_sample_size": len(observed_by_difficulty[level]),
            "predicted_success": _mean(predicted_by_difficulty[level]),
            "planned_count": planned_difficulty_counts[level],
            "selected_count": selected_difficulty_counts[level],
        }
        for level in range(1, 6)
    ]
    bank_distribution = [
        {
            "key": "mock",
            "label": "模拟题",
            "candidate_count": sum(row["mock_candidate_count"] for row in rows),
            "selected_count": sum(row["selected_mock_count"] for row in rows),
        },
        {
            "key": "ai",
            "label": "AI题",
            "candidate_count": sum(row["ai_candidate_count"] for row in rows),
            "selected_count": sum(row["selected_ai_count"] for row in rows),
        },
        {
            "key": "real",
            "label": "真题（已排除）",
            "candidate_count": sum(row["real_excluded_count"] for row in rows),
            "selected_count": 0,
        },
    ]
    unique_warnings = list(dict.fromkeys(warnings))
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "student": {
            "id": student.id,
            "name": student.nickname or student.email or f"学生 {student.id}",
        },
        "knowledge_scope": scope["selection"],
        "path": {
            "id": path.id,
            "version": path.version,
            "status": path.status,
            "algorithm_version": targeted_question_selector.ALGORITHM_VERSION,
            "goal_id": path.goal_id,
        },
        "summary": {
            "knowledge_point_count": len(rows),
            "question_count_per_kp": question_count,
            "planned_question_count": len(rows) * question_count,
            "selected_question_count": sum(
                row["selected_question_count"] for row in rows
            ),
            "mock_selected_count": sum(row["selected_mock_count"] for row in rows),
            "ai_selected_count": sum(row["selected_ai_count"] for row in rows),
            "real_selected_count": 0,
            "history_answer_count": sum(row["history_answer_count"] for row in rows),
            "template_covered_count": sum(
                row["template_source"] == "kp_average_template" for row in rows
            ),
            "average_template_question_count": _mean(
                row["template_question_count"] for row in rows
            ),
            "average_observed_accuracy": _mean(
                row["observed_accuracy"]
                for row in rows
                if row["observed_accuracy"] is not None
            ),
            "average_ability_estimate": _mean(
                row["ability_estimate"] for row in rows
            ),
            "average_predicted_target_success": _mean(
                row["predicted_target_success"] for row in rows
            ),
            "average_target_difficulty": _mean(
                row["target_difficulty"] for row in rows
            ),
            "unique_selected_count": sum(
                row["unique_selected_count"] for row in rows
            ),
            "repeated_selected_count": sum(
                row["repeated_selected_count"] for row in rows
            ),
            "warnings": unique_warnings[:20],
        },
        "metrics": metrics,
        "type_distribution": type_distribution,
        "difficulty_distribution": difficulty_distribution,
        "bank_distribution": bank_distribution,
    }
