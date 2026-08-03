"""按学习路径节点动态组装讲解与练习课程。"""
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint
from app.models.question import Question
from app.models.resource import KpExplanation, KpVideoResource
from app.models.student.goal import LearningGoal
from app.models.student.learning_path import LearningPath, LearningPathNode, LearningTask
from app.models.student.mastery_sync import CourseMasterySync
from app.schemas.student.course import CourseCompleteRequest
from app.services.learning.mastery_evaluator import evaluate_mastery
from app.services.learning import targeted_question_selector
from app.services.explanation_blocks import normalize_content_blocks


def _json_list(value: Optional[str]) -> List[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _normalize_answer(value: Optional[str]) -> str:
    text = re.sub(r"\s+", "", str(value or "")).upper()
    return text.replace("，", ",").replace("。", "")


def _is_correct(question: Question, selected: Optional[str], answer_text: Optional[str]) -> bool:
    expected = _normalize_answer(question.answer)
    actual = _normalize_answer(selected if question.question_type == "choice" else answer_text)
    if not expected or not actual:
        return False
    if question.question_type == "choice":
        match = re.search(r"[A-D]", expected)
        return bool(match and actual[:1] == match.group(0))
    return actual == expected


async def _owned_node(
    db: AsyncSession, user_id: int, path_id: int, kp_id: str
) -> Tuple[LearningPath, LearningPathNode, KnowledgePoint]:
    path = (
        await db.execute(
            select(LearningPath).where(
                LearningPath.id == path_id, LearningPath.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if not path:
        raise HTTPException(status_code=404, detail="学习路径不存在")
    node = (
        await db.execute(
            select(LearningPathNode).where(
                LearningPathNode.path_id == path_id, LearningPathNode.kp_id == kp_id
            )
        )
    ).scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="该知识点不在当前学习路径中")
    kp = await db.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(status_code=404, detail="知识点不存在")
    return path, node, kp


def _fallback_explanation(kp: KnowledgePoint) -> Dict[str, Any]:
    name = kp.short_name or kp.name
    context = " · ".join(filter(None, [kp.grade, kp.category_1, kp.category_2]))
    content = (
        f"## 学习目标\n\n理解并能运用 **{name}**。\n\n"
        f"## 学习提示\n\n先回顾相关定义和基本方法，再结合例题归纳解题步骤。"
        + (f"\n\n课程位置：{context}" if context else "")
    )
    return {
        "id": None,
        "title": f"{name}学习导引",
        "summary": f"围绕“{name}”建立概念、方法和典型应用之间的联系。",
        "content": content,
        "content_blocks": [{"type": "markdown", "content": content}],
        "key_points": [kp.cognitive_level or "理解核心概念", "掌握基本方法", "能在题目中正确应用"],
        "examples": [],
        "common_mistakes": ["只记结论而忽略适用条件", "计算或书写过程缺少必要步骤"],
        "difficulty_level": "basic",
        "source": "system_fallback",
    }


async def get_course(
    db: AsyncSession, user_id: int, path_id: int, kp_id: str, question_count: int = 5
) -> Dict[str, Any]:
    path, node, kp = await _owned_node(db, user_id, path_id, kp_id)
    explanation = (
        await db.execute(
            select(KpExplanation)
            .where(KpExplanation.kp_id == kp_id)
            .order_by(KpExplanation.version.desc(), KpExplanation.id.desc())
        )
    ).scalars().first()

    explanation_data = _fallback_explanation(kp)
    warnings: List[str] = []
    if explanation:
        explanation_data = {
            "id": explanation.id,
            "title": explanation.title or f"{kp.short_name or kp.name}知识讲解",
            "summary": explanation.summary,
            "content": explanation.content,
            "content_blocks": normalize_content_blocks(
                _json_list(explanation.content_blocks),
                explanation.content,
            ),
            "key_points": _json_list(explanation.key_points),
            "examples": _json_list(explanation.examples),
            "common_mistakes": _json_list(explanation.common_mistakes),
            "difficulty_level": explanation.difficulty_level or "basic",
            "source": "ai_explanation",
        }

    questions, selection_diagnostics = await targeted_question_selector.select_questions(
        db,
        user_id=user_id,
        goal_id=path.goal_id,
        kp_id=kp_id,
        current_mastery=node.current_mastery,
        question_count=question_count,
    )
    if len(questions) < question_count:
        warnings.append(
            f"当前知识点仅有 {len(questions)} 道可用模拟题或AI题，少于计划的 {question_count} 道"
        )
    if selection_diagnostics["template_source"] != "kp_average_template":
        warnings.append("当前知识点平均模板题型数据不足，已使用回退题型比例")

    tasks = (
        await db.execute(
            select(LearningTask).where(
                LearningTask.path_id == path_id, LearningTask.path_node_id == node.id
            )
        )
    ).scalars().all()
    latest_evaluation = next(
        (
            (task.result_json or {}).get("evaluation")
            for task in tasks
            if task.task_type in {"practice", "training", "checkpoint"}
            and (task.result_json or {}).get("evaluation")
        ),
        None,
    )
    answer_history = next(
        (
            (task.result_json or {}).get("answer_history", [])
            for task in tasks
            if task.task_type in {"practice", "training", "checkpoint"}
            and (task.result_json or {}).get("answer_history")
        ),
        [],
    )
    if not answer_history:
        # 兼容旧版批量提交结果：旧数据没有逐题证据，不能作为实时题序的累计结果展示。
        latest_evaluation = None
    mastery_sync = (
        await db.execute(
            select(CourseMasterySync).where(
                CourseMasterySync.user_id == user_id,
                CourseMasterySync.goal_id == path.goal_id,
                CourseMasterySync.kp_id == kp_id,
            )
        )
    ).scalar_one_or_none()
    videos = (
        await db.execute(
            select(KpVideoResource)
            .where(KpVideoResource.kp_id == kp_id, KpVideoResource.is_active == 1)
            .order_by(KpVideoResource.sort_order.asc(), KpVideoResource.id.asc())
        )
    ).scalars().all()
    external = [
        {
            "title": video.title,
            "url": video.url,
            "platform": "哔哩哔哩" if video.platform == "bilibili" else "YouTube",
            "resource_type": "video",
            "note": video.description,
        }
        for video in videos
    ]
    return {
        "path_id": path.id,
        "goal_id": path.goal_id,
        "node_id": node.id,
        "kp_id": kp.id,
        "kp_name": kp.short_name or kp.name,
        "stage_index": node.stage_index,
        "role": node.role,
        "current_mastery": node.current_mastery,
        "target_mastery": node.target_mastery,
        "estimated_minutes": node.estimated_minutes,
        "objectives": [
            f"掌握度达到 {round(node.target_mastery)} 分",
            explanation_data["key_points"][0] if explanation_data["key_points"] else "理解核心概念",
            "通过针对性练习检验学习效果",
        ],
        "explanation": explanation_data,
        "external_resources": external,
        "questions": [
            {
                "id": q.id,
                "question_type": q.question_type,
                "content": q.content,
                "options": q.options,
                "difficulty": q.difficulty or 3,
                "source": q.source,
                "bank_type": q.bank_type or "mock",
                "images": q.images,
            }
            for q in questions
        ],
        "progress": {
            "node_status": node.status,
            "tasks": {task.task_type: task.status for task in tasks},
            "evaluation": latest_evaluation,
            "answered_question_ids": [
                item.get("question_id") for item in answer_history if item.get("question_id")
            ],
            "mastery_sync": (
                {
                    "mastery_score": mastery_sync.mastery_score,
                    "confidence": mastery_sync.confidence,
                    "achieved": bool(mastery_sync.achieved),
                    "synced_at": mastery_sync.synced_at.isoformat() if mastery_sync.synced_at else None,
                }
                if mastery_sync
                else None
            ),
        },
        "warnings": warnings,
    }


async def complete_course(
    db: AsyncSession, user_id: int, path_id: int, kp_id: str, body: CourseCompleteRequest
) -> Dict[str, Any]:
    _, node, _ = await _owned_node(db, user_id, path_id, kp_id)
    if node.prerequisite_kp_ids:
        prerequisite_nodes = (
            await db.execute(
                select(LearningPathNode).where(
                    LearningPathNode.path_id == path_id,
                    LearningPathNode.kp_id.in_(node.prerequisite_kp_ids),
                )
            )
        ).scalars().all()
        incomplete = [item for item in prerequisite_nodes if item.status != "completed"]
        if incomplete:
            raise HTTPException(status_code=409, detail="前置知识点课程尚未完成，当前课程未解锁")
    question_ids = list(dict.fromkeys(answer.question_id for answer in body.answers))
    questions = (
        await db.execute(
            select(Question).where(
                Question.id.in_(question_ids), Question.primary_kp_id == kp_id
            )
        )
    ).scalars().all() if question_ids else []
    question_map = {q.id: q for q in questions}
    results = []
    for answer in body.answers:
        question = question_map.get(answer.question_id)
        if not question:
            continue
        correct = _is_correct(question, answer.selected_option, answer.answer_text)
        results.append(
            {
                "question_id": question.id,
                "is_correct": correct,
                "selected_option": answer.selected_option,
                "answer_text": answer.answer_text,
                "correct_answer": question.answer,
                "analysis": question.analysis,
                "difficulty": question.difficulty or 3,
                "bank_type": question.bank_type or "real",
            }
        )
    if not results:
        raise HTTPException(status_code=422, detail="请至少完成一道练习题后再提交评估")
    tasks = (
        await db.execute(
            select(LearningTask).where(
                LearningTask.path_id == path_id, LearningTask.path_node_id == node.id
            )
        )
    ).scalars().all()
    practice_task = next(
        (task for task in tasks if task.task_type in {"practice", "training", "checkpoint"}),
        None,
    )
    previous_result = practice_task.result_json or {} if practice_task else {}
    history = list(previous_result.get("answer_history") or [])
    history_by_question = {
        int(item["question_id"]): item
        for item in history
        if item.get("question_id") is not None
    }
    for item in results:
        history_by_question[int(item["question_id"])] = item
    history = list(history_by_question.values())
    session_prior = previous_result.get("session_prior_mastery")
    if session_prior is None:
        session_prior = node.current_mastery
    evaluation = evaluate_mastery(history, node.target_mastery, session_prior)
    node.current_mastery = evaluation["mastery_score"]
    correct_count = evaluation["correct_count"]
    accuracy = evaluation["accuracy"]
    completed = body.explanation_completed and evaluation["achieved"]
    now = datetime.utcnow()
    for task in tasks:
        if task.task_type == "concept" and body.explanation_completed:
            task.status = "completed"
            task.completed_at = now
        elif task.task_type in {"practice", "training", "checkpoint"} and results:
            task.status = "completed" if evaluation["achieved"] else "in_progress"
            task.completed_at = now if evaluation["achieved"] else None
            task.result_json = {
                "answered_count": len(history),
                "correct_count": correct_count,
                "accuracy": accuracy,
                "evaluation": evaluation,
                "answer_history": history,
                "session_prior_mastery": session_prior,
            }
    required = list(tasks)
    if required and all(t.status == "completed" for t in required):
        node.status = "completed"
        node.completed_at = now
        completed = True
    from app.services.learning.path_service import _refresh_progress_and_unlock

    path = await db.get(LearningPath, path_id)
    if path:
        await _refresh_progress_and_unlock(db, path)
    await db.commit()
    return {
        "path_id": path_id,
        "node_id": node.id,
        "kp_id": kp_id,
        "answered_count": len(history),
        "correct_count": correct_count,
        "accuracy": accuracy,
        "completed": completed,
        "task_statuses": {task.task_type: task.status for task in tasks},
        "question_results": results,
        "evaluation": evaluation,
    }


async def sync_mastery(
    db: AsyncSession, user_id: int, path_id: int, kp_id: str
) -> Dict[str, Any]:
    path, node, _ = await _owned_node(db, user_id, path_id, kp_id)
    tasks = (
        await db.execute(
            select(LearningTask).where(
                LearningTask.path_id == path_id,
                LearningTask.path_node_id == node.id,
                LearningTask.task_type.in_(["practice", "training", "checkpoint"]),
            )
        )
    ).scalars().all()
    evaluation = next(
        (
            (task.result_json or {}).get("evaluation")
            for task in tasks
            if (task.result_json or {}).get("evaluation")
        ),
        None,
    )
    if not evaluation:
        raise HTTPException(status_code=409, detail="请先完成至少一道练习并生成掌握度评估")

    record = (
        await db.execute(
            select(CourseMasterySync).where(
                CourseMasterySync.user_id == user_id,
                CourseMasterySync.goal_id == path.goal_id,
                CourseMasterySync.kp_id == kp_id,
            )
        )
    ).scalar_one_or_none()
    if record is None:
        record = CourseMasterySync(
            user_id=user_id,
            goal_id=path.goal_id,
            path_id=path_id,
            kp_id=kp_id,
            mastery_score=evaluation["mastery_score"],
            confidence=evaluation["confidence"],
            achieved=int(bool(evaluation["achieved"])),
            evidence_json=evaluation,
        )
        db.add(record)
    else:
        record.path_id = path_id
        record.mastery_score = evaluation["mastery_score"]
        record.confidence = evaluation["confidence"]
        record.achieved = int(bool(evaluation["achieved"]))
        record.evidence_json = evaluation
        record.synced_at = datetime.utcnow()
    await db.commit()
    await db.refresh(record)
    return {
        "path_id": path_id,
        "goal_id": path.goal_id,
        "kp_id": kp_id,
        "mastery_score": record.mastery_score,
        "confidence": record.confidence,
        "achieved": bool(record.achieved),
        "synced_at": record.synced_at,
    }


async def list_courses(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    rows = (
        await db.execute(
            select(LearningPath, LearningPathNode, KnowledgePoint, LearningGoal)
            .join(LearningPathNode, LearningPathNode.path_id == LearningPath.id)
            .join(KnowledgePoint, KnowledgePoint.id == LearningPathNode.kp_id)
            .join(LearningGoal, LearningGoal.id == LearningPath.goal_id)
            .where(
                LearningPath.user_id == user_id,
                LearningPath.status == "current",
                LearningPathNode.role != "verify",
            )
            .order_by(LearningPathNode.stage_index, LearningPathNode.order_index)
        )
    ).all()
    completed_kps = set()
    items = []
    for path, node, kp, goal in rows:
        available = all(req in completed_kps for req in (node.prerequisite_kp_ids or []))
        items.append(
            {
                "path_id": path.id,
                "goal_id": goal.id,
                "goal_title": goal.title or "学习目标",
                "kp_id": kp.id,
                "kp_name": kp.short_name or kp.name,
                "node_id": node.id,
                "stage_index": node.stage_index,
                "estimated_minutes": node.estimated_minutes,
                "status": node.status,
                "available": available,
            }
        )
        if node.status == "completed":
            completed_kps.add(node.kp_id)
    return items
