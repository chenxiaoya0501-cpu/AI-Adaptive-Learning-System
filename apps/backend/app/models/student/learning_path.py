"""学生学习路径、路径节点与每日任务。"""
from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.database import Base


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    goal_id = Column(
        Integer, ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="draft", index=True)
    generation_reason = Column(String(30), nullable=False, default="manual")
    algorithm_version = Column(String(30), nullable=False, default="path-v2.1")
    input_signature = Column(String(64), nullable=False, index=True)
    source_paper_ids = Column(JSON, nullable=True)
    goal_snapshot = Column(JSON, nullable=False)
    mastery_snapshot = Column(JSON, nullable=False)
    planning_params = Column(JSON, nullable=False)
    summary_json = Column(JSON, nullable=False)
    activated_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("goal_id", "version", name="uq_learning_path_goal_version"),
    )


class LearningPathNode(Base):
    __tablename__ = "learning_path_nodes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path_id = Column(
        Integer, ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kp_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False, index=True)
    order_index = Column(Integer, nullable=False)
    stage_index = Column(Integer, nullable=False)
    stage_type = Column(String(30), nullable=False)
    role = Column(String(30), nullable=False)
    current_mastery = Column(Float, nullable=True)
    target_mastery = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False, default=0)
    exam_weight = Column(Float, nullable=False, default=0)
    priority = Column(Float, nullable=False, default=0)
    expected_gain = Column(Float, nullable=False, default=0)
    estimated_minutes = Column(Integer, nullable=False)
    prerequisite_kp_ids = Column(JSON, nullable=True)
    reason_json = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    completed_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("path_id", "kp_id", name="uq_learning_path_node_kp"),
    )


class LearningTask(Base):
    __tablename__ = "learning_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path_id = Column(
        Integer, ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path_node_id = Column(
        Integer,
        ForeignKey("learning_path_nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    scheduled_date = Column(Date, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    task_type = Column(String(30), nullable=False)
    title = Column(String(200), nullable=False)
    instruction = Column(Text, nullable=True)
    estimated_minutes = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    resource_type = Column(String(30), nullable=True)
    resource_id = Column(String(100), nullable=True)
    result_json = Column(JSON, nullable=True)
    started_at = Column(TIMESTAMP, nullable=True)
    completed_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("path_id", "sequence", name="uq_learning_task_path_sequence"),
    )
