"""课程与资源管理 API"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------- Schemas ----------

class ExplanationGenerateRequest(BaseModel):
    kp_id: str = Field(..., description="知识点ID")
    difficulty_level: str = Field(default="basic", description="讲解深度: basic/intermediate/advanced")


class ExplanationSaveRequest(BaseModel):
    kp_id: str
    title: str = ""
    summary: str = ""
    content: str = ""
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    key_points: list = Field(default_factory=list)
    examples: list = Field(default_factory=list)
    common_mistakes: list = Field(default_factory=list)
    difficulty_level: str = "basic"


# ---------- Endpoints ----------

@router.post("/ai-explanation/generate")
async def generate_explanation(
    data: ExplanationGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """调用 LLM 为指定知识点生成讲解内容（不入库，返回给前端审核）"""
    from app.services.ai_explanation_service import generate_explanation as gen_exp

    try:
        result = await gen_exp(
            db=db,
            kp_id=data.kp_id,
            difficulty_level=data.difficulty_level,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai-explanation/save")
async def save_explanation(
    data: ExplanationSaveRequest,
    db: AsyncSession = Depends(get_db),
):
    """保存讲解内容到数据库"""
    from app.services.ai_explanation_service import save_explanation as save_exp

    try:
        exp = await save_exp(db=db, data=data.dict())
        return {"message": "保存成功", "id": exp.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-explanation/list")
async def list_explanations(
    kp_id: str,
    page: int = 1,
    page_size: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """获取知识点的讲解列表"""
    from app.services.ai_explanation_service import list_explanations as list_exp

    result = await list_exp(db=db, kp_id=kp_id, page=page, page_size=page_size)
    return result


@router.get("/ai-explanation/{exp_id}")
async def get_explanation(
    exp_id: int,
    db: AsyncSession = Depends(get_db),
):
    """获取单个讲解详情"""
    from app.services.ai_explanation_service import get_explanation as get_exp

    result = await get_exp(db=db, exp_id=exp_id)
    if not result:
        raise HTTPException(status_code=404, detail="讲解内容不存在")
    return result


@router.delete("/ai-explanation/{exp_id}")
async def delete_explanation(
    exp_id: int,
    db: AsyncSession = Depends(get_db),
):
    """删除讲解内容"""
    from app.services.ai_explanation_service import delete_explanation as del_exp

    ok = await del_exp(db=db, exp_id=exp_id)
    if not ok:
        raise HTTPException(status_code=404, detail="讲解内容不存在")
    return {"message": "删除成功"}
