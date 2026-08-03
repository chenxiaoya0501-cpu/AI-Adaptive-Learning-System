from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TextbookChapterUpdate(BaseModel):
    title: Optional[str] = None
    sort_order: Optional[int] = None
    status: Optional[str] = None
    content_summary: Optional[str] = None


class TextbookChapterResponse(BaseModel):
    id: int
    uploaded_file_id: int
    subject: Optional[str] = None
    grade: Optional[str] = None
    semester: Optional[str] = None
    parent_id: Optional[int] = None
    level: str
    title: str
    sort_order: int = 0
    content_summary: Optional[str] = None
    status: str = "draft"
    kp_count: Optional[int] = 0
    children: Optional[List["TextbookChapterResponse"]] = None
    file_name: Optional[str] = None

    class Config:
        from_attributes = True


class TextbookTocTreeResponse(BaseModel):
    uploaded_file_id: int
    file_name: Optional[str] = None
    grade: Optional[str] = None
    semester: Optional[str] = None
    chapters: List[TextbookChapterResponse]


TextbookChapterResponse.model_rebuild()
