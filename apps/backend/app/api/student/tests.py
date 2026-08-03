from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_student
from app.database import get_db
from app.models.user import User
from app.schemas.student.test import (
    AnswerPayload,
    AnswerPublic,
    AiExerciseAnswerRequest,
    AiExercisePublic,
    AiExerciseResult,
    AssemblePreview,
    AssembleRequest,
    PaperResultDetail,
    SaveProgressPayload,
    SubmitResult,
    TakingSession,
    TestPaperDetail,
    TestPaperSummary,
    WrongQuestionList,
    WrongQuestionGenerateRequest,
)
from app.services.learning import (
    assembly,
    exam_taking,
    wrong_question_practice,
    wrong_questions,
)

router = APIRouter(prefix="/tests")


@router.get("/preview", response_model=AssemblePreview)
async def preview_assemble(
    goal_id: int = Query(..., description="学习目标 ID"),
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """组卷前预览：目标摘要 + 默认平均模板题型结构。"""
    return await assembly.preview_assemble(db, user.id, goal_id)


@router.post("/assemble", response_model=TestPaperDetail)
async def assemble_test(
    body: AssembleRequest,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """
    按平均模板 π(k,t) 在已学知识点 L 上动态组卷。
    bank_type=real 从真题库抽题；mock 从模拟题库抽题。
    """
    return await assembly.assemble_paper(
        db,
        user_id=user.id,
        goal_id=body.goal_id,
        bank_type=body.bank_type,
        lambda_value=body.lambda_value,
        template_id=body.template_id,
        paper_kind=body.paper_kind,
    )


@router.get("", response_model=List[TestPaperSummary])
async def list_tests(
    goal_id: Optional[int] = Query(None),
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await assembly.list_papers(db, user.id, goal_id=goal_id)


@router.get("/wrong-questions", response_model=WrongQuestionList)
async def get_wrong_questions(
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """汇总当前学生在测评与课程练习中的全部错误作答。"""
    return await wrong_questions.list_wrong_questions(db, user.id)


@router.post("/wrong-questions/generate", response_model=AiExercisePublic)
async def generate_wrong_question_exercise(
    body: WrongQuestionGenerateRequest,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """基于当前学生的一道错题生成同类题或加深题。"""
    return await wrong_question_practice.generate(db, user.id, body)


@router.post(
    "/wrong-questions/exercises/{exercise_id}/submit",
    response_model=AiExerciseResult,
)
async def submit_wrong_question_exercise(
    exercise_id: int,
    body: AiExerciseAnswerRequest,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """提交 AI 错题练习并返回批改结果与解析。"""
    return await wrong_question_practice.submit(
        db, user.id, exercise_id, body.answer
    )


@router.get("/{paper_id}", response_model=TestPaperDetail)
async def get_test(
    paper_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    return await assembly.get_paper_detail(db, user.id, paper_id)


@router.delete("/{paper_id}")
async def delete_test(
    paper_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """删除本人的组卷记录（含题目快照）。"""
    await assembly.delete_paper(db, user.id, paper_id)
    return {"ok": True}


@router.post("/{paper_id}/start", response_model=TakingSession)
async def start_test(
    paper_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """开始测试：assembled → in_progress，返回答题会话。"""
    return await exam_taking.start_taking(db, user.id, paper_id)


@router.get("/{paper_id}/taking", response_model=TakingSession)
async def get_taking_session(
    paper_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """拉取答题会话（题干 + 已保存作答）。"""
    return await exam_taking.get_taking(db, user.id, paper_id)


@router.put("/{paper_id}/answers/{question_id}", response_model=AnswerPublic)
async def upsert_answer(
    paper_id: int,
    question_id: int,
    body: AnswerPayload,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """暂存单题作答。"""
    return await exam_taking.save_answer(db, user.id, paper_id, question_id, body)


@router.post("/{paper_id}/save", response_model=TakingSession)
async def save_progress(
    paper_id: int,
    body: SaveProgressPayload,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """批量保存当前作答进度（测试中可稍后继续）。"""
    return await exam_taking.save_progress(db, user.id, paper_id, body.answers)


@router.post("/{paper_id}/submit", response_model=SubmitResult)
async def submit_test(
    paper_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """交卷 → 自动批改 → 写入目标结果记录。"""
    return await exam_taking.submit_paper(db, user.id, paper_id)


@router.get("/{paper_id}/result", response_model=PaperResultDetail)
async def get_test_result(
    paper_id: int,
    user: User = Depends(get_current_student),
    db: AsyncSession = Depends(get_db),
):
    """查看批改结果（含对错与得分）。"""
    return await exam_taking.get_paper_result(db, user.id, paper_id)
