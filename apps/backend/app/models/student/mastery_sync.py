"""课程掌握度主动同步到学习地图的快照。"""
from sqlalchemy import Column, Float, ForeignKey, Integer, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.types import JSON

from app.database import Base


class CourseMasterySync(Base):
    __tablename__ = "course_mastery_syncs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    goal_id = Column(Integer, ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    path_id = Column(Integer, ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False)
    kp_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False, index=True)
    mastery_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    achieved = Column(Integer, nullable=False, default=0)
    evidence_json = Column(JSON, nullable=False)
    synced_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "goal_id", "kp_id", name="uq_course_mastery_sync"),
    )
