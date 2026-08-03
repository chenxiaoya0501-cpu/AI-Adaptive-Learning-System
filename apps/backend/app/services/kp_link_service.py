"""题目-知识点智能关联服务（复用系统配置中的大模型）"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from sqlalchemy import select, or_

from app.database import async_session
from app.models.question import Question, KpLinkTask, KpLinkSuggestion
from app.models.knowledge import KnowledgePoint
from app.models.system import SystemConfig
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)

IMG_RE = re.compile(r"\[IMG:[^\]]+\]")

KP_LINK_PROMPT = """你是初中数学教研助手。请根据题目内容，从给定知识点列表中选出最匹配的「一个」主知识点。

知识点列表（格式：[ID] 名称 | 分类）：
{kp_list}

请严格输出 JSON 对象：
{{
  "matches": [
    {{
      "question_index": 0,
      "kp_id": "必须从上方列表复制完整ID，如 MATH-01-001",
      "confidence": "high/medium/low",
      "reason": "一句话理由"
    }}
  ]
}}

规则：
1. kp_id 必须来自列表，禁止编造；优先复制完整 ID
2. 每道题只选一个主知识点
3. 不确定时用 medium 或 low，不要乱选
4. matches 数量必须与输入题目数量一致，question_index 从 0 开始"""


def run_kp_link_task(task_id: int):
    asyncio.run(_run_kp_link_async(task_id))


def _clean_question_text(text: str, limit: int = 400) -> str:
    cleaned = IMG_RE.sub(" ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def _resolve_kp_id(
    raw: Any,
    valid_ids: set,
    name_to_id: Dict[str, str],
) -> Optional[str]:
    """将模型返回值解析为合法知识点 ID（支持 ID / 名称）"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in valid_ids:
        return text

    # 常见包一层：MATH-01-001（xxx）
    m = re.search(r"(MATH-\d{2}-\d{3})", text, re.IGNORECASE)
    if m and m.group(1).upper() in {x.upper() for x in valid_ids}:
        # 还原原始大小写
        upper_map = {x.upper(): x for x in valid_ids}
        return upper_map[m.group(1).upper()]

    for vid in valid_ids:
        if vid in text:
            return vid

    # 按名称精确/包含匹配
    if text in name_to_id:
        return name_to_id[text]
    for name, kid in name_to_id.items():
        if name and (name in text or text in name):
            return kid
    return None


def _parse_matches(data: Any) -> List[dict]:
    if data is None:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        matches = data.get("matches")
        if isinstance(matches, list):
            return [x for x in matches if isinstance(x, dict)]
        # 兼容偶发直接返回单条
        if "kp_id" in data or "question_index" in data:
            return [data]
    return []


