from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AssembleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goal_id: int
    bank_type: str = Field("real", description="real=真题库 / mock=模拟题库")
    lambda_value: Optional[float] = Field(None, ge=0, le=1, alias="lambda")
    template_id: Optional[int] = None
    paper_kind: str = "diagnostic"


class TypeStructureItem(BaseModel):
    question_type: str
    count: int
    subtotal: float
    score_each: Optional[float] = None


class TestQuestionPublic(BaseModel):
    id: int
    seq: int
    question_type: str
    content: str
    options: Optional[Any] = None
    score: float
    primary_kp_id: Optional[str] = None
    images: Optional[Any] = None
    difficulty: Optional[int] = None
    source_exam_paper_id: Optional[int] = None


class TestPaperSummary(BaseModel):
    id: int
    goal_id: int
    template_id: Optional[int] = None
    paper_kind: str
    bank_type: str
    status: str
    title: Optional[str] = None
    total_score: float
    earned_score: Optional[float] = None
    question_count: int = 0
    degraded: bool = False
    warnings: Optional[List[str]] = None
    created_at: Optional[datetime] = None


class TestPaperDetail(TestPaperSummary):
    type_structure: Optional[List[Dict[str, Any]]] = None
    algorithm_version: str = "v1"
    lambda_value: float = 0.35
    questions: List[TestQuestionPublic] = Field(default_factory=list)


class AssemblePreview(BaseModel):
    """组卷前预览：目标 + 模板题型结构 + 资产就绪"""
    goal_id: int
    goal_title: Optional[str] = None
    grade_stage: str
    region: Optional[str] = None
    learned_chapter_count: int = 0
    learned_kp_count: int = 0
    template_id: Optional[int] = None
    template_name: Optional[str] = None
    template_status: Optional[str] = None
    total_score: float = 0
    type_structure: List[TypeStructureItem] = Field(default_factory=list)
    readiness_ok: bool = False
    readiness_messages: List[str] = Field(default_factory=list)


class AnswerPayload(BaseModel):
    selected_option: Optional[str] = None
    answer_text: Optional[str] = None
    image_urls: Optional[List[str]] = None
    is_marked_uncertain: bool = False


class ProgressAnswerItem(AnswerPayload):
    test_question_id: int


class SaveProgressPayload(BaseModel):
    answers: List[ProgressAnswerItem] = Field(default_factory=list)


class AnswerPublic(BaseModel):
    test_question_id: int
    selected_option: Optional[str] = None
    answer_text: Optional[str] = None
    image_urls: Optional[List[str]] = None
    is_marked_uncertain: bool = False
    is_correct: Optional[bool] = None
    score_got: Optional[float] = None


class TakingSession(BaseModel):
    """答题会话：试卷题干 + 已保存作答（不含标准答案）"""
    paper: TestPaperDetail
    answers: List[AnswerPublic] = Field(default_factory=list)
    answered_count: int = 0
    total_count: int = 0
    readonly: bool = False


class QuestionResultItem(BaseModel):
    question_id: int
    seq: int
    question_type: str
    score: float
    is_correct: Optional[bool] = None
    score_got: Optional[float] = None
    selected_option: Optional[str] = None
    answer_text: Optional[str] = None
    correct_answer: Optional[str] = None
    source_exam_paper_id: Optional[int] = None
    grading_note: Optional[str] = None
    # 批改详情补充：原题 / 来源 / 解析
    content: Optional[str] = None
    options: Optional[Any] = None
    analysis: Optional[str] = None
    source_label: Optional[str] = None
    source_year: Optional[str] = None
    source_region: Optional[str] = None
    source_question_number: Optional[int] = None
    ability_dimension: Optional[str] = None
    difficulty: Optional[int] = None
    primary_kp_id: Optional[str] = None


class SubmitResult(BaseModel):
    paper_id: int
    goal_id: int
    status: str
    answered_count: int
    total_count: int
    correct_count: int = 0
    earned_score: Optional[float] = None
    total_score: float = 0
    graded_count: int = 0
    message: str = ""
    assessment_status: Optional[str] = None


class PaperResultDetail(BaseModel):
    paper_id: int
    goal_id: int
    title: Optional[str] = None
    status: str
    earned_score: Optional[float] = None
    total_score: float = 0
    answered_count: int = 0
    correct_count: int = 0
    total_count: int = 0
    items: List[QuestionResultItem] = Field(default_factory=list)
    assessment_status: Optional[str] = None
    assessment: Optional[Any] = None


class WrongQuestionItem(BaseModel):
    """“我的错题集”中的一次错误作答。"""
    id: str
    source_type: str
    question_id: int
    paper_id: Optional[int] = None
    paper_title: Optional[str] = None
    path_id: Optional[int] = None
    kp_id: Optional[str] = None
    seq: Optional[int] = None
    question_type: str
    content: str
    options: Optional[Any] = None
    user_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    analysis: Optional[str] = None
    source_exam_paper_id: Optional[int] = None
    difficulty: Optional[int] = None
    created_at: Optional[datetime] = None
    generated_exercises: List[Dict[str, Any]] = Field(default_factory=list)


class WrongQuestionList(BaseModel):
    total: int = 0
    assessment_count: int = 0
    practice_count: int = 0
    items: List[WrongQuestionItem] = Field(default_factory=list)


class WrongQuestionGenerateRequest(BaseModel):
    source_type: str
    question_id: int
    mode: str = Field("similar", pattern="^(similar|deeper)$")


class AiExercisePublic(BaseModel):
    id: int
    mode: str
    question_type: str
    content: str
    options: Optional[Any] = None
    difficulty: int


class AiExerciseAnswerRequest(BaseModel):
    answer: str = Field(..., min_length=1, max_length=4000)


class AiExerciseResult(AiExercisePublic):
    user_answer: str
    is_correct: bool
    correct_answer: str
    analysis: str
