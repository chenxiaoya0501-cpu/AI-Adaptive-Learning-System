from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class ExamPaperCreate(BaseModel):
    title: str
    paper_type: str = "real"
    source: Optional[str] = None
    grade: Optional[str] = None
    subject: str = "数学"
    year: Optional[str] = None
    region: Optional[str] = None


class ExamPaperUpdate(BaseModel):
    title: Optional[str] = None
    paper_type: Optional[str] = None
    grade: Optional[str] = None
    year: Optional[str] = None
    region: Optional[str] = None
    subject: Optional[str] = None


class ExamPaperResponse(BaseModel):
    id: int
    title: str
    paper_type: str
    source: Optional[str] = None
    grade: Optional[str] = None
    subject: str = "数学"
    year: Optional[str] = None
    region: Optional[str] = None
    original_filename: Optional[str] = None
    total_questions: int = 0
    parse_status: str = "pending"
    parse_error: Optional[str] = None
    linked_count: Optional[int] = None
    scored_count: Optional[int] = None
    template_id: Optional[int] = None
    template_status: Optional[str] = None  # none/ready/incomplete
    template_is_default: Optional[bool] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


ABILITY_DIMENSIONS = ("计算", "理解", "信息提取", "推理", "空间", "记忆")


class QuestionCreate(BaseModel):
    exam_paper_id: Optional[int] = None
    bank_type: str = "real"
    question_type: str
    question_number: Optional[int] = None
    content: str
    options: Optional[Dict[str, str]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    difficulty: int = 3
    score: Optional[float] = None
    knowledge_point_ids: Optional[List[str]] = None
    primary_kp_id: Optional[str] = None
    secondary_kp_ids: Optional[List[str]] = None
    ability_dimension: Optional[str] = None
    source: Optional[str] = None

    @field_validator("ability_dimension")
    @classmethod
    def _validate_ability(cls, v):
        if v is None or v == "":
            return None
        if v not in ABILITY_DIMENSIONS:
            raise ValueError(f"能力维度必须是：{'、'.join(ABILITY_DIMENSIONS)}")
        return v


class QuestionUpdate(BaseModel):
    question_type: Optional[str] = None
    question_number: Optional[int] = None
    content: Optional[str] = None
    options: Optional[Dict[str, str]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    difficulty: Optional[int] = None
    score: Optional[float] = None
    knowledge_point_ids: Optional[List[str]] = None
    primary_kp_id: Optional[str] = None
    secondary_kp_ids: Optional[List[str]] = None
    ability_dimension: Optional[str] = None
    bank_type: Optional[str] = None
    source: Optional[str] = None

    @field_validator("ability_dimension")
    @classmethod
    def _validate_ability(cls, v):
        if v is None or v == "":
            return None
        if v not in ABILITY_DIMENSIONS:
            raise ValueError(f"能力维度必须是：{'、'.join(ABILITY_DIMENSIONS)}")
        return v


class QuestionResponse(BaseModel):
    id: int
    exam_paper_id: Optional[int] = None
    bank_type: str
    question_type: str
    question_number: Optional[int] = None
    content: str
    options: Optional[Dict[str, str]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    difficulty: int = 3
    score: Optional[float] = None
    knowledge_point_ids: Optional[List[str]] = None
    primary_kp_id: Optional[str] = None
    primary_kp_name: Optional[str] = None
    primary_kp_category_1: Optional[str] = None
    primary_kp_category_2: Optional[str] = None
    primary_kp_confidence: Optional[str] = None  # high/medium/low/manual
    secondary_kp_ids: Optional[List[str]] = None
    ability_dimension: Optional[str] = None
    source: Optional[str] = None
    images: Optional[List[str]] = None
    status: str = "draft"
    has_pending_suggestion: Optional[bool] = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QuestionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[QuestionResponse]
    linked_count: Optional[int] = None
    link_rate: Optional[float] = None


class KpLinkStartRequest(BaseModel):
    exam_paper_id: Optional[int] = None
    only_unlinked: bool = True
    question_ids: Optional[List[int]] = None
    bank_type: Optional[str] = None  # real / mock


class KpLinkTaskResponse(BaseModel):
    id: int
    status: str
    progress: int = 0
    scope: Optional[Any] = None
    result_summary: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class KpLinkSuggestionResponse(BaseModel):
    id: int
    task_id: int
    question_id: int
    question_number: Optional[int] = None
    question_content: Optional[str] = None
    suggested_kp_id: Optional[str] = None
    suggested_kp_name: Optional[str] = None
    confidence: Optional[str] = None
    reason: Optional[str] = None
    status: str = "pending"
    final_kp_id: Optional[str] = None

    class Config:
        from_attributes = True


class KpLinkConfirmItem(BaseModel):
    suggestion_id: int
    action: str  # accept / reject / modify
    kp_id: Optional[str] = None  # modify 时必填


class KpLinkConfirmRequest(BaseModel):
    items: List[KpLinkConfirmItem]


class BatchSetPrimaryKpRequest(BaseModel):
    question_ids: List[int]
    primary_kp_id: str


class BatchDeleteQuestionsRequest(BaseModel):
    question_ids: List[int]


class BatchRewriteImageAnswersRequest(BaseModel):
    """批量将答案中的公式图片转写为文本（兼容旧接口）。"""
    question_ids: Optional[List[int]] = None
    exam_paper_id: Optional[int] = None
    bank_type: Optional[str] = None  # real / mock
    dry_run: bool = False


class AnswerRewriteStartRequest(BaseModel):
    """启动图片答案转文本任务（仅生成待确认建议）。"""
    question_ids: Optional[List[int]] = None
    exam_paper_id: Optional[int] = None
    bank_type: Optional[str] = None


class AnswerRewriteTaskResponse(BaseModel):
    id: int
    status: str
    progress: int = 0
    scope: Optional[Any] = None
    result_summary: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnswerRewriteSuggestionResponse(BaseModel):
    id: int
    task_id: int
    question_id: int
    question_number: Optional[int] = None
    question_content: Optional[str] = None
    exam_paper_id: Optional[int] = None
    original_answer: Optional[str] = None
    suggested_answer: Optional[str] = None
    confidence: Optional[str] = None
    detail: Optional[Any] = None
    status: str = "pending"

    class Config:
        from_attributes = True


class AnswerRewriteConfirmItem(BaseModel):
    suggestion_id: int
    action: str  # accept / reject


class AnswerRewriteConfirmRequest(BaseModel):
    items: List[AnswerRewriteConfirmItem]


class AbilityLabelStartRequest(BaseModel):
    """启动能力维度 AI 标注任务。"""
    question_ids: Optional[List[int]] = None
    exam_paper_id: Optional[int] = None
    bank_type: Optional[str] = None
    only_unlabeled: bool = True


class AbilityLabelTaskResponse(BaseModel):
    id: int
    status: str
    progress: int = 0
    scope: Optional[Any] = None
    result_summary: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AbilityLabelSuggestionResponse(BaseModel):
    id: int
    task_id: int
    question_id: int
    question_number: Optional[int] = None
    question_content: Optional[str] = None
    current_dimension: Optional[str] = None
    suggested_dimension: Optional[str] = None
    confidence: Optional[str] = None
    reason: Optional[str] = None
    status: str = "pending"
    final_dimension: Optional[str] = None

    class Config:
        from_attributes = True


class AbilityLabelConfirmItem(BaseModel):
    suggestion_id: int
    action: str  # accept / reject / modify
    ability_dimension: Optional[str] = None  # modify 时必填


class AbilityLabelConfirmRequest(BaseModel):
    items: List[AbilityLabelConfirmItem]


class ExamScoreSchemeCreate(BaseModel):
    name: str
    exam_type: str = "zhongkao"
    subject: str = "数学"
    region: str = "浙江"
    rules: Dict[str, Any]
    is_default: bool = False


class ExamScoreSchemeResponse(BaseModel):
    id: int
    name: str
    exam_type: str
    subject: str
    region: str
    rules: Dict[str, Any]
    is_default: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApplyScoreSchemeRequest(BaseModel):
    scheme_id: Optional[int] = None
    overwrite: bool = False


class BuildTemplateRequest(BaseModel):
    scheme_id: Optional[int] = None
    paper_ids: Optional[List[int]] = None  # 多卷生成时使用；单卷接口可省略


class ExamKpScoreStatResponse(BaseModel):
    id: Optional[int] = None
    template_id: Optional[int] = None
    kp_id: str
    kp_name: Optional[str] = None
    category_1: Optional[str] = None
    domain: Optional[str] = None
    question_type: Optional[str] = None
    score_sum: float = 0
    score_ratio: float = 0
    question_count: int = 0


class ExamStructureTemplateResponse(BaseModel):
    id: int
    name: str
    exam_type: str
    subject: str
    region: str
    year: Optional[str] = None
    source_paper_ids: Optional[List[int]] = None
    type_structure: Optional[List[Dict[str, Any]]] = None
    category_score_stats: Optional[Dict[str, Any]] = None
    total_score: float = 0
    scheme_id: Optional[int] = None
    status: str
    is_default: bool = False
    used_temp_scores: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    stats: Optional[List[ExamKpScoreStatResponse]] = None
    build_meta: Optional[Dict[str, Any]] = None
    # 来源卷逐题明细：题号/题型/分值/一二级分类/主知识点ID
    question_rows: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class AIGenerateRequest(BaseModel):
    kp_id: str
    question_type: str = "choice"
    count: int = 3
    sample_ids: Optional[List[int]] = None
    difficulty: Optional[int] = None


class AIGeneratedQuestionItem(BaseModel):
    question_type: str
    content: str
    options: Optional[Dict[str, str]] = None
    answer: Optional[str] = None
    analysis: Optional[str] = None
    difficulty: int = 3


class AIGenerateResponse(BaseModel):
    questions: List[AIGeneratedQuestionItem]
