from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GoalCreate(BaseModel):
    """学习目标 + 现有状态一次性提交"""
    # —— 学习目标设置 ——
    exam_type: str = "中考"
    subject: str = "数学"
    region: Optional[str] = "浙江"
    target_score: float = Field(..., ge=0, le=200)
    exam_date: Optional[date] = None
    daily_study_minutes: Optional[int] = Field(None, ge=0, le=24 * 60)
    # —— 现有状态设置 ——
    grade_stage: str
    learned_chapter_ids: List[int] = Field(default_factory=list)
    # pending_test | assessed；创建时一般选 pending_test，不必马上测评
    mastery_status: str = "pending_test"
    # 兼容字段（前端可不传）
    current_score_estimate: Optional[float] = Field(None, ge=0, le=200)
    title: Optional[str] = None
    set_as_primary: bool = True


class GoalUpdate(BaseModel):
    exam_type: Optional[str] = None
    subject: Optional[str] = None
    region: Optional[str] = None
    target_score: Optional[float] = Field(None, ge=0, le=200)
    exam_date: Optional[date] = None
    daily_study_minutes: Optional[int] = Field(None, ge=0, le=24 * 60)
    grade_stage: Optional[str] = None
    learned_chapter_ids: Optional[List[int]] = None
    mastery_status: Optional[str] = None
    current_score_estimate: Optional[float] = Field(None, ge=0, le=200)
    title: Optional[str] = None


class GoalResultRecordPublic(BaseModel):
    id: int
    goal_id: int
    test_paper_id: Optional[int] = None
    event_type: str
    title: str
    summary: Optional[str] = None
    earned_score: Optional[float] = None
    total_score: Optional[float] = None
    correct_count: Optional[int] = None
    total_count: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class GoalResponse(BaseModel):
    id: int
    user_id: int
    title: Optional[str] = None
    exam_type: str
    subject: str
    target_score: float
    current_score_estimate: Optional[float] = None
    grade_stage: str
    exam_date: Optional[date] = None
    daily_study_minutes: Optional[int] = None
    region: Optional[str] = None
    status: str
    is_primary: bool
    mastery_status: str = "pending_test"
    learned_chapter_ids: List[int] = Field(default_factory=list)
    learned_kp_ids: List[str] = Field(default_factory=list)
    learned_chapter_count: int = 0
    learned_kp_count: int = 0
    needs_replan: bool = False
    recent_results: List[GoalResultRecordPublic] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PreviewKpRequest(BaseModel):
    chapter_ids: List[int] = Field(default_factory=list)
    grade_stage: Optional[str] = None


class PreviewKpResponse(BaseModel):
    chapter_count: int
    kp_count: int
    kp_ids: List[str] = Field(default_factory=list)
    prior_stages_included: List[str] = Field(
        default_factory=list,
        description="已自动计入的先前册次，如七年级上…八年级下",
    )
