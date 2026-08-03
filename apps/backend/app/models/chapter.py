"""教材章节目录模型"""
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class TextbookChapter(Base):
    """从电子课本抽取的章节目录节点"""
    __tablename__ = "textbook_chapters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    uploaded_file_id = Column(Integer, ForeignKey("uploaded_files.id"), nullable=False, comment="来源教材文件")
    subject = Column(String(20), default="数学")
    grade = Column(String(20), comment="年级，如七年级")
    semester = Column(String(20), comment="上/下")
    parent_id = Column(Integer, ForeignKey("textbook_chapters.id"), nullable=True, comment="父节点，节挂在章下")
    level = Column(String(20), default="chapter", comment="chapter/section")
    title = Column(String(500), nullable=False, comment="章节标题")
    sort_order = Column(Integer, default=0)
    content_summary = Column(Text, comment="节内容概述：该节核心知识点提炼")
    status = Column(String(20), default="draft", comment="draft/published")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("uploaded_file_id", "level", "title", "parent_id", name="uq_textbook_chapter"),
    )
