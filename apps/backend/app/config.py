from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./learning_system.db"
    DATABASE_URL_SYNC: str = "sqlite:///./learning_system.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    UPLOAD_DIR: str = "./uploads"

    # JWT / Auth
    SECRET_KEY: str = "dev-learning-system-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days (dev-friendly)

    # Dev seed student (created on startup if missing)
    SEED_STUDENT_ACCOUNT: str = "demo@local"
    SEED_STUDENT_PASSWORD: str = "demo123"
    SEED_STUDENT_NICKNAME: str = "演示学生"

    # LLM defaults (can be overridden via UI)
    LLM_API_KEY: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None
    LLM_MODEL: str = "deepseek-chat"

    class Config:
        env_file = ".env"


settings = Settings()
