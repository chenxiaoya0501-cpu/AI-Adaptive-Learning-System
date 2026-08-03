from sqlalchemy import Column, String, Integer, SmallInteger, Text, Float, TIMESTAMP, ForeignKey
from sqlalchemy.types import JSON
from sqlalchemy.sql import func
from app.database import Base


class ExamPaper(Base):
    """试卷表 - 记录上传的试卷文件"""
    __tablename__ = "exam_papers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False, comment="试卷标题")
    paper_type = Column(String(30), default="real", comment="试卷类型: real(真题)/mock(模拟题)")
    source = Column(String(500), comment="来源，如：2024年XX市中考数学卷")
    grade = Column(String(20), comment="年级，如：九年级")
    subject = Column(String(20), default="数学", comment="学科")
    year = Column(String(10), comment="年份")
    region = Column(String(100), comment="地区")
    original_filename = Column(String(500), comment="上传的原始文件名")
    stored_filename = Column(String(500), comment="存储的文件名")
    total_questions = Column(Integer, default=0, comment="题目总数")
    parse_status = Column(String(20), default="pending", comment="pending/parsing/parsed/failed")
    parse_error = Column(Text, comment="解析错误信息")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class Question(Base):
    """题库表 - 结构化存储的题目"""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exam_paper_id = Column(Integer, ForeignKey("exam_papers.id"), comment="所属试卷ID")
    bank_type = Column(String(30), default="real", comment="题库类型: real(真题)/mock(模拟题)/ai(AI生成)")
    question_type = Column(String(30), nullable=False, comment="题目类型: choice(选择)/fill(填空)/answer(问答)/proof(证明)")
    question_number = Column(Integer, comment="题目序号")
    content = Column(Text, nullable=False, comment="题目描述（支持含图片的HTML/Markdown）")
    options = Column(JSON, comment="选择题选项")
    answer = Column(Text, comment="答案")
    analysis = Column(Text, comment="解析")
    difficulty = Column(SmallInteger, default=3, comment="难度1-5")
    score = Column(Float, comment="分值")
    knowledge_point_ids = Column(JSON, comment="关联知识点ID列表(兼容旧字段)")
    primary_kp_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=True, comment="主知识点ID")
    primary_kp_confidence = Column(String(20), nullable=True, comment="关联置信度: high/medium/low/manual")
    secondary_kp_ids = Column(JSON, comment="次要知识点ID列表")
    ability_dimension = Column(
        String(100),
        comment="能力维度: 计算/理解/信息提取/推理/空间/记忆",
    )
    source = Column(String(500), comment="来源说明")
    images = Column(JSON, comment="题目中的图片路径列表")
    status = Column(String(20), default="draft", comment="draft/reviewed/published")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class KpLinkTask(Base):
    """题目-知识点智能关联任务"""
    __tablename__ = "kp_link_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), default="pending", comment="pending/running/completed/failed")
    progress = Column(Integer, default=0)
    scope = Column(JSON, comment="范围配置")
    result_summary = Column(JSON)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)


class KpLinkSuggestion(Base):
    """智能关联建议（待确认）"""
    __tablename__ = "kp_link_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("kp_link_tasks.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    suggested_kp_id = Column(String(50), comment="LLM建议的主知识点")
    confidence = Column(String(20), comment="high/medium/low")
    reason = Column(Text)
    status = Column(String(20), default="pending", comment="pending/accepted/rejected/modified")
    final_kp_id = Column(String(50), comment="确认后的主知识点")
    created_at = Column(TIMESTAMP, server_default=func.now())


class AnswerRewriteTask(Base):
    """图片答案转文本任务（建议不直接落库）"""
    __tablename__ = "answer_rewrite_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), default="pending", comment="pending/running/completed/failed")
    progress = Column(Integer, default=0)
    scope = Column(JSON, comment="范围配置")
    result_summary = Column(JSON)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)


class AnswerRewriteSuggestion(Base):
    """图片答案转文本建议（待确认）"""
    __tablename__ = "answer_rewrite_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("answer_rewrite_tasks.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    original_answer = Column(Text, comment="原答案（含图片占位）")
    suggested_answer = Column(Text, comment="转写后的文本答案")
    confidence = Column(String(20), comment="high/medium/low")
    detail = Column(JSON, comment="OCR 明细")
    status = Column(String(20), default="pending", comment="pending/accepted/rejected")
    created_at = Column(TIMESTAMP, server_default=func.now())


class AbilityLabelTask(Base):
    """能力维度 AI 标注任务（建议不直接落库）"""
    __tablename__ = "ability_label_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), default="pending", comment="pending/running/completed/failed")
    progress = Column(Integer, default=0)
    scope = Column(JSON, comment="范围配置")
    result_summary = Column(JSON)
    error_message = Column(Text)
    created_at = Column(TIMESTAMP, server_default=func.now())
    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)


class AbilityLabelSuggestion(Base):
    """能力维度标注建议（待确认）"""
    __tablename__ = "ability_label_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("ability_label_tasks.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    suggested_dimension = Column(String(100), comment="建议能力维度")
    confidence = Column(String(20), comment="high/medium/low")
    reason = Column(Text)
    status = Column(String(20), default="pending", comment="pending/accepted/rejected/modified")
    final_dimension = Column(String(100), comment="确认后的能力维度")
    created_at = Column(TIMESTAMP, server_default=func.now())


class ExamScoreScheme(Base):
    """地区默认分值方案"""
    __tablename__ = "exam_score_schemes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="方案名称")
    exam_type = Column(String(50), default="zhongkao", comment="考试类型")
    subject = Column(String(20), default="数学")
    region = Column(String(100), default="浙江")
    rules = Column(JSON, nullable=False, comment="分值规则 JSON")
    is_default = Column(SmallInteger, default=0, comment="是否默认方案 1/0")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class ExamStructureTemplate(Base):
    """真题结构模板"""
    __tablename__ = "exam_structure_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    exam_type = Column(String(50), default="zhongkao")
    subject = Column(String(20), default="数学")
    region = Column(String(100), default="浙江")
    year = Column(String(10), comment="来源卷年份")
    source_paper_ids = Column(JSON, comment="来源试卷 ID 列表")
    type_structure = Column(JSON, comment="题型结构 [{question_type,count,score_each|per_number,subtotal}]")
    category_score_stats = Column(JSON, comment="按题型×一级/二级分类的分值分布")
    total_score = Column(Float, default=0, comment="卷面总分")
    scheme_id = Column(Integer, ForeignKey("exam_score_schemes.id"), nullable=True)
    status = Column(String(20), default="incomplete", comment="ready/incomplete")
    is_default = Column(SmallInteger, default=0, comment="是否考区默认模板 1/0")
    used_temp_scores = Column(SmallInteger, default=0, comment="统计时是否含临时分值")
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())


class ExamKpScoreStat(Base):
    """模板下知识点分值占比 π(k) / π(k,t)"""
    __tablename__ = "exam_kp_score_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("exam_structure_templates.id"), nullable=False)
    kp_id = Column(String(50), ForeignKey("knowledge_points.id"), nullable=False)
    question_type = Column(String(30), nullable=True, comment="题型；NULL=该 KP 全卷合计")
    score_sum = Column(Float, default=0)
    score_ratio = Column(Float, default=0, comment="π(k) 或 π(k,t)")
    question_count = Column(Integer, default=0)
