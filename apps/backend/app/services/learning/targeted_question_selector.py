"""课程针对性刷题选题：平均模板定题型，历史表现定难度。"""
from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import ExamKpScoreStat, Question
from app.models.student.goal import LearningGoal
from app.models.student.learning_path import LearningTask
from app.models.student.test_paper import TestAnswer, TestPaper, TestQuestion
from app.services.learning import assembly

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "targeted-selector-v1.0"
TYPE_KEYS = ("choice", "fill", "short_answer")
TYPE_LABELS = {
    "choice": "选择题",
    "fill": "填空题",
    "short_answer": "简答题",
}
ALLOWED_BANK_TYPES = ("mock", "ai")
TARGET_SUCCESS_RATE = 0.62


def _type_key(question_type: Optional[str]) -> Optional[str]:
    if question_type == "choice":
        return "choice"
    if question_type == "fill":
        return "fill"
    if question_type in {"answer", "proof"}:
        return "short_answer"
    return None


def _largest_remainder(weights: Dict[Any, float], count: int) -> Dict[Any, int]:
    if not weights:
        return {}
    positive = {key: max(0.0, float(value)) for key, value in weights.items()}
    total = sum(positive.values())
    if total <= 0:
        positive = {key: 1.0 for key in positive}
        total = float(len(positive))
    raw = {key: count * value / total for key, value in positive.items()}
    quotas = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = count - sum(quotas.values())
    order = sorted(
        raw,
        key=lambda key: (raw[key] - quotas[key], positive[key], str(key)),
        reverse=True,
    )
    for key in order[:remainder]:
        quotas[key] += 1
    return quotas


def _difficulty_distribution(target: int, count: int) -> Dict[int, int]:
    weights: Dict[int, float] = defaultdict(float)
    weights[max(1, target - 1)] += 0.20
    weights[target] += 0.60
    weights[min(5, target + 1)] += 0.20
    return _largest_remainder(dict(weights), count)


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _recent_streak(events: Sequence[Dict[str, Any]]) -> int:
    ordered = sorted(
        events,
        key=lambda item: item.get("created_at") or datetime.min,
        reverse=True,
    )
    streak = 0
    for event in ordered:
        correct = bool(event["correct"])
        if streak == 0:
            streak = 1 if correct else -1
        elif (streak > 0) == correct:
            streak += 1 if correct else -1
        else:
            break
        if streak >= 3 or streak <= -2:
            break
    return streak


def _estimate_difficulty(
    events: Sequence[Dict[str, Any]], current_mastery: Optional[float]
) -> Dict[str, Any]:
    mastery = 50.0 if current_mastery is None else max(0.0, min(100.0, current_mastery))
    theta = 1.0 + 4.0 * mastery / 100.0
    ordered = sorted(events, key=lambda item: item.get("created_at") or datetime.min)
    buckets: Dict[int, List[bool]] = defaultdict(list)
    for event in ordered:
        difficulty = max(1, min(5, int(event.get("difficulty") or 3)))
        correct = bool(event["correct"])
        predicted = _sigmoid(1.7 * (theta - difficulty))
        theta = max(1.0, min(5.0, theta + 0.22 * ((1.0 if correct else 0.0) - predicted)))
        buckets[difficulty].append(correct)

    streak = _recent_streak(events)
    target_rate = 0.70 if streak <= -2 else 0.55 if streak >= 3 else TARGET_SUCCESS_RATE
    predictions: Dict[int, Dict[str, Any]] = {}
    for difficulty in range(1, 6):
        values = buckets[difficulty]
        attempted = len(values)
        correct = sum(values)
        empirical = (correct + 2.0) / (attempted + 4.0)
        elo_probability = _sigmoid(1.7 * (theta - difficulty))
        evidence_weight = attempted / (attempted + 5.0)
        probability = evidence_weight * empirical + (1.0 - evidence_weight) * elo_probability
        predictions[difficulty] = {
            "attempted": attempted,
            "correct": correct,
            "empirical_accuracy": round(empirical, 4),
            "predicted_success": round(probability, 4),
        }
    target = min(
        predictions,
        key=lambda difficulty: (
            abs(predictions[difficulty]["predicted_success"] - target_rate),
            abs(difficulty - theta),
        ),
    )
    return {
        "ability": round(theta, 4),
        "recent_streak": streak,
        "target_success_rate": target_rate,
        "target_difficulty": target,
        "predictions": predictions,
    }


