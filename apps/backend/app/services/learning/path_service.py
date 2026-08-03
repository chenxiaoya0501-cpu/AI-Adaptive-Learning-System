"""学习路径 v2：快照编排、版本管理、任务执行与重规划闭环。"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint, KnowledgeRelation
from app.models.question import ExamKpScoreStat
from app.models.student.goal import LearningGoal
from app.models.student.learning_path import LearningPath, LearningPathNode, LearningTask
from app.models.student.test_paper import TestPaper, TestQuestion
from app.schemas.student.learning_path import LearningPathGenerateRequest, LearningTaskUpdate
from app.services.learning import goal_service
from app.services.learning.assembly import resolve_template
from app.services.learning.mastery_snapshot import build_mastery_snapshot
from app.services.learning.path_planner import (
    ALGORITHM_VERSION,
    MIN_DIRECT_GAIN,
    MIN_GAIN_PER_MINUTE,
    build_plan,
    dependency_order as _dependency_order,
    role_for as _role,
    tarjan_components as _tarjan,
)

BUFFER_RATIO = 0.20


async def load_exam_weights(
    db: AsyncSession,
    goal: LearningGoal,
    scope_ids: List[str],
    paper_ids: List[int],
) -> Tuple[Dict[str, float], Dict[str, str], Optional[int], float, List[str]]:
    warnings: List[str] = []
    template = None
    try:
        template = await resolve_template(
            db, goal.subject, goal.region, goal.exam_type, template_id=None
        )
    except HTTPException:
        warnings.append("未找到适用的考试结构模板，已回退目标测评实际分值占比")

    template_raw: Dict[str, float] = {}
    if template:
        rows = (
            await db.execute(
                select(ExamKpScoreStat).where(
                    ExamKpScoreStat.template_id == template.id,
                    ExamKpScoreStat.question_type.is_(None),
                    ExamKpScoreStat.kp_id.in_(scope_ids),
                )
            )
        ).scalars().all()
        template_raw = {
            row.kp_id: max(0.0, float(row.score_ratio or 0.0)) for row in rows
        }

    empirical_raw: Dict[str, float] = defaultdict(float)
    if paper_ids:
        questions = (
            await db.execute(
                select(TestQuestion).where(TestQuestion.test_paper_id.in_(paper_ids))
            )
        ).scalars().all()
        for question in questions:
            kp_ids = list(
                dict.fromkeys(
                    [
                        question.primary_kp_id,
                        *(question.secondary_kp_ids or []),
                    ]
                )
            )
            kp_ids = [kp_id for kp_id in kp_ids if kp_id in scope_ids]
            if not kp_ids:
                continue
            share = max(0.0, float(question.score or 0.0)) / len(kp_ids)
            for kp_id in kp_ids:
                empirical_raw[kp_id] += share
    empirical_total = sum(empirical_raw.values())
    empirical_ratio = (
        {kp_id: score / empirical_total for kp_id, score in empirical_raw.items()}
        if empirical_total > 0
        else {}
    )

    raw: Dict[str, float] = {}
    sources: Dict[str, str] = {}
    for kp_id in scope_ids:
        if template_raw.get(kp_id, 0.0) > 0:
            raw[kp_id] = template_raw[kp_id]
            sources[kp_id] = "template"
        elif empirical_ratio.get(kp_id, 0.0) > 0:
            raw[kp_id] = empirical_ratio[kp_id]
            sources[kp_id] = "empirical"
        else:
            raw[kp_id] = 0.0
            sources[kp_id] = "none"
    total = sum(raw.values())
    weights = (
        {kp_id: value / total for kp_id, value in raw.items()}
        if total > 0
        else {kp_id: 0.0 for kp_id in scope_ids}
    )
    if total <= 0:
        warnings.append("缺少可靠的考试价值权重，本轮不生成正式学习任务，请先完成目标测评后重新规划")
    total_score = (
        float(template.total_score or goal.target_score or 100)
        if template
        else max(float(goal.target_score or 100), 100.0)
    )
    return weights, sources, template.id if template else None, total_score, warnings


def _current_estimate(
    scope_nodes: List[Dict[str, Any]],
    weights: Dict[str, float],
    total_score: float,
    goal: LearningGoal,
    latest_paper: Optional[Dict[str, Any]],
) -> Tuple[float, str]:
    weighted = 0.0
    observed_weight = 0.0
    for node in scope_nodes:
        kp_id = node["kp_id"]
        weight = weights.get(kp_id, 0.0)
        if weight <= 0:
            continue
        confidence = max(0.0, min(1.0, float(node.get("confidence") or 0.0)))
        score = node.get("mastery_score")
        mastery = 0.50 if score is None else max(0.0, min(1.0, float(score) / 100))
        effective = confidence * mastery + (1 - confidence) * 0.50
        weighted += weight * effective
        observed_weight += weight
    if observed_weight > 0:
        return total_score * weighted / observed_weight, "mastery_weighted"
    if goal.current_score_estimate is not None:
        return float(goal.current_score_estimate), "goal_estimate"
    if latest_paper and latest_paper.get("total_score") and latest_paper.get("earned_score") is not None:
        return (
            float(latest_paper["earned_score"])
            / float(latest_paper["total_score"])
            * total_score,
            "latest_paper",
        )
    return total_score * 0.50, "neutral_prior"


async def build_preview(
    db: AsyncSession,
    user_id: int,
    goal_id: int,
    request: LearningPathGenerateRequest,
) -> Dict[str, Any]:
    goal = await goal_service.get_owned_goal(db, goal_id, user_id)
    map_data = await build_mastery_snapshot(db, user_id, goal_id)
    scope_nodes = [
        node
        for node in map_data["nodes"]
        if node.get("node_type") == "knowledge"
        and node.get("kp_id")
        and node.get("is_in_goal_scope")
    ]
    if not scope_nodes:
        raise HTTPException(status_code=409, detail="学习目标尚未关联知识点，无法生成路径")
    scope_ids = list(dict.fromkeys(node["kp_id"] for node in scope_nodes))
    kp_rows = (
        await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(scope_ids)))
    ).scalars().all()
    kp_meta: Dict[str, Dict[str, Any]] = {
        kp.id: {
            "subject": kp.subject,
            "display_name": (kp.short_name or "").strip() or kp.name,
            "description": kp.name,
            "domain": kp.domain,
            "category_1": kp.category_1,
            "category_2": kp.category_2,
            "grade": kp.grade,
            "chapter": kp.chapter,
            "cognitive_level": kp.cognitive_level,
        }
        for kp in kp_rows
    }
    kp_meta["__goal__"] = {"subject": goal.subject}

    relations = (
        await db.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.relation_type == "prerequisite",
                KnowledgeRelation.from_point_id.in_(scope_ids),
                KnowledgeRelation.to_point_id.in_(scope_ids),
            )
        )
    ).scalars().all()
    prereqs_by_dependent: Dict[str, Set[str]] = defaultdict(set)
    dependent_by_prereq: Dict[str, Set[str]] = defaultdict(set)
    relation_snapshot: List[Dict[str, Any]] = []
    relation_strengths: Dict[Tuple[str, str], float] = {}
    for relation in relations:
        prereqs_by_dependent[relation.to_point_id].add(relation.from_point_id)
        dependent_by_prereq[relation.from_point_id].add(relation.to_point_id)
        relation_strengths[(relation.from_point_id, relation.to_point_id)] = max(
            0.05, float(relation.weight or 1.0)
        )
        relation_snapshot.append(
            {
                "from": relation.from_point_id,
                "to": relation.to_point_id,
                "weight": float(relation.weight or 1.0),
            }
        )

    source_paper_ids = [int(item["id"]) for item in map_data.get("papers", [])]
    weights, weight_sources, template_id, total_score, warnings = await load_exam_weights(
        db, goal, scope_ids, source_paper_ids
    )
    current_score, current_score_source = _current_estimate(
        scope_nodes, weights, total_score, goal, map_data.get("paper")
    )
    target_score = min(float(goal.target_score), total_score)
    daily_minutes = request.daily_study_minutes or goal.daily_study_minutes or 45
    start = request.start_date or date.today()
    horizon_days = (
        request.horizon_days
        if request.horizon_days
        else max(1, (goal.exam_date - start).days)
        if goal.exam_date
        else 14
    )
    capacity_minutes = max(
        0, math.floor(daily_minutes * horizon_days * (1 - BUFFER_RATIO))
    )
    planned = build_plan(
        scope_nodes=scope_nodes,
        kp_meta=kp_meta,
        weights=weights,
        weight_sources=weight_sources,
        prereqs_by_dependent=prereqs_by_dependent,
        dependent_by_prereq=dependent_by_prereq,
        relation_strengths=relation_strengths,
        total_score=total_score,
        current_score=current_score,
        target_score=target_score,
        capacity_minutes=capacity_minutes,
        daily_minutes=daily_minutes,
        horizon_days=horizon_days,
        start_date=start,
    )
    planned["summary"]["warnings"] = [
        *warnings,
        *planned["summary"].get("warnings", []),
    ]
    planned["summary"].update(
        {
            "template_id": template_id,
            "current_score_source": current_score_source,
            "weight_source": (
                "template"
                if any(source == "template" for source in weight_sources.values())
                else "empirical"
                if any(source == "empirical" for source in weight_sources.values())
                else "none"
            ),
        }
    )
    mastery_snapshot = [
        {
            "kp_id": node["kp_id"],
            "mastery": node.get("mastery_score"),
            "confidence": node.get("confidence", 0),
            "attempt_count": node.get("attempt_count", 0),
        }
        for node in scope_nodes
    ]
    signature_payload = {
        "goal": {
            "id": goal.id,
            "target_score": goal.target_score,
            "exam_date": goal.exam_date.isoformat() if goal.exam_date else None,
            "daily_minutes": daily_minutes,
            "scope_ids": scope_ids,
        },
        "papers": source_paper_ids,
        "mastery": mastery_snapshot,
        "weights": sorted(weights.items()),
        "relations": relation_snapshot,
        "params": request.model_dump(mode="json"),
        "algorithm": ALGORITHM_VERSION,
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "goal_id": goal.id,
        "status": "preview",
        "algorithm_version": ALGORITHM_VERSION,
        "generation_reason": request.generation_reason,
        "source_paper_ids": source_paper_ids,
        "summary": planned["summary"],
        "nodes": planned["nodes"],
        "tasks": planned["tasks"],
        "_input_signature": signature,
        "_mastery_snapshot": mastery_snapshot,
        "_goal_snapshot": signature_payload["goal"],
        "_planning_params": {
            **request.model_dump(mode="json"),
            "buffer_ratio": BUFFER_RATIO,
            "min_direct_gain": MIN_DIRECT_GAIN,
            "min_gain_per_minute": MIN_GAIN_PER_MINUTE,
            "unlock_alpha": 0.70,
            "total_score": total_score,
            "planning_scope": "first_pass",
        },
    }


async def generate(
    db: AsyncSession, user_id: int, goal_id: int, request: LearningPathGenerateRequest
) -> Dict[str, Any]:
    preview = await build_preview(db, user_id, goal_id, request)
    existing = (
        await db.execute(
            select(LearningPath).where(
                LearningPath.goal_id == goal_id,
                LearningPath.user_id == user_id,
                LearningPath.input_signature == preview["_input_signature"],
                LearningPath.status.in_(("draft", "current")),
            )
        )
    ).scalar_one_or_none()
    if existing:
        return await get_detail(db, user_id, existing.id)
    version = (
        await db.execute(
            select(func.coalesce(func.max(LearningPath.version), 0)).where(
                LearningPath.goal_id == goal_id
            )
        )
    ).scalar_one() + 1
    path = LearningPath(
        user_id=user_id,
        goal_id=goal_id,
        version=version,
        status="draft",
        generation_reason=request.generation_reason,
        algorithm_version=ALGORITHM_VERSION,
        input_signature=preview["_input_signature"],
        source_paper_ids=preview["source_paper_ids"],
        goal_snapshot=preview["_goal_snapshot"],
        mastery_snapshot=preview["_mastery_snapshot"],
        planning_params=preview["_planning_params"],
        summary_json=preview["summary"],
    )
    db.add(path)
    await db.flush()
    node_ids: Dict[str, int] = {}
    for item in preview["nodes"]:
        node = LearningPathNode(
            path_id=path.id,
            kp_id=item["kp_id"],
            order_index=item["order_index"],
            stage_index=item["stage_index"],
            stage_type=item["stage_type"],
            role=item["role"],
            current_mastery=item["current_mastery"],
            target_mastery=item["target_mastery"],
            confidence=item["confidence"],
            exam_weight=item["exam_weight"],
            priority=item["priority"],
            expected_gain=item["expected_gain"],
            estimated_minutes=item["estimated_minutes"],
            prerequisite_kp_ids=item["prerequisite_kp_ids"],
            reason_json={**item["reason"], "name": item["name"]},
        )
        db.add(node)
        await db.flush()
        node_ids[item["kp_id"]] = node.id
    for item in preview["tasks"]:
        db.add(
            LearningTask(
                path_id=path.id,
                path_node_id=node_ids[item["kp_id"]],
                user_id=user_id,
                scheduled_date=item["scheduled_date"],
                sequence=item["sequence"],
                task_type=item["task_type"],
                title=item["title"],
                instruction=item["instruction"],
                estimated_minutes=item["estimated_minutes"],
                status=item["status"],
            )
        )
    await db.commit()
    return await get_detail(db, user_id, path.id)


async def activate(db: AsyncSession, user_id: int, path_id: int) -> Dict[str, Any]:
    path = await _get_owned_path(db, user_id, path_id)
    await db.execute(
        update(LearningPath)
        .where(
            LearningPath.goal_id == path.goal_id,
            LearningPath.user_id == user_id,
            LearningPath.status == "current",
            LearningPath.id != path.id,
        )
        .values(status="archived")
    )
    path.status = "current"
    path.activated_at = datetime.utcnow()
    goal = await goal_service.get_owned_goal(db, path.goal_id, user_id)
    goal.needs_replan = False
    await _refresh_progress_and_unlock(db, path)
    await db.commit()
    return await get_detail(db, user_id, path.id)


async def get_current(
    db: AsyncSession, user_id: int, goal_id: int
) -> Optional[Dict[str, Any]]:
    await goal_service.get_owned_goal(db, goal_id, user_id)
    path = (
        await db.execute(
            select(LearningPath)
            .where(
                LearningPath.goal_id == goal_id,
                LearningPath.user_id == user_id,
                LearningPath.status == "current",
            )
            .order_by(LearningPath.version.desc())
        )
    ).scalars().first()
    return await get_detail(db, user_id, path.id) if path else None


async def list_versions(
    db: AsyncSession, user_id: int, goal_id: int
) -> List[Dict[str, Any]]:
    await goal_service.get_owned_goal(db, goal_id, user_id)
    paths = (
        await db.execute(
            select(LearningPath)
            .where(
                LearningPath.goal_id == goal_id, LearningPath.user_id == user_id
            )
            .order_by(LearningPath.version.desc())
        )
    ).scalars().all()
    return [await get_detail(db, user_id, path.id) for path in paths]


async def replan(
    db: AsyncSession,
    user_id: int,
    goal_id: int,
    request: LearningPathGenerateRequest,
) -> Dict[str, Any]:
    request.generation_reason = request.generation_reason or "assessment_updated"
    if request.generation_reason == "manual":
        request.generation_reason = "manual_replan"
    return await generate(db, user_id, goal_id, request)


async def _get_owned_path(db: AsyncSession, user_id: int, path_id: int) -> LearningPath:
    path = (
        await db.execute(
            select(LearningPath).where(
                LearningPath.id == path_id, LearningPath.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if path is None:
        raise HTTPException(status_code=404, detail="学习路径不存在")
    return path


async def _get_owned_task(db: AsyncSession, user_id: int, task_id: int) -> LearningTask:
    task = (
        await db.execute(
            select(LearningTask).where(
                LearningTask.id == task_id, LearningTask.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="学习任务不存在")
    return task


async def _refresh_progress_and_unlock(db: AsyncSession, path: LearningPath) -> None:
    nodes = (
        await db.execute(
            select(LearningPathNode)
            .where(LearningPathNode.path_id == path.id)
            .order_by(LearningPathNode.order_index)
        )
    ).scalars().all()
    tasks = (
        await db.execute(
            select(LearningTask)
            .where(LearningTask.path_id == path.id)
            .order_by(LearningTask.sequence)
        )
    ).scalars().all()
    tasks_by_node: Dict[int, List[LearningTask]] = defaultdict(list)
    for task in tasks:
        tasks_by_node[task.path_node_id].append(task)
    node_by_kp = {node.kp_id: node for node in nodes}
    now = datetime.utcnow()
    today = date.today()
    base_complete_by_kp: Dict[str, bool] = {}
    for node in nodes:
        node_tasks = tasks_by_node.get(node.id, [])
        base_tasks: List[LearningTask] = []
        for task in node_tasks:
            if task.task_type == "reinforcement":
                break
            base_tasks.append(task)
        base_complete_by_kp[node.kp_id] = bool(base_tasks) and all(
            task.status in ("completed", "skipped") for task in base_tasks
        )
        terminal_before_last = all(
            task.status in ("completed", "skipped") for task in node_tasks[:-1]
        )
        checkpoint_passed = bool(
            node_tasks
            and node_tasks[-1].status == "completed"
            and terminal_before_last
        )
        if checkpoint_passed:
            node.status = "completed"
            node.completed_at = node.completed_at or now
        elif any(task.status in ("in_progress", "completed", "skipped") for task in node_tasks):
            node.status = "in_progress"
        else:
            node.status = "pending"
    for node in nodes:
        dependencies_complete = all(
            node_by_kp.get(kp_id) is None
            or base_complete_by_kp.get(kp_id, False)
            for kp_id in (node.prerequisite_kp_ids or [])
        )
        previous_terminal = True
        for task in tasks_by_node.get(node.id, []):
            if task.status in ("completed", "skipped", "in_progress"):
                previous_terminal = task.status in ("completed", "skipped")
                continue
            should_open = (
                dependencies_complete
                and previous_terminal
                and task.scheduled_date <= today
            )
            task.status = "pending" if should_open else "blocked"
            previous_terminal = False
    if nodes and all(node.status == "completed" for node in nodes):
        path.completed_at = path.completed_at or now


async def update_task(
    db: AsyncSession, user_id: int, task_id: int, body: LearningTaskUpdate
) -> Dict[str, Any]:
    task = await _get_owned_task(db, user_id, task_id)
    path = await _get_owned_path(db, user_id, task.path_id)
    if path.status != "current":
        raise HTTPException(status_code=409, detail="只能执行当前学习路径中的任务")
    await _refresh_progress_and_unlock(db, path)
    if task.status == "blocked" and body.status != "blocked":
        raise HTTPException(status_code=409, detail="前置任务尚未完成，当前任务未解锁")
    if body.status not in ("pending", "in_progress", "completed", "skipped"):
        raise HTTPException(status_code=422, detail="不支持的任务状态")
    if body.status == "in_progress" and task.started_at is None:
        task.started_at = datetime.utcnow()
    if body.status == "completed":
        task.started_at = task.started_at or datetime.utcnow()
        task.completed_at = datetime.utcnow()
    elif body.status in ("pending", "in_progress"):
        task.completed_at = None
    task.status = body.status
    if body.result is not None:
        task.result_json = body.result
    await db.flush()
    await _refresh_progress_and_unlock(db, path)
    await db.commit()
    return await get_detail(db, user_id, path.id)


async def get_detail(db: AsyncSession, user_id: int, path_id: int) -> Dict[str, Any]:
    path = await _get_owned_path(db, user_id, path_id)
    goal = await goal_service.get_owned_goal(db, path.goal_id, user_id)
    if path.status == "current":
        await _refresh_progress_and_unlock(db, path)
        await db.commit()
    nodes = (
        await db.execute(
            select(LearningPathNode)
            .where(LearningPathNode.path_id == path.id)
            .order_by(LearningPathNode.order_index)
        )
    ).scalars().all()
    tasks = (
        await db.execute(
            select(LearningTask)
            .where(LearningTask.path_id == path.id)
            .order_by(LearningTask.sequence)
        )
    ).scalars().all()
    kp_ids = [node.kp_id for node in nodes]
    kp_rows = (
        await db.execute(select(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids)))
    ).scalars().all() if kp_ids else []
    names = {kp.id: (kp.short_name or kp.name) for kp in kp_rows}
    node_kp = {node.id: node.kp_id for node in nodes}
    latest_paper_ids = set(
        (
            await db.execute(
                select(TestPaper.id).where(
                    TestPaper.goal_id == path.goal_id,
                    TestPaper.user_id == user_id,
                    TestPaper.status == "graded",
                )
            )
        ).scalars().all()
    )
    is_stale = bool(goal.needs_replan) or bool(
        latest_paper_ids - set(path.source_paper_ids or [])
    )
    completed_tasks = sum(task.status == "completed" for task in tasks)
    summary = {
        **(path.summary_json or {}),
        "completed_task_count": completed_tasks,
        "progress_percent": round(completed_tasks / len(tasks) * 100) if tasks else 0,
        "is_stale": is_stale,
        "completed_at": path.completed_at.isoformat() if path.completed_at else None,
    }
    return {
        "id": path.id,
        "goal_id": path.goal_id,
        "version": path.version,
        "status": path.status,
        "algorithm_version": path.algorithm_version,
        "generation_reason": path.generation_reason,
        "source_paper_ids": path.source_paper_ids or [],
        "summary": summary,
        "nodes": [
            {
                "id": node.id,
                "kp_id": node.kp_id,
                "name": names.get(node.kp_id, (node.reason_json or {}).get("name", node.kp_id)),
                "order_index": node.order_index,
                "stage_index": node.stage_index,
                "stage_type": node.stage_type,
                "role": node.role,
                "current_mastery": node.current_mastery,
                "target_mastery": node.target_mastery,
                "confidence": node.confidence,
                "exam_weight": node.exam_weight,
                "priority": node.priority,
                "expected_gain": node.expected_gain,
                "estimated_minutes": node.estimated_minutes,
                "prerequisite_kp_ids": node.prerequisite_kp_ids or [],
                "reason": node.reason_json or {},
                "status": node.status,
            }
            for node in nodes
        ],
        "tasks": [
            {
                "id": task.id,
                "path_node_id": task.path_node_id,
                "kp_id": node_kp.get(task.path_node_id, ""),
                "scheduled_date": task.scheduled_date,
                "sequence": task.sequence,
                "task_type": task.task_type,
                "title": task.title,
                "instruction": task.instruction,
                "estimated_minutes": task.estimated_minutes,
                "status": task.status,
                "result": task.result_json,
            }
            for task in tasks
        ],
        "created_at": path.created_at,
    }
