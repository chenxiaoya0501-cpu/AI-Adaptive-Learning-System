"""图片答案转文本任务：只生成待确认建议，不直接改写题目答案。"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import or_, select

from app.database import async_session
from app.models.question import AnswerRewriteSuggestion, AnswerRewriteTask, Question
from app.services.answer_image_text_service import rewrite_answer_text
from app.services.pdf_parser import _get_easyocr_reader

logger = logging.getLogger(__name__)

_RADICAL_TYPO = re.compile(r"(?<![A-Za-z])[Vv](?=\d)|(?<=\d)[Vv](?=\d)")


def run_answer_rewrite_task(task_id: int) -> None:
    asyncio.run(_run_answer_rewrite_async(task_id))


def _conf_label(stats: Dict[str, Any]) -> str:
    details = stats.get("details") or []
    confs = [float(d.get("conf") or 0) for d in details if d.get("ok")]
    if not confs:
        return "medium" if stats.get("text_fixed") else "low"
    avg = sum(confs) / len(confs)
    if avg >= 0.75:
        return "high"
    if avg >= 0.45:
        return "medium"
    return "low"


async def _run_answer_rewrite_async(task_id: int) -> None:
    async with async_session() as db:
        task = (
            await db.execute(select(AnswerRewriteTask).where(AnswerRewriteTask.id == task_id))
        ).scalar_one_or_none()
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        task.progress = 0
        await db.commit()

        scope = task.scope or {}
        question_ids = scope.get("question_ids")
        exam_paper_id = scope.get("exam_paper_id")
        bank_type = scope.get("bank_type")

        try:
            q = select(Question).where(
                Question.answer.isnot(None),
                or_(
                    Question.answer.contains("[IMG:"),
                    Question.answer.contains("V"),
                    Question.answer.contains("v"),
                ),
            )
            if question_ids:
                q = q.where(Question.id.in_(question_ids))
            if exam_paper_id is not None:
                q = q.where(Question.exam_paper_id == exam_paper_id)
            if bank_type:
                q = q.where(Question.bank_type == bank_type)

            rows = list((await db.execute(q)).scalars().all())
            rows = [
                r
                for r in rows
                if "[IMG:" in (r.answer or "") or _RADICAL_TYPO.search(r.answer or "")
            ]

            if any("[IMG:" in (r.answer or "") for r in rows):
                _get_easyocr_reader()

            suggested = 0
            skipped = 0
            failed_tokens = 0
            replaced_tokens = 0
            total = max(len(rows), 1)

            for idx, question in enumerate(rows):
                old = (question.answer or "").strip()
                new, st = rewrite_answer_text(old, question.exam_paper_id)
                replaced_tokens += st.get("replaced", 0)
                failed_tokens += st.get("failed", 0)
                if new != old:
                    # 同一题若已有 pending 建议，先作废
                    old_sugs = (
                        await db.execute(
                            select(AnswerRewriteSuggestion).where(
                                AnswerRewriteSuggestion.question_id == question.id,
                                AnswerRewriteSuggestion.status == "pending",
                            )
                        )
                    ).scalars().all()
                    for s in old_sugs:
                        s.status = "rejected"
                    db.add(
                        AnswerRewriteSuggestion(
                            task_id=task_id,
                            question_id=question.id,
                            original_answer=old,
                            suggested_answer=new,
                            confidence=_conf_label(st),
                            detail={
                                "replaced": st.get("replaced", 0),
                                "failed": st.get("failed", 0),
                                "details": (st.get("details") or [])[:10],
                            },
                            status="pending",
                        )
                    )
                    suggested += 1
                else:
                    skipped += 1

                task.progress = int((idx + 1) / total * 100)
                if (idx + 1) % 3 == 0:
                    await db.commit()

            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.utcnow()
            task.result_summary = {
                "scanned": len(rows),
                "suggested": suggested,
                "skipped": skipped,
                "replaced_tokens": replaced_tokens,
                "failed_tokens": failed_tokens,
            }
            if suggested == 0:
                task.error_message = "未产生可确认的转写建议（可能无图片答案，或识别后与原文相同）"
            await db.commit()
        except Exception as e:
            logger.exception("答案转写任务失败 task=%s", task_id)
            task.status = "failed"
            task.error_message = str(e)[:500]
            task.completed_at = datetime.utcnow()
            await db.commit()
