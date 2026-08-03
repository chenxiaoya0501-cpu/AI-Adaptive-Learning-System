from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LearningPathGenerateRequest(BaseModel):
    daily_study_minutes: Optional[int] = Field(None, ge=15, le=720)
    start_date: Optional[date] = None
    horizon_days: Optional[int] = Field(None, ge=1, le=180)
    generation_reason: str = Field("manual", max_length=30)


class LearningPathNodePublic(BaseModel):
    id: Optional[int] = None
    kp_id: str
    name: str
    order_index: int
    stage_index: int
    stage_type: str
    role: str
    current_mastery: Optional[float] = None
    target_mastery: float
    confidence: float
    exam_weight: float
    priority: float
    expected_gain: float
    estimated_minutes: int
    prerequisite_kp_ids: List[str] = Field(default_factory=list)
    reason: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"


class LearningTaskPublic(BaseModel):
    id: Optional[int] = None
    path_node_id: Optional[int] = None
    kp_id: str
    scheduled_date: date
    sequence: int
    task_type: str
    title: str
    instruction: Optional[str] = None
    estimated_minutes: int
    status: str = "pending"
    result: Optional[Dict[str, Any]] = None


class LearningTaskUpdate(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None


class LearningPathPublic(BaseModel):
    id: Optional[int] = None
    goal_id: int
    version: Optional[int] = None
    status: str
    algorithm_version: str
    generation_reason: str
    source_paper_ids: List[int] = Field(default_factory=list)
    summary: Dict[str, Any]
    nodes: List[LearningPathNodePublic]
    tasks: List[LearningTaskPublic]
    created_at: Optional[datetime] = None
