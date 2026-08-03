"""题目能力维度 AI 批量标注（建议待确认后落库）。"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select

from app.database import async_session
from app.models.question import AbilityLabelSuggestion, AbilityLabelTask, Question
from app.models.system import SystemConfig
from app.schemas.question import ABILITY_DIMENSIONS
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)

IMG_RE = re.compile(r"\[IMG:[^\]]+\]")

ABILITY_LABEL_PROMPT = """你是初中数学教研助手。请根据题目内容，从下列能力维度中为每道题选出「一个」最主要考察的能力维度。

可选能力维度（必须原样输出其一）：
{dimensions}

判定参考：
- 计算：以数值运算、式子化简、求解数值结果为主
- 理解：以概念理解、法则含义、题意辨析为主
- 信息提取：从图表/文字中读取关键数据或条件为主
- 推理：逻辑推导、证明思路、关系判断为主
- 空间：图形想象、几何直观、空间关系为主
- 记忆：以公式/定义/事实回忆为主（少见，慎用）

请严格输出 JSON 对象：
{{
  "matches": [
    {{
      "question_index": 0,
      "ability_dimension": "必须是上述六个之一",
      "confidence": "high/medium/low",
      "reason": "一句话理由"
    }}
  ]
}}

规则：
1. ability_dimension 必须是六个选项之一，禁止编造
2. 每道题只选一个主维度
3. matches 数量必须与输入题目数量一致，question_index 从 0 开始
4. 不确定时用 medium 或 low"""


def run_ability_label_task(task_id: int) -> None:
    asyncio.run(_run_ability_label_async(task_id))


def _clean_question_text(text: str, limit: int = 400) -> str:
    cleaned = IMG_RE.sub(" ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def _normalize_dimension(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in ABILITY_DIMENSIONS:
        return text
    # 兼容英文/别名
    alias = {
        "calculation": "计算",
        "compute": "计算",
        "understanding": "理解",
        "comprehension": "理解",
        "information": "信息提取",
        "info": "信息提取",
        "extraction": "信息提取",
        "reasoning": "推理",
        "inference": "推理",
        "spatial": "空间",
        "space": "空间",
        "memory": "记忆",
        "memorization": "记忆",
    }
    low = text.lower()
    if low in alias:
        return alias[low]
    for d in ABILITY_DIMENSIONS:
        if d in text:
            return d
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
        if "ability_dimension" in data or "question_index" in data:
            return [data]
    return []


async def _run_ability_label_async(task_id: int) -> None:
    async with async_session() as db:
        try:
            task = (
                await db.execute(select(AbilityLabelTask).where(AbilityLabelTask.id == task_id))
            ).scalar_one_or_none()
            if not task:
                return

            task.status = "running"
            task.started_at = datetime.now()
            task.error_message = None
            task.progress = 0
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

            q_query = select(Question)
            if scope.get("question_ids"):
                q_query = q_query.where(Question.id.in_(scope["question_ids"]))
            else:
                if scope.get("exam_paper_id"):
                    q_query = q_query.where(Question.exam_paper_id == scope["exam_paper_id"])
                if scope.get("bank_type"):
                    q_query = q_query.where(Question.bank_type == scope["bank_type"])
            if scope.get("only_unlabeled"):
                q_query = q_query.where(
                    or_(Question.ability_dimension.is_(None), Question.ability_dimension == "")
                )

            questions = list(
                (await db.execute(q_query.order_by(Question.id))).scalars().all()
            )
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
            dims_text = "、".join(ABILITY_DIMENSIONS)
            system_prompt = ABILITY_LABEL_PROMPT.format(dimensions=dims_text)

            for i in range(0, total, batch_size):
                batch = questions[i : i + batch_size]
                lines = []
                for idx, q in enumerate(batch):
                    content = _clean_question_text(q.content or "", 400)
                    opts = ""
                    if q.options and isinstance(q.options, dict):
                        opts = " ".join([f"{k}.{v}" for k, v in q.options.items()])
                        opts = _clean_question_text(opts, 160)
                    lines.append(f"题目{idx}: {content}\n选项: {opts}")

                user_prompt = f"请为以下{len(batch)}道题标注能力维度：\n\n" + "\n\n".join(lines)

                data = None
                try:
                    data = await llm.extract_json(system_prompt, user_prompt)
                except Exception as e:
                    err = str(e)
                    logger.warning("能力维度标注LLM失败 task=%s batch=%s: %s", task_id, i, err)
                    llm_errors.append(err[:300])
                    for q in batch:
                        # 作废同题旧 pending
                        old_sugs = (
                            await db.execute(
                                select(AbilityLabelSuggestion).where(
                                    AbilityLabelSuggestion.question_id == q.id,
                                    AbilityLabelSuggestion.status == "pending",
                                )
                            )
                        ).scalars().all()
                        for s in old_sugs:
                            s.status = "rejected"
                        db.add(
                            AbilityLabelSuggestion(
                                task_id=task_id,
                                question_id=q.id,
                                suggested_dimension=None,
                                confidence="low",
                                reason=f"大模型调用失败: {err[:200]}",
                                status="pending",
                            )
                        )
                    task.progress = min(int((i + len(batch)) / total * 100), 99)
                    await db.commit()
                    continue

                matches = _parse_matches(data)
                if not matches:
                    logger.warning(
                        "能力维度标注返回空 matches task=%s batch=%s data=%s",
                        task_id,
                        i,
                        data,
                    )
                    llm_errors.append("模型返回中无 matches")
                else:
                    batches_ok += 1

                match_by_idx: Dict[int, dict] = {}
                for m in matches:
                    try:
                        match_by_idx[int(m.get("question_index", -1))] = m
                    except Exception:
                        continue
                if not match_by_idx and matches:
                    for idx, m in enumerate(matches[: len(batch)]):
                        match_by_idx[idx] = m

                for idx, q in enumerate(batch):
                    m = match_by_idx.get(idx, {})
                    dim = _normalize_dimension(
                        m.get("ability_dimension")
                        or m.get("dimension")
                        or m.get("ability")
                    )
                    conf = str(m.get("confidence") or "medium").lower()
                    if conf not in ("high", "medium", "low"):
                        conf = "medium"
                    reason = str(m.get("reason") or "")[:500]
                    if not dim and not reason:
                        reason = "未能匹配到合法能力维度"

                    # 直接写回题目的能力维度字段（覆盖已有）
                    if dim:
                        q.ability_dimension = dim
                        suggested += 1

                    # 记录建议供审计
                    db.add(
                        AbilityLabelSuggestion(
                            task_id=task_id,
                            question_id=q.id,
                            suggested_dimension=dim,
                            confidence=conf,
                            reason=reason,
                            status="accepted" if dim else "failed",
                            final_dimension=dim,
                        )
                    )

                task.progress = min(int((i + len(batch)) / total * 100), 99)
                await db.commit()

            if batches_ok == 0 and llm_errors:
                task.status = "failed"
                task.progress = 100
                task.completed_at = datetime.now()
                task.error_message = (
                    "大模型调用失败（与知识抽取共用系统配置）。" + llm_errors[0]
                )[:1000]
                task.result_summary = {
                    "total_questions": total,
                    "suggested": 0,
                    "llm_errors": llm_errors[:5],
                }
                await db.commit()
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
                task.error_message = "任务完成但未产出有效能力维度建议，请检查模型返回或手动改选"
            await db.commit()
            logger.info("能力维度标注任务%s完成: %s/%s", task_id, suggested, total)

        except Exception as e:
            logger.exception("能力维度标注任务失败 task=%s", task_id)
            task = (
                await db.execute(select(AbilityLabelTask).where(AbilityLabelTask.id == task_id))
            ).scalar_one_or_none()
            if task:
                task.status = "failed"
                task.error_message = str(e)[:1000]
                task.completed_at = datetime.now()
                await db.commit()
