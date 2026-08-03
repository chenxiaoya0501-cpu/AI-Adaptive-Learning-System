from fastapi import APIRouter

from app.api.knowledge import router as knowledge_router
from app.api.files import router as files_router
from app.api.system import router as system_router
from app.api.extraction import router as extraction_router
from app.api.questions import router as questions_router
from app.api.chapters import router as chapters_router
from app.api.resources import router as resources_router
from app.api.analytics import router as analytics_router

router = APIRouter()

router.include_router(knowledge_router, prefix="/knowledge", tags=["知识点管理"])
router.include_router(files_router, prefix="/files", tags=["文件管理"])
router.include_router(system_router, prefix="/system", tags=["系统配置"])
router.include_router(extraction_router, prefix="/extraction", tags=["知识抽取"])
router.include_router(questions_router, prefix="/questions", tags=["题库管理"])
router.include_router(chapters_router, prefix="/chapters", tags=["章节目录"])
router.include_router(resources_router, prefix="/resources", tags=["课程与资源管理"])
router.include_router(analytics_router, prefix="/analytics", tags=["学习数据分析"])
