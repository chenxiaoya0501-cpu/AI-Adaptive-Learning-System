from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.analytics_service import (
    diagnostic_priority_analysis,
    list_students,
    knowledge_options,
    marginal_value_analysis,
    population_analysis,
    student_analysis,
    targeted_practice_analysis,
)

router = APIRouter()


@router.get("/population")
async def get_population_analysis(
    domain: Optional[str] = Query(default=None),
    category_1: Optional[str] = Query(default=None),
    category_2: Optional[str] = Query(default=None),
    kp_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await population_analysis(db, domain, category_1, category_2, kp_id)


@router.get("/knowledge-options")
async def get_knowledge_options(db: AsyncSession = Depends(get_db)):
    return await knowledge_options(db)


@router.get("/students")
async def get_students(db: AsyncSession = Depends(get_db)):
    return await list_students(db)


@router.get("/marginal-value")
async def get_marginal_value_analysis(
    user_id: int = Query(..., gt=0),
    domain: Optional[str] = Query(default=None),
    category_1: Optional[str] = Query(default=None),
    category_2: Optional[str] = Query(default=None),
    kp_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    result = await marginal_value_analysis(
        db, user_id, domain, category_1, category_2, kp_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return result


@router.get("/diagnostic-priority")
async def get_diagnostic_priority_analysis(
    user_id: int = Query(..., gt=0),
    domain: Optional[str] = Query(default=None),
    category_1: Optional[str] = Query(default=None),
    category_2: Optional[str] = Query(default=None),
    kp_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    result = await diagnostic_priority_analysis(
        db, user_id, domain, category_1, category_2, kp_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="学生或学习目标不存在")
    return result


@router.get("/targeted-practice")
async def get_targeted_practice_analysis(
    user_id: int = Query(..., gt=0),
    domain: Optional[str] = Query(default=None),
    category_1: Optional[str] = Query(default=None),
    category_2: Optional[str] = Query(default=None),
    kp_id: Optional[str] = Query(default=None),
    question_count: int = Query(default=20, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    result = await targeted_practice_analysis(
        db,
        user_id,
        domain,
        category_1,
        category_2,
        kp_id,
        question_count,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="学生或学习目标不存在")
    return result


@router.get("/students/{user_id}")
async def get_student_analysis(
    user_id: int,
    domain: Optional[str] = Query(default=None),
    category_1: Optional[str] = Query(default=None),
    category_2: Optional[str] = Query(default=None),
    kp_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    result = await student_analysis(
        db, user_id, domain, category_1, category_2, kp_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="学生不存在")
    return result
