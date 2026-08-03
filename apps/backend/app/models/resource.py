"""课程与资源管理相关模型"""
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


class KpExplanation(Base):
    """AI 生成的知识点讲解内容"""
    __tablename__ = "kp_explanations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kp_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False, index=True)
    title = Column(String(200), comment="讲解标题")
    content = Column(Text, nullable=False, comment="讲解正文（Markdown）")
    content_blocks = Column(
        Text,
        comment="图文讲解内容块（JSON 数组，兼容正文与受控数学图示）",
    )
    summary = Column(Text, comment="知识点概要/一句话总结")
    key_points = Column(Text, comment="重点要点（JSON 数组）")
    examples = Column(Text, comment="典型例题与解析（JSON 数组）")
    common_mistakes = Column(Text, comment="常见错误（JSON 数组）")
    difficulty_level = Column(String(20), default="basic", comment="basic/intermediate/advanced")
    status = Column(String(20), default="draft", comment="draft/reviewed/published")
    version = Column(Integer, default=1, comment="版本号，同一知识点可多次生成")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class KpVideoResource(Base):
    """与知识点直接关联、经过确认的外部教学视频。"""
    __tablename__ = "kp_video_resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kp_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    url = Column(String(1000), nullable=False, unique=True)
    platform = Column(String(30), nullable=False, comment="bilibili/youtube")
    description = Column(String(500))
    sort_order = Column(Integer, default=0)
    is_active = Column(Integer, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())
