from fastapi import APIRouter

from app.api.student.auth import router as auth_router
from app.api.student.assets import router as assets_router
from app.api.student.goals import router as goals_router
from app.api.student.tests import router as tests_router
from app.api.student.learning_paths import router as learning_paths_router
from app.api.student.courses import router as courses_router

router = APIRouter()
router.include_router(learning_paths_router, tags=["学生-学习路径"])
router.include_router(courses_router, tags=["学生-课程学习"])
router.include_router(auth_router, tags=["学生-认证"])
router.include_router(assets_router, tags=["学生-资产只读"])
router.include_router(goals_router, tags=["学生-学习目标"])
router.include_router(tests_router, tags=["学生-测评组卷"])
