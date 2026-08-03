"""测试答题：开始作答 / 暂存 / 交卷 + 自动批改"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.question import ExamPaper, Question
from app.models.student.goal import LearningGoal
from app.models.student.test_paper import TestAnswer, TestQuestion
from app.schemas.student.test import (
    AnswerPayload,
    AnswerPublic,
    PaperResultDetail,
    ProgressAnswerItem,
    QuestionResultItem,
    SubmitResult,
    TakingSession,
)
from app.services.learning import assembly, grading, result_records, assessment

EDITABLE_STATUSES = {"assembled", "in_progress"}
LOCKED_STATUSES = {"submitted", "grading", "graded"}


def _has_response(ans: Optional[TestAnswer]) -> bool:
    if ans is None:
        return False
    if ans.selected_option and str(ans.selected_option).strip():
        return True
    if ans.answer_text and str(ans.answer_text).strip():
        return True
    if ans.image_urls:
        return True
    return False


def to_answer_public(ans: TestAnswer, *, reveal_grade: bool = False) -> AnswerPublic:
    return AnswerPublic(
        test_question_id=ans.test_question_id,
        selected_option=ans.selected_option,
        answer_text=ans.answer_text,
        image_urls=list(ans.image_urls or []) if ans.image_urls else None,
        is_marked_uncertain=bool(ans.is_marked_uncertain),
        is_correct=ans.is_correct if reveal_grade else None,
        score_got=ans.score_got if reveal_grade else None,
    )


async def _get_questions(db: AsyncSession, paper_id: int) -> List[TestQuestion]:
    return list(
        (
            await db.execute(
                select(TestQuestion)
                .where(TestQuestion.test_paper_id == paper_id)
                .order_by(TestQuestion.seq.asc())
            )
        )
        .scalars()
        .all()
    )


async def _get_answers_map(db: AsyncSession, paper_id: int) -> Dict[int, TestAnswer]:
    rows = (
        await db.execute(select(TestAnswer).where(TestAnswer.test_paper_id == paper_id))
    ).scalars().all()
    # 历史脏数据可能一题多条；优先保留有作答 / id 更大的一条
    out: Dict[int, TestAnswer] = {}
    for a in rows:
        prev = out.get(a.test_question_id)
        if prev is None:
            out[a.test_question_id] = a
            continue
        prefer_new = _has_response(a) and not _has_response(prev)
        prefer_new = prefer_new or (
            _has_response(a) == _has_response(prev) and (a.id or 0) > (prev.id or 0)
        )
        if prefer_new:
            out[a.test_question_id] = a
    return out


async def _get_or_create_answer(
    db: AsyncSession, paper_id: int, question_id: int
) -> TestAnswer:
    rows = list(
        (
            await db.execute(
                select(TestAnswer).where(
                    TestAnswer.test_paper_id == paper_id,
                    TestAnswer.test_question_id == question_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        ans = TestAnswer(test_paper_id=paper_id, test_question_id=question_id)
        db.add(ans)
        return ans
    rows.sort(
        key=lambda a: (1 if _has_response(a) else 0, a.id or 0),
        reverse=True,
    )
    keep = rows[0]
    for extra in rows[1:]:
        await db.delete(extra)
    return keep


async def start_taking(db: AsyncSession, user_id: int, paper_id: int) -> TakingSession:
    paper = await assembly.get_owned_paper(db, paper_id, user_id)
    if paper.status in LOCKED_STATUSES:
        return await get_taking(db, user_id, paper_id)
    if paper.status == "assembled":
        paper.status = "in_progress"
        await db.commit()
        await db.refresh(paper)
    return await get_taking(db, user_id, paper_id)


async def get_taking(db: AsyncSession, user_id: int, paper_id: int) -> TakingSession:
    detail = await assembly.get_paper_detail(db, user_id, paper_id)
    answers_map = await _get_answers_map(db, paper_id)
    reveal = detail.status in LOCKED_STATUSES
    answers = [to_answer_public(a, reveal_grade=reveal) for a in answers_map.values()]
    answered = sum(1 for a in answers_map.values() if _has_response(a))
    return TakingSession(
        paper=detail,
        answers=answers,
        answered_count=answered,
        total_count=len(detail.questions),
        readonly=detail.status in LOCKED_STATUSES,
    )


async def save_answer(
    db: AsyncSession,
    user_id: int,
    paper_id: int,
    question_id: int,
    payload: AnswerPayload,
) -> AnswerPublic:
    paper = await assembly.get_owned_paper(db, paper_id, user_id)
    if paper.status in LOCKED_STATUSES:
        raise HTTPException(status_code=400, detail="已交卷，不可再修改答案")
    if paper.status == "assembled":
        paper.status = "in_progress"

    q = (
        await db.execute(
            select(TestQuestion).where(
                TestQuestion.id == question_id,
                TestQuestion.test_paper_id == paper_id,
            )
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="题目不存在")

    ans = await _get_or_create_answer(db, paper_id, question_id)
    _apply_answer_fields(q, ans, payload)

    await db.commit()
    await db.refresh(ans)
    return to_answer_public(ans)


def _apply_answer_fields(
    q: TestQuestion, ans: TestAnswer, payload: AnswerPayload
) -> None:
    if q.question_type == "choice":
        ans.selected_option = (
            grading.normalize_choice(payload.selected_option)
            if payload.selected_option
            else None
        )
        ans.answer_text = None
    else:
        ans.selected_option = None
        ans.answer_text = (payload.answer_text or "").strip() or None

    ans.image_urls = payload.image_urls
    ans.is_marked_uncertain = bool(payload.is_marked_uncertain)
    ans.is_correct = None
    ans.score_got = None


async def save_progress(
    db: AsyncSession,
    user_id: int,
    paper_id: int,
    items: List[ProgressAnswerItem],
) -> TakingSession:
    """一次事务批量暂存，供答题页「保存」使用。"""
    paper = await assembly.get_owned_paper(db, paper_id, user_id)
    if paper.status in LOCKED_STATUSES:
        raise HTTPException(status_code=400, detail="已交卷，不可再修改答案")
    if paper.status == "assembled":
        paper.status = "in_progress"

    questions = await _get_questions(db, paper_id)
    q_map = {q.id: q for q in questions}

    for item in items:
        qid = int(item.test_question_id)
        q = q_map.get(qid)
        if q is None:
            raise HTTPException(status_code=404, detail=f"题目不存在：{qid}")
        ans = await _get_or_create_answer(db, paper_id, qid)
        _apply_answer_fields(q, ans, item)

    await db.flush()
    answers_map = await _get_answers_map(db, paper_id)
    answered = sum(1 for a in answers_map.values() if _has_response(a))
    await result_records.upsert_taking_record(
        db,
        goal_id=paper.goal_id,
        user_id=user_id,
        test_paper_id=paper.id,
        paper_title=paper.title or f"试卷 #{paper.id}",
        answered_count=answered,
        total_count=len(questions),
        total_score=float(paper.total_score or 0),
    )
    await db.commit()
    return await get_taking(db, user_id, paper_id)


async def submit_paper(db: AsyncSession, user_id: int, paper_id: int) -> SubmitResult:
    paper = await assembly.get_owned_paper(db, paper_id, user_id)
    if paper.status in LOCKED_STATUSES:
        raise HTTPException(status_code=400, detail="该卷已交过，请勿重复交卷")

    questions = await _get_questions(db, paper_id)
    answers_map = await _get_answers_map(db, paper_id)
    answered = sum(1 for a in answers_map.values() if _has_response(a))
    total_score = float(paper.total_score or 0)
    paper_title = paper.title or f"试卷 #{paper.id}"

    # 交卷：清除「答题中」，写入「批改完成」
    paper.status = "submitted"
    await db.flush()
    paper.status = "grading"
    await db.flush()
    stats = grading.grade_paper(questions, answers_map)
    paper.status = "graded"
    paper.earned_score = stats["earned_score"]

    goal = (
        await db.execute(
            select(LearningGoal).where(
                LearningGoal.id == paper.goal_id,
                LearningGoal.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if goal is not None:
        goal.mastery_status = "assessed"
        goal.current_score_estimate = stats["earned_score"]
        # 新测评会改变认知快照；若已有路径，应提示基于最新状态生成新版本。
        goal.needs_replan = True

    await result_records.clear_taking_for_paper(
        db, user_id=user_id, test_paper_id=paper.id
    )
    await result_records.add_record(
        db,
        goal_id=paper.goal_id,
        user_id=user_id,
        test_paper_id=paper.id,
        event_type="graded",
        title="批改完成",
        summary=(
            f"「{paper_title}」已批改："
            f"得分 {stats['earned_score']}/{total_score}，"
            f"答对 {int(stats['correct_count'])}/{int(stats['total_count'])} 题。"
        ),
        earned_score=stats["earned_score"],
        total_score=total_score,
        correct_count=int(stats["correct_count"]),
        total_count=int(stats["total_count"]),
        meta={"graded_count": int(stats["graded_count"])},
    )

    # 批改后能力评估（规则必出；有 LLM Key 则润色）
    try:
        await assessment.generate_and_store(
            db,
            paper=paper,
            questions=questions,
            answers_map=answers_map,
            use_llm=True,
        )
    except Exception:
        # 评估失败不影响交卷成功
        pass

    await db.commit()

    return SubmitResult(
        paper_id=paper.id,
        goal_id=paper.goal_id,
        status=paper.status,
        answered_count=answered,
        total_count=len(questions),
        correct_count=int(stats["correct_count"]),
        earned_score=stats["earned_score"],
        total_score=total_score,
        graded_count=int(stats["graded_count"]),
        assessment_status=paper.assessment_status,
        message=(
            f"交卷成功并已自动批改：{stats['earned_score']}/{total_score} 分，"
            f"答对 {int(stats['correct_count'])}/{len(questions)} 题。"
        ),
    )


_GRADING_NOTE = {
    "empty": "未作答",
    "no_key": "题库未录入文本答案，无法自动判分",
    "needs_review": "参考答案以公式图片为主或缺失文本，当前仅展示参考答案，不计分",
    "choice_rule": "选择题选项比对",
    "fill_rule": "填空文本比对",
    "fill_alt": "填空多答案比对",
    "text_exact": "文本完全一致",
    "text_contain_key": "作答包含标准答案文本",
    "text_rule": "文本比对未通过",
}


def _format_source_label(
    exam_paper: Optional[ExamPaper],
    question_number: Optional[int],
    question_source: Optional[str],
) -> Optional[str]:
    if exam_paper and (exam_paper.source or "").strip():
        base = exam_paper.source.strip()
    elif exam_paper:
        bits: List[str] = []
        if exam_paper.year:
            bits.append(f"{exam_paper.year}年")
        if exam_paper.region:
            bits.append(str(exam_paper.region))
        bits.append("模拟题" if exam_paper.paper_type == "mock" else "真题")
        if exam_paper.title:
            bits.append(str(exam_paper.title))
        base = " · ".join(bits)
    elif question_source:
        base = question_source.strip()
    else:
        base = ""
    if question_number:
        suffix = f"第{question_number}题"
        return f"{base} · {suffix}" if base else suffix
    return base or None


async def _load_source_maps(
    db: AsyncSession, questions: List[TestQuestion]
):
    q_ids = [q.source_question_id for q in questions if q.source_question_id]
    p_ids = list(
        {
            q.source_exam_paper_id
            for q in questions
            if getattr(q, "source_exam_paper_id", None)
        }
    )
    q_map: Dict[int, Question] = {}
    p_map: Dict[int, ExamPaper] = {}
    if q_ids:
        rows = (
            await db.execute(select(Question).where(Question.id.in_(list(set(q_ids)))))
        ).scalars().all()
        q_map = {r.id: r for r in rows}
        for r in rows:
            if r.exam_paper_id and r.exam_paper_id not in p_ids:
                p_ids.append(r.exam_paper_id)
    if p_ids:
        rows = (
            await db.execute(select(ExamPaper).where(ExamPaper.id.in_(list(set(p_ids)))))
        ).scalars().all()
        p_map = {r.id: r for r in rows}
    return q_map, p_map


async def get_paper_result(
    db: AsyncSession, user_id: int, paper_id: int
) -> PaperResultDetail:
    paper = await assembly.get_owned_paper(db, paper_id, user_id)
    if paper.status not in LOCKED_STATUSES:
        raise HTTPException(status_code=400, detail="试卷尚未交卷，暂无批改结果")

    questions = await _get_questions(db, paper_id)
    answers_map = await _get_answers_map(db, paper_id)
    # 用最新规则重判，修正历史误判（如图片尺寸数字误匹配）
    stats = grading.grade_paper(questions, answers_map)
    paper.earned_score = stats["earned_score"]
    paper.status = "graded"
    await db.commit()

    paper_ids = await assembly.resolve_source_exam_paper_ids(db, questions)
    src_q_map, src_p_map = await _load_source_maps(db, questions)
    items: List[QuestionResultItem] = []
    answered = 0
    for q in questions:
        ans = answers_map.get(q.id)
        if _has_response(ans):
            answered += 1
        _ok, _got, method = grading.grade_one(q, ans)
        src_paper_id = paper_ids.get(q.id) or getattr(q, "source_exam_paper_id", None)
        src_q = src_q_map.get(q.source_question_id) if q.source_question_id else None
        if src_paper_id is None and src_q is not None:
            src_paper_id = src_q.exam_paper_id
        exam_paper = src_p_map.get(src_paper_id) if src_paper_id else None
        qnum = src_q.question_number if src_q else None
        q_source = (src_q.source if src_q else None) or None

        content_display = assembly.expand_img_placeholders(q.content, src_paper_id)
        options_display = assembly.expand_options_images(q.options, src_paper_id)
        analysis_raw = q.analysis or (src_q.analysis if src_q else None)
        analysis_display = (
            assembly.expand_img_placeholders(analysis_raw, src_paper_id)
            if analysis_raw
            else None
        )
        correct_display = (
            assembly.expand_img_placeholders(q.answer, src_paper_id) if q.answer else None
        )

        items.append(
            QuestionResultItem(
                question_id=q.id,
                seq=q.seq,
                question_type=q.question_type,
                score=float(q.score or 0),
                is_correct=ans.is_correct if ans else False,
                score_got=ans.score_got if ans else 0.0,
                selected_option=ans.selected_option if ans else None,
                answer_text=ans.answer_text if ans else None,
                correct_answer=correct_display,
                source_exam_paper_id=src_paper_id,
                grading_note=_GRADING_NOTE.get(method, method),
                content=content_display,
                options=options_display,
                analysis=analysis_display,
                source_label=_format_source_label(exam_paper, qnum, q_source),
                source_year=exam_paper.year if exam_paper else None,
                source_region=exam_paper.region if exam_paper else None,
                source_question_number=qnum,
                ability_dimension=getattr(q, "ability_dimension", None)
                or (src_q.ability_dimension if src_q else None),
                difficulty=q.difficulty,
                primary_kp_id=q.primary_kp_id,
            )
        )

    # 旧卷无评估时补生成一次（规则+可选 LLM）
    if not paper.assessment_json or paper.assessment_status != "ready":
        try:
            await assessment.generate_and_store(
                db,
                paper=paper,
                questions=questions,
                answers_map=answers_map,
                use_llm=True,
            )
            await db.commit()
            await db.refresh(paper)
        except Exception:
            await db.rollback()

    enriched_assessment = await assessment.enrich_knowledge_labels(
        db, paper.assessment_json
    )
    if enriched_assessment != paper.assessment_json:
        paper.assessment_json = enriched_assessment
        await db.commit()

    return PaperResultDetail(
        paper_id=paper.id,
        goal_id=paper.goal_id,
        title=paper.title,
        status=paper.status,
        earned_score=paper.earned_score,
        total_score=float(paper.total_score or 0),
        answered_count=answered,
        correct_count=int(stats["correct_count"]),
        total_count=len(questions),
        items=items,
        assessment_status=paper.assessment_status,
        assessment=enriched_assessment,
    )


async def delete_answers_for_paper(db: AsyncSession, paper_id: int) -> None:
    await db.execute(delete(TestAnswer).where(TestAnswer.test_paper_id == paper_id))
