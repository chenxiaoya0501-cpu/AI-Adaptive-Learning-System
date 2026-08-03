from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import os

from app.api import router as api_router
from app.api.student import router as student_router
from app.database import engine, Base
from app.config import settings
from app import models  # noqa: F401 — 注册全部模型
from app.db_migrate import ensure_sqlite_columns
from app.core.security import try_decode_access_token
from app.services.seed import (
    ensure_seed_course_questions,
    ensure_seed_exam_assets,
    ensure_seed_student,
    ensure_seed_video_resources,
)

app = FastAPI(
    title="自适应学习系统 API",
    version="0.1.0",
    description="中考数学AI自适应学习系统 — 共享后端（Admin + Student）",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Admin frontend
        "http://localhost:5174",  # Student frontend
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def block_student_token_on_admin_writes(request: Request, call_next):
    """学生 JWT 不得调用 Admin 写接口；Admin 前端仍可无 Token 访问（当前阶段）。"""
    path = request.url.path
    method = request.method.upper()
    if (
        method in {"POST", "PUT", "PATCH", "DELETE"}
        and path.startswith("/api/")
        and not path.startswith("/api/v1/student")
    ):
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
            payload = try_decode_access_token(token)
            if payload and payload.get("role") == "student":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "学生账号无权调用管理端写接口"},
                )
    return await call_next(request)


app.include_router(api_router, prefix="/api")
app.include_router(student_router, prefix="/api/v1/student")

os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_sqlite_columns(conn)
    await ensure_seed_student()
    await ensure_seed_exam_assets()
    await ensure_seed_video_resources()
    await ensure_seed_course_questions()


@app.get("/health")
async def health():
    return {"status": "ok"}