async def _template_type_weights(
    db: AsyncSession,
    goal: LearningGoal,
    kp_id: str,
) -> Tuple[Dict[str, float], Optional[int], str]:
    try:
        template = await assembly.resolve_template(
            db,
            subject=goal.subject,
            region=goal.region,
            exam_type=goal.exam_type,
        )
    except Exception as exc:
        logger.warning("针对性刷题无法解析平均模板 goal=%s: %s", goal.id, exc)
        return {}, None, "template_unavailable"

    stats = (
        await db.execute(
            select(ExamKpScoreStat).where(
                ExamKpScoreStat.template_id == template.id,
                ExamKpScoreStat.kp_id == kp_id,
                ExamKpScoreStat.question_type.is_not(None),
            )
        )
    ).scalars().all()
    counts = {key: 0.0 for key in TYPE_KEYS}
    for stat in stats:
        key = _type_key(stat.question_type)
        if key:
            counts[key] += max(0.0, float(stat.question_count or 0))
    if sum(counts.values()) > 0:
        return counts, template.id, "kp_average_template"

    # 当前知识点在模板中无可用题数时，退回平均模板整卷题型结构。
    for item in assembly.parse_type_structure(template.type_structure):
        key = _type_key(item["question_type"])
        if key:
            counts[key] += max(0.0, float(item["count"] or 0))
    return counts, template.id, "template_overall"


