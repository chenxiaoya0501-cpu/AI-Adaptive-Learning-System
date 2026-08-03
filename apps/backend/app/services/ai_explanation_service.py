"""AI 知识点讲解生成服务 - 调用大模型为知识点生成结构化讲解内容"""
import json
import logging
from typing import Optional, Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgePoint
from app.models.resource import KpExplanation
from app.models.system import SystemConfig
from app.services.explanation_blocks import (
    markdown_from_blocks,
    normalize_content_blocks,
)
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)


def _build_system_prompt() -> str:
    return (
        "你是一位经验丰富的初中数学教师，擅长将数学知识讲解得通俗易懂、条理清晰。\n"
        "你需要为学生生成一份准确的图文知识点讲解。正文与数学图示必须按阅读顺序组织。\n"
        "数学图示只能使用下方受控 JSON 参数描述，禁止输出 HTML、SVG、图片链接或代码。\n\n"
        "输出格式为 JSON，结构如下：\n"
        "{\n"
        '  "title": "讲解标题（简短有吸引力）",\n'
        '  "summary": "一句话概括该知识点的核心内容",\n'
        '  "content_blocks": [\n'
        '    {"type": "markdown", "content": "按章节组织的 Markdown 正文"},\n'
        '    {\n'
        '      "type": "visual",\n'
        '      "visual_type": "geometry | number_line | coordinate_plane | function_plot | bar_chart | line_chart",\n'
        '      "title": "图示标题", "caption": "图示说明", "alt": "无障碍文字说明",\n'
        '      "spec": {}\n'
        '    }\n'
        "  ],\n"
        '  "key_points": ["要点1", "要点2", ...],\n'
        '  "examples": [\n'
        '    {"problem": "例题题目", "solution": "详细解题步骤", "explanation": "解题思路说明"}\n'
        "  ],\n"
        '  "common_mistakes": [\n'
        '    {"mistake": "常见错误描述", "correction": "正确做法", "reason": "出错原因分析"}\n'
        "  ]\n"
        "}\n\n"
        "图示规格（只使用确有教学价值的类型，通常 1-3 幅）：\n"
        "1. geometry：坐标统一为 0~100。spec = {\n"
        '   "points":[{"id":"A","x":20,"y":60,"label":"A"}],\n'
        '   "segments":[{"from":"A","to":"B","label":"AB","dashed":false,"color":"teal"}],\n'
        '   "polygons":[{"points":["A","B","C"],"label":"△ABC","color":"blue"}],\n'
        '   "circles":[{"center":"O","radius":20,"label":"⊙O","color":"teal"}] }。\n'
        "2. number_line：spec = {"
        '"min":-5,"max":5,"step":1,'
        '"markers":[{"value":2,"label":"a","color":"red"}],'
        '"ranges":[{"from":-1,"to":3,"label":"取值范围","color":"blue"}]}。\n'
        "3. coordinate_plane / function_plot：必须提供绘图采样点，不写表达式代码。spec = {"
        '"x_min":-5,"x_max":5,"y_min":-5,"y_max":5,"x_label":"x","y_label":"y","grid":true,'
        '"series":[{"label":"y=2x","color":"teal","points":[{"x":-2,"y":-4},{"x":0,"y":0},{"x":2,"y":4}]}],'
        '"points":[{"x":1,"y":2,"label":"P"}]}。\n'
        "4. bar_chart / line_chart：spec = {"
        '"labels":["甲","乙","丙"],'
        '"series":[{"label":"人数","color":"teal","values":[12,18,15]}],'
        '"y_label":"人数"}。\n\n'
        "要求：\n"
        "1. 讲解内容必须准确、严谨，符合初中数学课标要求。\n"
        "2. 语言通俗易懂，适合初中学生阅读理解。\n"
        "3. 例题必须完整，包含题目、详细解题步骤和思路说明。\n"
        "4. 常见错误要贴合学生实际易犯的错误。\n"
        "5. content_blocks 中 Markdown 与图示交替出现，图示应紧跟解释它的正文。\n"
        "6. 数学公式使用纯文本表示（如：x²+1=0），禁止使用 LaTeX $..$ 格式。\n"
        "7. 次方必须用 Unicode 上标字符：²³⁴⁵⁶⁷⁸⁹⁰。\n"
        "8. 图示数据必须与正文结论完全一致；不能确定时宁可不生成图示。\n"
        "9. 仅输出 JSON，不要有其他文字。"
    )


def _build_user_prompt(
    kp_name: str,
    kp_description: str,
    domain: str,
    category_1: str,
    category_2: str,
    cognitive_level: str,
    difficulty_level: str,
) -> str:
    level_map = {
        "basic": "基础入门（适合刚接触该知识点的学生）",
        "intermediate": "巩固提高（适合有一定基础需要加深理解的学生）",
        "advanced": "拓展提升（适合已掌握基础需要深入理解的学生）",
    }
    parts = [
        f"【知识点名称】{kp_name}",
    ]
    if kp_description and kp_description != kp_name:
        parts.append(f"【知识点描述】{kp_description}")
    if domain:
        parts.append(f"【所属领域】{domain}")
    if category_1:
        parts.append(f"【一级分类】{category_1}")
    if category_2:
        parts.append(f"【二级分类】{category_2}")
    if cognitive_level:
        parts.append(f"【认知层次】{cognitive_level}")
    parts.append(f"【讲解深度】{level_map.get(difficulty_level, level_map['basic'])}")
    parts.append("\n请为该知识点生成一份完整、结构化的讲解内容，以 JSON 格式输出。")
    parts.append("要求至少包含 2-3 个典型例题和 2-3 个常见错误。")
    return "\n".join(parts)


