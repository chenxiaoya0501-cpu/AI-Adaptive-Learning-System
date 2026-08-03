from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CourseExplanation(BaseModel):
    id: Optional[int] = None
    title: str
    summary: Optional[str] = None
    content: str
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    key_points: List[str] = Field(default_factory=list)
    examples: List[Dict[str, Any]] = Field(default_factory=list)
    common_mistakes: List[Any] = Field(default_factory=list)
    difficulty_level: str = "basic"
    source: str = "ai_explanation"


class CourseResource(BaseModel):
    title: str
    url: str
    platform: str
    resource_type: str = "search"
    note: Optional[str] = None


class CourseQuestion(BaseModel):
    id: int
    question_type: str
    content: str
    options: Optional[Any] = None
    difficulty: int = 3
    source: Optional[str] = None
    bank_type: str
    images: Optional[Any] = None


class CoursePublic(BaseModel):
    path_id: int
    goal_id: int
    node_id: int
    kp_id: str
    kp_name: str
    stage_index: int
    role: str
    current_mastery: Optional[float] = None
    target_mastery: float
    estimated_minutes: int
    objectives: List[str]
    explanation: CourseExplanation
    external_resources: List[CourseResource]
    questions: List[CourseQuestion]
    progress: Dict[str, Any]
    warnings: List[str] = Field(default_factory=list)


class CourseAnswer(BaseModel):
    question_id: int
    selected_option: Optional[str] = None
    answer_text: Optional[str] = None


class CourseCompleteRequest(BaseModel):
    explanation_completed: bool = True
    answers: List[CourseAnswer] = Field(default_factory=list)


class CourseCompleteResult(BaseModel):
    path_id: int
    node_id: int
    kp_id: str
    answered_count: int
    correct_count: int
    accuracy: Optional[float] = None
    completed: bool
    task_statuses: Dict[str, str]
    question_results: List[Dict[str, Any]] = Field(default_factory=list)
    evaluation: Dict[str, Any]


class CourseMasterySyncResult(BaseModel):
    path_id: int
    goal_id: int
    kp_id: str
    mastery_score: float
    confidence: float
    achieved: bool
    synced_at: datetime


class CourseTutorTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class CourseTutorRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: List[CourseTutorTurn] = Field(default_factory=list, max_length=8)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value


class CourseTutorResponse(BaseModel):
    answer: str
    suggested_questions: List[str] = Field(default_factory=list)


class LearningCourseSummary(BaseModel):
    path_id: int
    goal_id: int
    goal_title: str
    kp_id: str
    kp_name: str
    node_id: int
    stage_index: int
    estimated_minutes: int
    status: str
    available: bool
