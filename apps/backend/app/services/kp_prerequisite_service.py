"""AI 生成知识点前置依赖关系。"""
import asyncio
import logging
from typing import Dict, List, Optional

from sqlalchemy import select

from app.database import async_session
from app.models.knowledge import KnowledgePoint, KnowledgeRelation
from app.models.system import SystemConfig
from app.services.knowledge_relation_sync import sync_prerequisite_names
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是初中数学知识图谱专家。请为目标知识点选择真正必要的前置知识点。
前置知识点是“学习目标知识点之前必须先掌握的知识”，不是同类词、后续知识或泛泛相关知识。
只能使用候选列表中的 ID；每个目标最多选择 3 个；没有必要前置时返回空数组；禁止选择自身。
严格输出 JSON：
{"results":[{"target_id":"MATH-01-001","prerequisite_ids":["MATH-01-002"]}]}"""

_task_progress: Dict[str, dict] = {}


def get_prerequisite_task_progress(task_key: str) -> Optional[dict]:
    return _task_progress.get(task_key)


def run_prerequisite_task(task_key: str, point_ids: Optional[List[str]] = None):
    asyncio.run(_run_prerequisite_async(task_key, point_ids))


def _point_line(point: KnowledgePoint) -> str:
    short = (point.short_name or "").strip() or point.name[:30]
    category = "/".join(
        value for value in [point.domain, point.category_1, point.category_2] if value
    )
    return (
        f"{point.id} | {short} | {category or '-'} | {point.grade or '-'} | "
        f"{(point.name or '')[:100]}"
    )


async def _run_prerequisite_async(task_key: str, point_ids: Optional[List[str]]):
    _task_progress[task_key] = {
        "status": "running",
        "progress": 0,
        "total": 0,
        "done": 0,
        "created": 0,
        "error": None,
    }
    async with async_session() as db:
        try:
            configs = {
                row.key: row.value
                for row in (await db.execute(select(SystemConfig))).scalars().all()
            }
            if not configs.get("llm_api_key"):
                _task_progress[task_key].update(
                    {
                        "status": "failed",
                        "progress": 100,
                        "error": "未配置LLM API密钥，请到「系统配置 → 运行设置」填写",
                    }
                )
                return
            llm = create_llm_client(configs)

            all_points = list(
                (
                    await db.execute(
                        select(KnowledgePoint).order_by(
                            KnowledgePoint.domain, KnowledgePoint.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            selected = set(point_ids or [])
            targets = (
                [point for point in all_points if point.id in selected]
                if selected
                else all_points
            )
            if not targets:
                _task_progress[task_key].update(
                    {
                        "status": "completed",
                        "progress": 100,
                        "error": "没有符合条件的知识点",
                    }
                )
                return

            total = len(targets)
            done = 0
            created = 0
            _task_progress[task_key]["total"] = total
            points_by_domain: Dict[str, List[KnowledgePoint]] = {}
            for point in all_points:
                points_by_domain.setdefault(point.domain or "未分类", []).append(point)

            batch_size = 8
            for start in range(0, total, batch_size):
                batch = targets[start : start + batch_size]
                domains = {point.domain or "未分类" for point in batch}
                candidates: List[KnowledgePoint] = []
                seen = set()
                for domain in domains:
                    for point in points_by_domain.get(domain, []):
                        if point.id not in seen:
                            candidates.append(point)
                            seen.add(point.id)

                user_prompt = (
                    "【目标知识点】\n"
                    + "\n".join(_point_line(point) for point in batch)
                    + "\n\n【候选前置知识点】\n"
                    + "\n".join(_point_line(point) for point in candidates)
                )
                try:
                    data = await llm.extract_json(SYSTEM_PROMPT, user_prompt)
                except Exception as exc:
                    logger.warning("前置知识点生成失败 batch=%s: %s", start, exc)
                    done += len(batch)
                    _task_progress[task_key].update(
                        {"done": done, "progress": min(int(done / total * 100), 99)}
                    )
                    continue

                results = data.get("results", []) if isinstance(data, dict) else []
                target_ids = {point.id for point in batch}
                candidate_ids = {point.id for point in candidates}
                for row in results:
                    if not isinstance(row, dict):
                        continue
                    target_id = str(row.get("target_id") or "").strip()
                    if target_id not in target_ids:
                        continue
                    raw_ids = row.get("prerequisite_ids") or []
                    if not isinstance(raw_ids, list):
                        raw_ids = []
                    for prerequisite_id in list(dict.fromkeys(raw_ids))[:3]:
                        prerequisite_id = str(prerequisite_id).strip()
                        if (
                            prerequisite_id not in candidate_ids
                            or prerequisite_id == target_id
                        ):
                            continue
                        exists = (
                            await db.execute(
                                select(KnowledgeRelation.id).where(
                                    KnowledgeRelation.from_point_id == prerequisite_id,
                                    KnowledgeRelation.to_point_id == target_id,
                                    KnowledgeRelation.relation_type == "prerequisite",
                                )
                            )
                        ).scalar_one_or_none()
                        if exists is None:
                            db.add(
                                KnowledgeRelation(
                                    from_point_id=prerequisite_id,
                                    to_point_id=target_id,
                                    relation_type="prerequisite",
                                    weight=1.0,
                                )
                            )
                            created += 1

                await db.flush()
                await sync_prerequisite_names(
                    db, [point.id for point in batch]
                )
                await db.commit()
                done += len(batch)
                _task_progress[task_key].update(
                    {
                        "done": done,
                        "created": created,
                        "progress": min(int(done / total * 100), 99),
                    }
                )

            _task_progress[task_key] = {
                "status": "completed",
                "progress": 100,
                "total": total,
                "done": done,
                "created": created,
                "error": None,
            }
        except Exception as exc:
            logger.error("前置知识点生成任务失败", exc_info=True)
            _task_progress[task_key].update(
                {"status": "failed", "progress": 100, "error": str(exc)[:500]}
            )