async def _run_kp_link_async(task_id: int):
    async with async_session() as db:
        try:
            result = await db.execute(select(KpLinkTask).where(KpLinkTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                return

            task.status = "running"
            task.started_at = datetime.now()
            task.error_message = None
            await db.commit()

            config_result = await db.execute(select(SystemConfig))
            configs = {c.key: c.value for c in config_result.scalars().all()}
            if not configs.get("llm_api_key"):
                task.status = "failed"
                task.error_message = "未配置LLM API密钥，请到「系统配置 → 运行设置」填写（与知识抽取共用）"
                await db.commit()
                return

            llm = create_llm_client(configs)
            scope = task.scope or {}

            kp_query = select(KnowledgePoint).where(
                or_(
                    KnowledgePoint.status == "published",
                    KnowledgePoint.status == "reviewed",
                    KnowledgePoint.status == "draft",
                )
            )
            kp_result = await db.execute(kp_query)
            kps = list(kp_result.scalars().all())
            if not kps:
                task.status = "failed"
                task.error_message = "知识点库为空，请先抽取知识点"
                await db.commit()
                return

            valid_ids = {kp.id for kp in kps}
            name_to_id = {(kp.name or "").strip(): kp.id for kp in kps if (kp.name or "").strip()}
            # 名称过长时截断后也做一份索引，便于匹配
            for kp in kps:
                short = (kp.name or "").strip()[:40]
                if short and short not in name_to_id:
                    name_to_id[short] = kp.id

            kp_list_text = "\n".join([
                f"- [{kp.id}] {(kp.name or '')[:60]} | {kp.category_1 or ''}/{kp.category_2 or ''}"
                for kp in kps[:300]
            ])

            q_query = select(Question)
            if scope.get("question_ids"):
                # 已明确选题时不再叠加 bank_type，避免误过滤
                q_query = q_query.where(Question.id.in_(scope["question_ids"]))
            else:
                if scope.get("exam_paper_id"):
                    q_query = q_query.where(Question.exam_paper_id == scope["exam_paper_id"])
                if scope.get("bank_type"):
                    q_query = q_query.where(Question.bank_type == scope["bank_type"])
            if scope.get("only_unlinked"):
                q_query = q_query.where(
                    or_(Question.primary_kp_id.is_(None), Question.primary_kp_id == "")
                )

            q_result = await db.execute(q_query.order_by(Question.id))
            questions = list(q_result.scalars().all())
            if not questions:
                task.status = "failed"
                task.error_message = "没有符合条件的题目"
                await db.commit()
                return

            batch_size = 5
            try:
                batch_size = max(1, min(10, int(configs.get("extraction_batch_size") or 5)))
            except Exception:
                batch_size = 5

            total = len(questions)
            suggested = 0
            llm_errors: List[str] = []
            batches_ok = 0

            for i in range(0, total, batch_size):
                batch = questions[i:i + batch_size]
                lines = []
                for idx, q in enumerate(batch):
                    content = _clean_question_text(q.content or "", 400)
                    opts = ""
                    if q.options and isinstance(q.options, dict):
                        opts = " ".join([f"{k}.{v}" for k, v in q.options.items()])
                        opts = _clean_question_text(opts, 160)
                    lines.append(f"题目{idx}: {content}\n选项: {opts}")

                user_prompt = f"请为以下{len(batch)}道题匹配主知识点：\n\n" + "\n\n".join(lines)
                system_prompt = KP_LINK_PROMPT.format(kp_list=kp_list_text)

                data = None
                try:
                    data = await llm.extract_json(system_prompt, user_prompt)
                except Exception as e:
                    err = str(e)
                    logger.warning(f"KP关联LLM失败 task={task_id} batch={i}: {err}")
                    llm_errors.append(err[:300])
                    # 本批失败也写入空建议，附上失败原因，避免前端只看到「无建议」且无解释
                    for q in batch:
                        db.add(KpLinkSuggestion(
                            task_id=task_id,
                            question_id=q.id,
                            suggested_kp_id=None,
                            confidence="low",
                            reason=f"大模型调用失败: {err[:200]}",
                            status="pending",
                        ))
                    task.progress = min(int((i + len(batch)) / total * 100), 99)
                    await db.commit()
                    continue

                matches = _parse_matches(data)
                if not matches:
                    logger.warning(f"KP关联返回空 matches task={task_id} batch={i} data={data}")
                    llm_errors.append("模型返回中无 matches")
                else:
                    batches_ok += 1

                match_by_idx = {}
                for m in matches:
                    try:
                        match_by_idx[int(m.get("question_index", -1))] = m
                    except Exception:
                        continue
                # 若模型未给 index，按顺序兜底
                if not match_by_idx and matches:
                    for idx, m in enumerate(matches[:len(batch)]):
                        match_by_idx[idx] = m

                for idx, q in enumerate(batch):
                    m = match_by_idx.get(idx, {})
                    kp_id = _resolve_kp_id(m.get("kp_id") or m.get("id") or m.get("knowledge_point_id"), valid_ids, name_to_id)
                    if not kp_id:
                        # 再用名称字段试一次
                        kp_id = _resolve_kp_id(m.get("kp_name") or m.get("name"), valid_ids, name_to_id)

                    conf = str(m.get("confidence") or "medium").lower()
                    if conf not in ("high", "medium", "low"):
                        conf = "medium"
                    reason = str(m.get("reason") or "")[:500]
                    if not kp_id and not reason:
                        reason = "未能匹配到合法知识点ID，请改选"

                    db.add(KpLinkSuggestion(
                        task_id=task_id,
                        question_id=q.id,
                        suggested_kp_id=kp_id,
                        confidence=conf,
                        reason=reason,
                        status="pending",
                    ))
                    if kp_id:
                        suggested += 1

                task.progress = min(int((i + len(batch)) / total * 100), 99)
                await db.commit()

            # 全部批次 LLM 都失败 → 任务失败，避免看起来“成功但全无建议”
            if batches_ok == 0 and llm_errors:
                task.status = "failed"
                task.progress = 100
                task.completed_at = datetime.now()
                task.error_message = (
                    "大模型调用失败（与知识抽取共用系统配置）。"
                    + llm_errors[0]
                )[:1000]
                task.result_summary = {
                    "total_questions": total,
                    "suggested": 0,
                    "llm_errors": llm_errors[:5],
                }
                await db.commit()
                logger.error(f"KP关联任务{task_id}失败: {task.error_message}")
                return

            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.now()
            task.result_summary = {
                "total_questions": total,
                "suggested": suggested,
                "batches_ok": batches_ok,
            }
            if suggested == 0:
                task.error_message = "任务完成但未产出有效知识点建议，请检查模型返回或手动改选"
            await db.commit()
            logger.info(f"KP关联任务{task_id}完成: {suggested}/{total}")

        except Exception as e:
            logger.error(f"KP关联任务失败: {e}", exc_info=True)
            async with async_session() as db2:
                result = await db2.execute(select(KpLinkTask).where(KpLinkTask.id == task_id))
                task = result.scalar_one_or_none()
                if task:
                    task.status = "failed"
                    task.error_message = str(e)[:1000]
                    await db2.commit()
