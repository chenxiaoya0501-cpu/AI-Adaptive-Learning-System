"""学生测评卷与题目快照"""
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    TIMESTAMP,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.types import JSON
from sqlalchemy.sql import func

from app.database import Base


class TestPaper(Base):
    __tablename__ = "test_papers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    goal_id = Column(Integer, ForeignKey("learning_goals.id"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("exam_structure_templates.id"), nullable=True)
    paper_kind = Column(String(30), nullable=False, default="diagnostic", comment="diagnostic/review")
    bank_type = Column(String(30), nullable=False, default="real", comment="real/mock")
    status = Column(
        String(30),
        nullable=False,
        default="assembled",
        comment="assembled/in_progress/submitted/grading/graded",
    )
    title = Column(String(200), nullable=True)
    total_score = Column(Float, nullable=False, default=0)
    earned_score = Column(Float, nullable=True)
    type_structure = Column(JSON, nullable=True, comment="组卷时题型结构快照")
    algorithm_version = Column(String(20), nullable=False, default="v1")
    lambda_value = Column(Float, nullable=False, default=0.35)
    degraded = Column(Boolean, nullable=False, default=False)
    warnings = Column(JSON, nullable=True)
    assessment_status = Column(
        String(20),
        nullable=True,
        comment="能力评估状态：pending/ready/failed",
    )
    assessment_json = Column(JSON, nullable=True, comment="批改后能力评估报告 JSON")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class TestQuestion(Base):
    __tablename__ = "test_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_paper_id = Column(Integer, ForeignKey("test_papers.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False, comment="卷内题号，从 1 起")
    source_question_id = Column(Integer, ForeignKey("questions.id"), nullable=True)
    source_exam_paper_id = Column(
        Integer,
        ForeignKey("exam_papers.id"),
        nullable=True,
        comment="源试卷ID，用于解析 [IMG:] 图片路径",
    )
    question_type = Column(String(30), nullable=False)
    content = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    answer = Column(Text, nullable=True, comment="快照答案，仅服务端")
    analysis = Column(Text, nullable=True, comment="快照解析，仅服务端")
    images = Column(JSON, nullable=True)
    score = Column(Float, nullable=False, default=0)
    primary_kp_id = Column(String(50), nullable=True)
    secondary_kp_ids = Column(JSON, nullable=True)
    difficulty = Column(Integer, nullable=True)
    ability_dimension = Column(
        String(100),
        nullable=True,
        comment="快照能力维度：计算/理解/信息提取/推理/空间/记忆",
    )
    created_at = Column(TIMESTAMP, server_default=func.now())


class TestAnswer(Base):
    """学生对卷内题目的作答（一题一条）"""
    __tablename__ = "test_answers"
    __table_args__ = (
        UniqueConstraint("test_paper_id", "test_question_id", name="uq_test_answer_paper_question"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_paper_id = Column(
        Integer, ForeignKey("test_papers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    test_question_id = Column(
        Integer, ForeignKey("test_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    selected_option = Column(String(10), nullable=True, comment="选择题选项 A/B/C/D")
    answer_text = Column(Text, nullable=True, comment="填空/解答文本")
    image_urls = Column(JSON, nullable=True, comment="手写图 URL 列表")
    is_marked_uncertain = Column(Boolean, nullable=False, default=False)
    is_correct = Column(Boolean, nullable=True)
    score_got = Column(Float, nullable=True)
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
    created_at = Column(TIMESTAMP, server_default=func.now())


class WrongQuestionAiExercise(Base):
    """基于错题生成的个性化 AI 练习题。"""
    __tablename__ = "wrong_question_ai_exercises"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)
    source_question_id = Column(Integer, nullable=False, index=True)
    mode = Column(String(20), nullable=False, comment="similar/deeper")
    question_type = Column(String(30), nullable=False)
    content = Column(Text, nullable=False)
    options = Column(JSON, nullable=True)
    answer = Column(Text, nullable=False)
    analysis = Column(Text, nullable=False)
    difficulty = Column(Integer, nullable=False, default=3)
    user_answer = Column(Text, nullable=True)
    is_correct = Column(Boolean, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    answered_at = Column(TIMESTAMP, nullable=True)
