from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class SystemConfigResponse(BaseModel):
    id: int
    key: str
    value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SystemConfigUpdate(BaseModel):
    value: str
    description: Optional[str] = None


class LLMConfigResponse(BaseModel):
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int


class UploadedFileResponse(BaseModel):
    id: int
    filename: str
    original_name: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    grade: Optional[str] = None
    semester: Optional[str] = None
    status: str
    parse_result: Optional[Any] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ExtractionTaskCreate(BaseModel):
    task_type: str
    source_file_ids: Optional[list] = None
    config: Optional[dict] = None


class ExtractionTaskResponse(BaseModel):
    id: int
    task_type: str
    source_file_ids: Optional[str] = None
    source_file_names: Optional[str] = None  # 展示用：源文件名称，逗号分隔
    status: str
    progress: int
    result_summary: Optional[Any] = None
    error_message: Optional[str] = None
    config: Optional[Any] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True
