"""基于学生错题生成并批改 AI 练习。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import Question
from app.models.student.learning_path import LearningTask
from app.models.student.test_paper import (
    TestAnswer,
    TestPaper,
    TestQuestion,
    WrongQuestionAiExercise,
)
from app.schemas.student.test import (
    AiExercisePublic,
    AiExerciseResult,
    WrongQuestionGenerateRequest,
)
from app.services import ai_question_service
from app.services.learning.grading import normalize_choice, normalize_text_answer


async def _owned_wrong_sample(
    db: AsyncSession, user_id: int, source_type: str, question_id: int
) -> Tuple[Dict[str, Any], str | None]:
    if source_type == "assessment":
        row = (
            await db.execute(
                select(TestQuestion, TestAnswer)
                .join(TestPaper, TestPaper.id == TestQuestion.test_paper_id)
                .join(
                    TestAnswer,
                    (TestAnswer.test_paper_id == TestPaper.id)
                    & (TestAnswer.test_question_id == TestQuestion.id),
                )
                .where(
                    TestPaper.user_id == user_id,
                    TestQuestion.id == question_id,
                    TestAnswer.is_correct.is_(False),
                )
            )
        ).first()
        if row:
            question = row[0]
            return {
                "question_type": question.question_type,
                "content": question.content,
                "options": question.options,
                "answer": question.answer,
                "analysis": question.analysis,
                "difficulty": question.difficulty,
            }, question.primary_kp_id
    elif source_type == "practice":
        tasks = (
            await db.execute(
                select(LearningTask).where(
                    LearningTask.user_id == user_id,
                    LearningTask.task_type.in_(["practice", "training", "checkpoint"]),
                )
            )
        ).scalars().all()
        is_wrong = any(
            any(
                int(entry.get("question_id") or 0) == question_id
                and entry.get("is_correct") is False
                for entry in ((task.result_json or {}).get("answer_history") or [])
            )
            for task in tasks
        )
        if is_wrong:
            question = await db.get(Question, question_id)
            if question:
                return {
                    "question_type": question.question_type,
                    "content": question.content,
                    "options": question.options,
                    "answer": question.answer,
                    "analysis": question.analysis,
                    "difficulty": question.difficulty,
                }, question.primary_kp_id
    else:
        raise HTTPException(status_code=422, detail="不支持的错题来源")
    raise HTTPException(status_code=404, detail="错题不存在或无权访问")


async def generate(
    db: AsyncSession, user_id: int, body: WrongQuestionGenerateRequest
) -> AiExercisePublic:
    sample, kp_id = await _owned_wrong_sample(
        db, user_id, body.source_type, body.question_id
    )
    try:
        generated = await ai_question_service.generate_wrong_question_variant(
            db, sample=sample, kp_id=kp_id, mode=body.mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    row = WrongQuestionAiExercise(
        user_id=user_id,
        source_type=body.source_type,
        source_question_id=body.question_id,
        mode=body.mode,
        **generated,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return AiExercisePublic(
        id=row.id,
        mode=row.mode,
        question_type=row.question_type,
        content=row.content,
        options=row.options,
        difficulty=row.difficulty,
    )


async def submit(
    db: AsyncSession, user_id: int, exercise_id: int, answer: str
) -> AiExerciseResult:
    row = (
        await db.execute(
            select(WrongQuestionAiExercise).where(
                WrongQuestionAiExercise.id == exercise_id,
                WrongQuestionAiExercise.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="AI 练习题不存在")
    user_answer = answer.strip()
    if row.question_type == "choice":
        is_correct = normalize_choice(user_answer) == normalize_choice(row.answer)
    else:
        expected = normalize_text_answer(row.answer)
        actual = normalize_text_answer(user_answer)
        alternatives = [
            normalize_text_answer(item)
            for item in str(row.answer).replace("；", ";").split(";")
        ]
        if row.question_type == "fill":
            is_correct = bool(actual and (actual == expected or actual in alternatives))
        else:
            is_correct = bool(actual and expected and (actual == expected or expected in actual))
    row.user_answer = user_answer
    row.is_correct = is_correct
    row.answered_at = datetime.utcnow()
    await db.commit()
    return AiExerciseResult(
        id=row.id,
        mode=row.mode,
        question_type=row.question_type,
        content=row.content,
        options=row.options,
        difficulty=row.difficulty,
        user_answer=user_answer,
        is_correct=is_correct,
        correct_answer=row.answer,
        analysis=row.analysis,
    )
