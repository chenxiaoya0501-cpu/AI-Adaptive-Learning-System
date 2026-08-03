from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


class KnowledgePointCreate(BaseModel):
    id: str
    name: str
    short_name: Optional[str] = None
    subject: str = "数学"
    domain: Optional[str] = None
    category_1: Optional[str] = None
    category_2: Optional[str] = None
    typical_questions: Optional[str] = None
    grade: Optional[str] = None
    chapter: Optional[str] = None
    prerequisites: Optional[str] = None
    cognitive_level: Optional[str] = None
    source: Optional[str] = None
    status: str = "draft"


class KnowledgePointUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    subject: Optional[str] = None
    domain: Optional[str] = None
    category_1: Optional[str] = None
    category_2: Optional[str] = None
    typical_questions: Optional[str] = None
    grade: Optional[str] = None
    chapter: Optional[str] = None
    prerequisites: Optional[str] = None
    cognitive_level: Optional[str] = None
    source: Optional[str] = None
    status: Optional[str] = None


class KnowledgePointResponse(BaseModel):
    id: str
    name: str
    short_name: Optional[str] = None
    subject: Optional[str] = None
    domain: Optional[str] = None
    category_1: Optional[str] = None
    category_2: Optional[str] = None
    typical_questions: Optional[str] = None
    grade: Optional[str] = None
    chapter: Optional[str] = None
    prerequisites: Optional[str] = None
    cognitive_level: Optional[str] = None
    source: Optional[str] = None
    status: str
    version: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KnowledgePointListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[KnowledgePointResponse]


class KnowledgeRelationCreate(BaseModel):
    from_point_id: str
    to_point_id: str
    relation_type: str
    weight: float = 1.0


class KnowledgeRelationResponse(BaseModel):
    id: int
    from_point_id: str
    to_point_id: str
    from_point_name: Optional[str] = None
    from_point_short_name: Optional[str] = None
    to_point_name: Optional[str] = None
    to_point_short_name: Optional[str] = None
    relation_type: str
    weight: float
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KnowledgeStatsResponse(BaseModel):
    total: int
    by_domain: Dict[str, int]
    by_grade: Dict[str, int]
    by_status: Dict[str, int]
    relation_count: int
