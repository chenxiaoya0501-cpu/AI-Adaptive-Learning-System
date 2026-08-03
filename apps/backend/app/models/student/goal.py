"""学生学习目标"""
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, Date, TIMESTAMP, ForeignKey, UniqueConstraint,
)
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from app.database import Base


class LearningGoal(Base):
    __tablename__ = "learning_goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=True, comment="展示标题，可自动生成")
    exam_type = Column(String(30), nullable=False, default="中考")
    subject = Column(String(20), nullable=False, default="数学")
    target_score = Column(Float, nullable=False)
    current_score_estimate = Column(Float, nullable=True)
    grade_stage = Column(String(50), nullable=False, comment="如九年级上")
    exam_date = Column(Date, nullable=True)
    daily_study_minutes = Column(Integer, nullable=True)
    region = Column(String(50), nullable=True, comment="考区，如浙江")
    status = Column(String(20), nullable=False, default="active", comment="active/archived")
    is_primary = Column(Boolean, nullable=False, default=False)
    learned_kp_ids = Column(JSON, nullable=True, comment="由已学章节展开的知识点 ID 缓存")
    # pending_test: 状态已建、掌握情况待测评；assessed: 已通过测评体现掌握情况
    mastery_status = Column(String(30), nullable=False, default="pending_test")
    needs_replan = Column(Boolean, nullable=False, default=False, comment="章节/目标分变更后提示重测或重规划")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class GoalLearnedChapter(Base):
    __tablename__ = "goal_learned_chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(Integer, ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(Integer, ForeignKey("textbook_chapters.id"), nullable=False)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("goal_id", "chapter_id", name="uq_goal_learned_chapter"),
    )


class GoalResultRecord(Base):
    """学习目标上的测评结果时间点记录（交卷 / 批改完成等）"""
    __tablename__ = "goal_result_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    goal_id = Column(
        Integer, ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    test_paper_id = Column(
        Integer, ForeignKey("test_papers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type = Column(
        String(30),
        nullable=False,
        comment="taking（答题中）/ graded（批改完成）/ assembled|submitted（历史遗留）",
    )
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    earned_score = Column(Float, nullable=True)
    total_score = Column(Float, nullable=True)
    correct_count = Column(Integer, nullable=True)
    total_count = Column(Integer, nullable=True)
    meta = Column(JSON, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
