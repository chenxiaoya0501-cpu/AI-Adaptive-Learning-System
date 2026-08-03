from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=False)
    description = Column(String(500))
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    original_name = Column(String(500), nullable=False)
    file_type = Column(String(50), comment="curriculum/textbook")
    file_size = Column(Integer)
    grade = Column(String(20), comment="年级,教材用")
    semester = Column(String(20), comment="学期,教材用")
    status = Column(String(20), default="uploaded", comment="uploaded/parsing/parsed/failed")
    parse_result = Column(JSON, comment="解析结果摘要")
    created_at = Column(TIMESTAMP, server_default=func.now())


class ExtractionTask(Base):
    __tablename__ = "extraction_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_type = Column(String(50), nullable=False, comment="knowledge_extraction/relation_extraction")
    source_file_ids = Column(Text, comment="源文件ID列表，逗号分隔，支持多文件")
    status = Column(String(20), default="pending", comment="pending/running/completed/failed")
    progress = Column(Integer, default=0, comment="进度百分比")
    result_summary = Column(JSON, comment="结果摘要")
    error_message = Column(Text)
    config = Column(JSON, comment="运行时配置快照")
    created_at = Column(TIMESTAMP, server_default=func.now())
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)