async def generate_explanation(
    db: AsyncSession,
    kp_id: str,
    difficulty_level: str = "basic",
) -> Dict[str, Any]:
    """
    调用 LLM 为指定知识点生成讲解内容（不入库，返回给前端审核）。
    """
    # 1. 获取知识点信息
    kp = (await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.id == kp_id)
    )).scalar_one_or_none()
    if not kp:
        raise ValueError(f"知识点 {kp_id} 不存在")

    # 2. 获取 LLM 配置
    config_result = await db.execute(select(SystemConfig))
    configs = {c.key: c.value for c in config_result.scalars().all()}
    if not configs.get("llm_api_key"):
        raise ValueError("未配置 LLM API Key，请在系统配置中设置")

    llm = create_llm_client(configs)
    # 讲解需要更多 token
    llm.max_tokens = min(8192, max(llm.max_tokens, 4096))
    llm.temperature = max(llm.temperature, 0.3)

    # 3. 构建 prompt 并调用
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        kp_name=kp.short_name or kp.name,
        kp_description=kp.name,
        domain=kp.domain or "",
        category_1=kp.category_1 or "",
        category_2=kp.category_2 or "",
        cognitive_level=kp.cognitive_level or "",
        difficulty_level=difficulty_level,
    )

    logger.info(f"AI讲解生成: kp={kp_id}, level={difficulty_level}")
    result = await llm.extract_json(system_prompt, user_prompt, retries=2)

    # 4. 解析结果
    if not result or not isinstance(result, dict):
        raise RuntimeError("LLM 返回空结果或格式异常")

    fallback_content = result.get("content", "")
    content_blocks = normalize_content_blocks(
        result.get("content_blocks"),
        fallback_content,
    )
    content = markdown_from_blocks(content_blocks, fallback_content)
    if not content:
        raise RuntimeError("LLM 未返回有效讲解正文")

    return {
        "kp_id": kp_id,
        "title": result.get("title", kp.short_name or kp.name),
        "summary": result.get("summary", ""),
        "content": content,
        "content_blocks": content_blocks,
        "key_points": result.get("key_points", []),
        "examples": result.get("examples", []),
        "common_mistakes": result.get("common_mistakes", []),
        "difficulty_level": difficulty_level,
    }


async def save_explanation(
    db: AsyncSession,
    data: Dict[str, Any],
) -> KpExplanation:
    """将生成的讲解内容保存到数据库"""
    content_blocks = normalize_content_blocks(
        data.get("content_blocks"),
        data.get("content", ""),
    )
    content = markdown_from_blocks(content_blocks, data.get("content", ""))
    if not content:
        raise ValueError("讲解正文不能为空")

    # 获取当前最大版本号
    max_ver = (await db.execute(
        select(func.max(KpExplanation.version)).where(
            KpExplanation.kp_id == data["kp_id"],
            KpExplanation.difficulty_level == data["difficulty_level"],
        )
    )).scalar() or 0

    explanation = KpExplanation(
        kp_id=data["kp_id"],
        title=data.get("title", ""),
        content=content,
        content_blocks=json.dumps(content_blocks, ensure_ascii=False),
        summary=data.get("summary", ""),
        key_points=json.dumps(data.get("key_points", []), ensure_ascii=False),
        examples=json.dumps(data.get("examples", []), ensure_ascii=False),
        common_mistakes=json.dumps(data.get("common_mistakes", []), ensure_ascii=False),
        difficulty_level=data.get("difficulty_level", "basic"),
        version=max_ver + 1,
        status="draft",
    )
    db.add(explanation)
    await db.commit()
    await db.refresh(explanation)
    return explanation


async def list_explanations(
    db: AsyncSession,
    kp_id: str,
    page: int = 1,
    page_size: int = 10,
) -> Dict[str, Any]:
    """获取知识点的讲解列表"""
    base_query = select(KpExplanation).where(KpExplanation.kp_id == kp_id)
    total = (await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )).scalar() or 0

    items = (await db.execute(
        base_query.order_by(KpExplanation.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).scalars().all()

    return {
        "total": total,
        "items": [_explanation_to_dict(exp) for exp in items],
    }


async def get_explanation(db: AsyncSession, exp_id: int) -> Optional[Dict[str, Any]]:
    """获取单个讲解详情"""
    exp = (await db.execute(
        select(KpExplanation).where(KpExplanation.id == exp_id)
    )).scalar_one_or_none()
    if not exp:
        return None
    return _explanation_to_dict(exp)


async def delete_explanation(db: AsyncSession, exp_id: int) -> bool:
    """删除讲解"""
    exp = (await db.execute(
        select(KpExplanation).where(KpExplanation.id == exp_id)
    )).scalar_one_or_none()
    if not exp:
        return False
    await db.delete(exp)
    await db.commit()
    return True


def _explanation_to_dict(exp: KpExplanation) -> Dict[str, Any]:
    """模型转字典"""
    def _parse_json(val):
        if not val:
            return []
        try:
            return json.loads(val)
        except Exception:
            return []

    return {
        "id": exp.id,
        "kp_id": exp.kp_id,
        "title": exp.title,
        "summary": exp.summary,
        "content": exp.content,
        "content_blocks": normalize_content_blocks(
            _parse_json(exp.content_blocks),
            exp.content,
        ),
        "key_points": _parse_json(exp.key_points),
        "examples": _parse_json(exp.examples),
        "common_mistakes": _parse_json(exp.common_mistakes),
        "difficulty_level": exp.difficulty_level,
        "status": exp.status,
        "version": exp.version,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else None,
    }
