from sqlalchemy import Column, String, Integer, SmallInteger, Text, Float, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from app.database import Base


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id = Column(String(50), primary_key=True)
    subject = Column(String(20), default="数学", comment="学科类别")
    domain = Column(String(50), comment="知识领域：数与代数/图形与几何/统计与概率/综合与实践")
    category_1 = Column(String(100), comment="知识点一级分类，如：数与式/方程与不等式")
    category_2 = Column(String(100), comment="知识点二级分类，如：有理数/整式")
    name = Column(String(500), nullable=False, comment="知识点内容描述")
    short_name = Column(String(100), comment="知识点简短名称")
    typical_questions = Column(Text, comment="典型题目，来自课标")
    grade = Column(String(20), comment="年级段，如：七年级上")
    chapter = Column(String(200), comment="所属章节，来自教材")
    prerequisites = Column(Text, comment="依赖知识点ID列表，逗号分隔")
    cognitive_level = Column(String(20), comment="了解/理解/掌握/运用")
    source = Column(String(50), comment="数据来源: curriculum/textbook/manual")
    status = Column(String(20), default="draft", comment="draft/reviewed/published")
    version = Column(Integer, default=1)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    from_point_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False)
    to_point_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False)
    relation_type = Column(String(30), nullable=False, comment="prerequisite/contains/related/extends")
    weight = Column(Float, default=1.0)
    created_at = Column(TIMESTAMP, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("from_point_id", "to_point_id", "relation_type", name="uq_relation"),
    )


class TypicalQuestion(Base):
    __tablename__ = "typical_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_point_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False)
    question_content = Column(Text, nullable=False)
    answer = Column(Text)
    analysis = Column(Text, comment="解析")
    difficulty = Column(SmallInteger, comment="难度1-5")
    question_type = Column(String(30), comment="选择/填空/解答")
    source = Column(String(200), comment="来源")
    created_at = Column(TIMESTAMP, server_default=func.now())
