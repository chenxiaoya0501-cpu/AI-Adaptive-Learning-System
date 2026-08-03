"""聚合学生在测评与课程练习中的错误作答。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.student.learning_path import LearningPath, LearningTask
from app.models.student.test_paper import (
    TestAnswer,
    TestPaper,
    TestQuestion,
    WrongQuestionAiExercise,
)
from app.schemas.student.test import WrongQuestionItem, WrongQuestionList
from app.services.learning import assembly


def _answer_text(selected_option: Any, answer_text: Any) -> str | None:
    selected = str(selected_option or "").strip()
    text = str(answer_text or "").strip()
    return selected or text or None


def _practice_wrong_rows(
    task: LearningTask, question_map: Dict[int, Question]
) -> List[WrongQuestionItem]:
    result = task.result_json or {}
    history = result.get("answer_history") or []
    rows: List[WrongQuestionItem] = []
    for entry in history:
        if entry.get("is_correct") is not False:
            continue
        try:
            question_id = int(entry.get("question_id"))
        except (TypeError, ValueError):
            continue
        question = question_map.get(question_id)
        if question is None:
            continue
        rows.append(
            WrongQuestionItem(
                id=f"practice-{task.id}-{question_id}",
                source_type="practice",
                question_id=question_id,
                path_id=task.path_id,
                kp_id=question.primary_kp_id,
                question_type=question.question_type,
                content=question.content,
                options=question.options,
                user_answer=_answer_text(
                    entry.get("selected_option"), entry.get("answer_text")
                ),
                correct_answer=entry.get("correct_answer") or question.answer,
                analysis=entry.get("analysis") or question.analysis,
                source_exam_paper_id=question.exam_paper_id,
                difficulty=entry.get("difficulty") or question.difficulty,
                created_at=task.completed_at or task.created_at,
            )
        )
    return rows


async def list_wrong_questions(
    db: AsyncSession, user_id: int
) -> WrongQuestionList:
    assessment_rows = (
        await db.execute(
            select(TestAnswer, TestQuestion, TestPaper)
            .join(TestQuestion, TestQuestion.id == TestAnswer.test_question_id)
            .join(TestPaper, TestPaper.id == TestAnswer.test_paper_id)
            .where(TestPaper.user_id == user_id, TestAnswer.is_correct.is_(False))
        )
    ).all()
    items: List[WrongQuestionItem] = []
    source_paper_ids = await assembly.resolve_source_exam_paper_ids(
        db, [row[1] for row in assessment_rows]
    )
    for answer, question, paper in assessment_rows:
        source_paper_id = (
            question.source_exam_paper_id
            or source_paper_ids.get(question.id)
        )
        items.append(
            WrongQuestionItem(
                id=f"assessment-{answer.id}",
                source_type="assessment",
                question_id=question.id,
                paper_id=paper.id,
                paper_title=paper.title,
                seq=question.seq,
                question_type=question.question_type,
                content=assembly.expand_img_placeholders(
                    question.content, source_paper_id
                ),
                options=assembly.expand_options_images(
                    question.options, source_paper_id
                ),
                user_answer=_answer_text(
                    answer.selected_option, answer.answer_text
                ),
                correct_answer=(
                    assembly.expand_img_placeholders(question.answer, source_paper_id)
                    if question.answer
                    else None
                ),
                analysis=(
                    assembly.expand_img_placeholders(question.analysis, source_paper_id)
                    if question.analysis
                    else None
                ),
                source_exam_paper_id=source_paper_id,
                difficulty=question.difficulty,
                created_at=answer.updated_at or answer.created_at or paper.created_at,
            )
        )

    tasks = (
        await db.execute(
            select(LearningTask)
            .join(LearningPath, LearningPath.id == LearningTask.path_id)
            .where(
                LearningTask.user_id == user_id,
                LearningPath.user_id == user_id,
                LearningTask.task_type.in_(["practice", "training", "checkpoint"]),
                LearningTask.result_json.is_not(None),
            )
        )
    ).scalars().all()
    question_ids = {
        int(entry["question_id"])
        for task in tasks
        for entry in ((task.result_json or {}).get("answer_history") or [])
        if entry.get("question_id") is not None
        and str(entry.get("question_id")).isdigit()
        and entry.get("is_correct") is False
    }
    question_map: Dict[int, Question] = {}
    if question_ids:
        questions = (
            await db.execute(select(Question).where(Question.id.in_(question_ids)))
        ).scalars().all()
        question_map = {question.id: question for question in questions}
    practice_items = [
        item
        for task in tasks
        for item in _practice_wrong_rows(task, question_map)
    ]
    items.extend(practice_items)

    exercises = (
        await db.execute(
            select(WrongQuestionAiExercise)
            .where(WrongQuestionAiExercise.user_id == user_id)
            .order_by(WrongQuestionAiExercise.created_at.desc())
        )
    ).scalars().all()
    exercises_by_source: Dict[tuple, List[Dict[str, Any]]] = {}
    for exercise in exercises:
        public = {
            "id": exercise.id,
            "mode": exercise.mode,
            "question_type": exercise.question_type,
            "content": exercise.content,
            "options": exercise.options,
            "difficulty": exercise.difficulty,
            "user_answer": exercise.user_answer,
            "is_correct": exercise.is_correct,
            "created_at": exercise.created_at,
        }
        # 只有提交过答案的练习才返回标准答案与解析。
        if exercise.is_correct is not None:
            public["correct_answer"] = exercise.answer
            public["analysis"] = exercise.analysis
        key = (exercise.source_type, exercise.source_question_id)
        exercises_by_source.setdefault(key, []).append(public)
    for item in items:
        item.generated_exercises = exercises_by_source.get(
            (item.source_type, item.question_id), []
        )

    items.sort(
        key=lambda item: item.created_at or datetime.min,
        reverse=True,
    )
    return WrongQuestionList(
        total=len(items),
        assessment_count=len(items) - len(practice_items),
        practice_count=len(practice_items),
        items=items,
    )