async def _history_events(
    db: AsyncSession, user_id: int, kp_id: str
) -> Tuple[List[Dict[str, Any]], set[int]]:
    events: List[Dict[str, Any]] = []
    answered_ids: set[int] = set()
    formal = (
        await db.execute(
            select(TestAnswer, TestQuestion, TestPaper)
            .join(TestQuestion, TestQuestion.id == TestAnswer.test_question_id)
            .join(TestPaper, TestPaper.id == TestAnswer.test_paper_id)
            .where(
                TestPaper.user_id == user_id,
                TestPaper.status == "graded",
                TestAnswer.is_correct.is_not(None),
                TestQuestion.primary_kp_id == kp_id,
            )
        )
    ).all()
    for answer, question, paper in formal:
        if question.source_question_id:
            answered_ids.add(int(question.source_question_id))
        events.append(
            {
                "difficulty": question.difficulty or 3,
                "correct": bool(answer.is_correct),
                "created_at": answer.updated_at or answer.created_at or paper.updated_at,
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
    entries = [
        (entry, task.created_at)
        for task in tasks
        for entry in ((task.result_json or {}).get("answer_history") or [])
        if str(entry.get("question_id") or "").isdigit()
    ]
    question_ids = {int(entry["question_id"]) for entry, _created_at in entries}
    question_map: Dict[int, Question] = {}
    if question_ids:
        questions = (
            await db.execute(select(Question).where(Question.id.in_(question_ids)))
        ).scalars().all()
        question_map = {question.id: question for question in questions}
    for entry, created_at in entries:
        question = question_map.get(int(entry["question_id"]))
        if not question or question.primary_kp_id != kp_id:
            continue
        answered_ids.add(question.id)
        events.append(
            {
                "difficulty": entry.get("difficulty") or question.difficulty or 3,
                "correct": bool(entry.get("is_correct")),
                "created_at": created_at,
            }
        )
    return events, answered_ids


def _build_slots(quotas: Dict[Any, int]) -> List[Any]:
    remaining = dict(quotas)
    slots: List[Any] = []
    while any(value > 0 for value in remaining.values()):
        for key in sorted(remaining, key=str):
            if remaining[key] > 0:
                slots.append(key)
                remaining[key] -= 1
    return slots


def _select_candidates(
    candidates: List[Question],
    answered_ids: set[int],
    type_quotas: Dict[str, int],
    difficulty_quotas: Dict[int, int],
    count: int,
) -> List[Question]:
    type_slots = _build_slots(type_quotas)
    difficulty_slots = _build_slots(difficulty_quotas)
    selected: List[Question] = []
    selected_ids: set[int] = set()

    def candidate_key(question: Question, desired_difficulty: int):
        distance = abs(int(question.difficulty or 3) - desired_difficulty)
        # 先保证题目位于目标难度附近，再在可接受区间内优先模拟题。
        # 这样不会为了“模拟题优先”给能力较弱的学生强行安排过难题。
        return (
            0 if distance <= 1 else 1,
            0 if question.bank_type == "mock" else 1,
            distance,
            0 if question.id not in answered_ids else 1,
            question.id,
        )

    for index, type_key in enumerate(type_slots):
        desired_difficulty = difficulty_slots[index % len(difficulty_slots)]
        available = [
            question
            for question in candidates
            if question.id not in selected_ids and _type_key(question.question_type) == type_key
        ]
        if not available:
            continue
        picked = min(available, key=lambda question: candidate_key(question, desired_difficulty))
        selected.append(picked)
        selected_ids.add(picked.id)

    # 某题型库存不足时，从其余模拟/AI候选中按剩余难度槽补足。
    while len(selected) < count:
        available = [question for question in candidates if question.id not in selected_ids]
        if not available:
            break
        desired_difficulty = difficulty_slots[len(selected) % len(difficulty_slots)]
        picked = min(available, key=lambda question: candidate_key(question, desired_difficulty))
        selected.append(picked)
        selected_ids.add(picked.id)
    return selected


def build_selection_plan(
    *,
    candidates: List[Question],
    template_weights: Dict[str, float],
    template_id: Optional[int],
    template_source: str,
    events: Sequence[Dict[str, Any]],
    answered_ids: set[int],
    current_mastery: Optional[float],
    question_count: int,
) -> Tuple[List[Question], Dict[str, Any]]:
    """使用已加载的数据计算一次选题计划，供课程接口和指标分析共用。"""
    pool_counts = Counter(_type_key(question.question_type) for question in candidates)
    planned_type_weights = {
        key: template_weights.get(key, 0.0)
        for key in TYPE_KEYS
        if template_weights.get(key, 0.0) > 0
    }
    if not planned_type_weights or sum(planned_type_weights.values()) <= 0:
        planned_type_weights = {
            key: float(pool_counts[key])
            for key in TYPE_KEYS
            if pool_counts[key] > 0
        }
        template_source = "practice_pool_fallback"
    type_quotas = _largest_remainder(planned_type_weights, question_count)

    difficulty = _estimate_difficulty(events, current_mastery)
    difficulty_quotas = _difficulty_distribution(
        difficulty["target_difficulty"], question_count
    )
    selected = _select_candidates(
        candidates,
        answered_ids,
        type_quotas,
        difficulty_quotas,
        question_count,
    )
    diagnostics = {
        "algorithm_version": ALGORITHM_VERSION,
        "template_id": template_id,
        "template_source": template_source,
        "template_type_weights": template_weights,
        "type_quotas": type_quotas,
        "difficulty": difficulty,
        "difficulty_quotas": difficulty_quotas,
        "history_count": len(events),
        "candidate_count": len(candidates),
        "mock_candidate_count": sum(1 for q in candidates if q.bank_type == "mock"),
        "ai_candidate_count": sum(1 for q in candidates if q.bank_type == "ai"),
        "selected_ids": [question.id for question in selected],
        "selected_bank_types": [question.bank_type for question in selected],
    }
    return selected, diagnostics


async def select_questions(
    db: AsyncSession,
    *,
    user_id: int,
    goal_id: int,
    kp_id: str,
    current_mastery: Optional[float],
    question_count: int,
) -> Tuple[List[Question], Dict[str, Any]]:
    goal = await db.get(LearningGoal, goal_id)
    if not goal or goal.user_id != user_id:
        raise ValueError("学习目标不存在或无权访问")
    candidates = (
        await db.execute(
            select(Question).where(
                Question.primary_kp_id == kp_id,
                Question.bank_type.in_(ALLOWED_BANK_TYPES),
            )
        )
    ).scalars().all()
    template_weights, template_id, template_source = await _template_type_weights(
        db, goal, kp_id
    )

    events, answered_ids = await _history_events(db, user_id, kp_id)
    selected, diagnostics = build_selection_plan(
        candidates=candidates,
        template_weights=template_weights,
        template_id=template_id,
        template_source=template_source,
        events=events,
        answered_ids=answered_ids,
        current_mastery=current_mastery,
        question_count=question_count,
    )
    logger.info(
        "针对性刷题选题 user=%s kp=%s count=%s selected=%s target_difficulty=%s template=%s",
        user_id,
        kp_id,
        question_count,
        len(selected),
        diagnostics["difficulty"]["target_difficulty"],
        template_id,
    )
    return selected, diagnostics
