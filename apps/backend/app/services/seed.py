"""开发环境种子数据"""
from sqlalchemy import or_, select

from app.config import settings
from app.core.security import hash_password
from app.database import async_session
from app.models.user import User
from app.models.resource import KpVideoResource
from app.models.question import Question
from app.services.exam_template_service import ensure_default_score_scheme


async def ensure_seed_student() -> None:
    account = (settings.SEED_STUDENT_ACCOUNT or "").strip()
    password = settings.SEED_STUDENT_PASSWORD or "demo123"
    if not account:
        return

    async with async_session() as db:
        existing = (
            await db.execute(
                select(User).where(
                    or_(User.email == account, User.phone == account),
                    User.role == "student",
                )
            )
        ).scalar_one_or_none()
        if existing:
            return

        is_email = "@" in account
        user = User(
            email=account if is_email else None,
            phone=None if is_email else account,
            password_hash=hash_password(password),
            nickname=settings.SEED_STUDENT_NICKNAME or "演示学生",
            role="student",
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"[seed] 已创建演示学生账号: {account} / {password}")


async def ensure_seed_exam_assets() -> None:
    """确保默认分值方案存在"""
    async with async_session() as db:
        await ensure_default_score_scheme(db)


async def ensure_seed_video_resources() -> None:
    """写入已核实的具体视频直链；重复启动不会重复创建。"""
    resources = [
        {
            "kp_id": "MATH-01-044",
            "title": "初一数学：几何图形初步",
            "url": "https://www.bilibili.com/video/BV1JV4115758/",
            "platform": "bilibili",
            "description": "共四讲，覆盖几何初步、直线、射线、线段与角。",
            "sort_order": 10,
        },
        {
            "kp_id": "MATH-01-044",
            "title": "第4章 几何图形初步",
            "url": "https://www.bilibili.com/video/BV1rE411A7bQ/",
            "platform": "bilibili",
            "description": "人教版七年级上册第四章知识点整理。",
            "sort_order": 20,
        },
        {
            "kp_id": "MATH-01-044",
            "title": "几何图形初步知识大归纳",
            "url": "https://www.youtube.com/watch?v=Xsn5YOK2jLU",
            "platform": "youtube",
            "description": "七年级数学同步课程，系统归纳几何图形初步。",
            "sort_order": 30,
        },
    ]
    async with async_session() as db:
        urls = [item["url"] for item in resources]
        existing = set(
            (
                await db.execute(
                    select(KpVideoResource.url).where(KpVideoResource.url.in_(urls))
                )
            ).scalars().all()
        )
        db.add_all([KpVideoResource(**item) for item in resources if item["url"] not in existing])
        await db.commit()


async def ensure_seed_course_questions() -> None:
    """为首个课程样例补足可连续评估的 AI 练习题。"""
    kp_id = "MATH-01-044"
    items = [
        {
            "content": "一个正方体共有多少个面、多少条棱、多少个顶点？",
            "options": {"A": "6个面、12条棱、8个顶点", "B": "6个面、8条棱、12个顶点", "C": "8个面、12条棱、6个顶点", "D": "4个面、8条棱、6个顶点"},
            "answer": "A",
            "analysis": "正方体由6个正方形面围成，共有12条棱和8个顶点。",
            "difficulty": 2,
        },
        {
            "content": "下列图形中，属于平面图形的是（　　）",
            "options": {"A": "圆柱", "B": "球", "C": "三角形", "D": "圆锥"},
            "answer": "C",
            "analysis": "三角形的所有部分都在同一平面内；圆柱、球和圆锥都是立体图形。",
            "difficulty": 1,
        },
        {
            "content": "将一个长方形绕它的一条边旋转一周，通常可以形成（　　）",
            "options": {"A": "圆柱", "B": "圆锥", "C": "球", "D": "正方体"},
            "answer": "A",
            "analysis": "长方形绕一条边旋转时，另一条边扫过圆面，整体形成圆柱。",
            "difficulty": 3,
        },
        {
            "content": "下列说法正确的是（　　）",
            "options": {"A": "点有长度和宽度", "B": "线段没有端点", "C": "球只有曲面，没有平面", "D": "圆柱有两个顶点"},
            "answer": "C",
            "analysis": "点只表示位置；线段有两个端点；圆柱没有顶点；球的表面是曲面。",
            "difficulty": 3,
        },
        {
            "content": "一个几何体由两个大小相同的圆形底面和一个曲面组成，这个几何体是（　　）",
            "options": {"A": "球", "B": "圆柱", "C": "圆锥", "D": "棱柱"},
            "answer": "B",
            "analysis": "圆柱有两个相同的圆形底面和一个曲面侧面。",
            "difficulty": 2,
        },
        {
            "content": "把一个正方体纸盒沿某些棱剪开并展开，得到的图形属于（　　）",
            "options": {"A": "立体图形", "B": "平面图形", "C": "曲面图形", "D": "无法判断"},
            "answer": "B",
            "analysis": "正方体展开图的所有部分位于同一平面内，因此是平面图形。",
            "difficulty": 2,
        },
        {
            "content": "用一个平面去截一个正方体，截面不可能是（　　）",
            "options": {"A": "三角形", "B": "四边形", "C": "六边形", "D": "圆"},
            "answer": "D",
            "analysis": "正方体的面都是平面多边形，平面截正方体所得截面是多边形，不可能是圆。",
            "difficulty": 4,
        },
    ]
    async with async_session() as db:
        contents = [item["content"] for item in items]
        existing = set(
            (
                await db.execute(
                    select(Question.content).where(
                        Question.primary_kp_id == kp_id,
                        Question.content.in_(contents),
                    )
                )
            ).scalars().all()
        )
        db.add_all(
            [
                Question(
                    bank_type="ai",
                    question_type="choice",
                    primary_kp_id=kp_id,
                    primary_kp_confidence="manual",
                    status="draft",
                    source="课程学习 AI 练习题",
                    **item,
                )
                for item in items
                if item["content"] not in existing
            ]
        )
        await db.commit()
