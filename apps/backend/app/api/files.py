import os
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.system import UploadedFile as UploadedFileModel
from app.schemas.system import UploadedFileResponse
from app.config import settings

router = APIRouter()


@router.post("/upload", response_model=UploadedFileResponse)
async def upload_file(
    file: UploadFile = File(...),
    file_type: str = Form(..., description="curriculum 或 textbook"),
    grade: str = Form(None, description="年级(教材用)"),
    semester: str = Form(None, description="学期(教材用)"),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持PDF文件")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename)[1]
    saved_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, saved_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    record = UploadedFileModel(
        filename=saved_name,
        original_name=file.filename,
        file_type=file_type,
        file_size=len(content),
        grade=grade,
        semester=semester,
        status="uploaded",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return UploadedFileResponse.model_validate(record, from_attributes=True)


@router.get("/list", response_model=List[UploadedFileResponse])
async def list_files(
    file_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(UploadedFileModel).order_by(UploadedFileModel.created_at.desc())
    if file_type:
        query = query.where(UploadedFileModel.file_type == file_type)
    result = await db.execute(query)
    files = result.scalars().all()
    return [UploadedFileResponse.model_validate(f, from_attributes=True) for f in files]


@router.put("/{file_id}/type", response_model=UploadedFileResponse)
async def update_file_type(
    file_id: int,
    file_type: str = Form(..., description="curriculum 或 textbook"),
    db: AsyncSession = Depends(get_db),
):
    """修正资料类型（课标/教材），便于章节目录等任务正确识别"""
    if file_type not in ("curriculum", "textbook"):
        raise HTTPException(status_code=400, detail="file_type 只能是 curriculum 或 textbook")
    result = await db.execute(select(UploadedFileModel).where(UploadedFileModel.id == file_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")
    record.file_type = file_type
    await db.commit()
    await db.refresh(record)
    return UploadedFileResponse.model_validate(record, from_attributes=True)


@router.delete("/{file_id}")
async def delete_file(file_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UploadedFileModel).where(UploadedFileModel.id == file_id))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = os.path.join(settings.UPLOAD_DIR, record.filename)
    if os.path.exists(file_path):
        os.remove(file_path)

    await db.delete(record)
    await db.commit()
    return {"message": "已删除"}
