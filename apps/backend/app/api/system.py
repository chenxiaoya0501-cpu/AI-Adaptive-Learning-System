from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.database import get_db
from app.models.system import SystemConfig
from app.schemas.system import SystemConfigResponse, SystemConfigUpdate, LLMConfigResponse

router = APIRouter()

DEFAULT_CONFIGS = [
    {"key": "llm_api_key", "value": "", "description": "大模型API密钥"},
    {"key": "llm_base_url", "value": "https://api.deepseek.com/v1", "description": "大模型API地址"},
    {"key": "llm_model", "value": "deepseek-chat", "description": "大模型名称"},
    {"key": "llm_temperature", "value": "0.1", "description": "生成温度(0-1)"},
    {"key": "llm_max_tokens", "value": "4096", "description": "最大输出token数"},
    {"key": "extraction_batch_size", "value": "10", "description": "每次发送给LLM的条目/切片数量"},
    {"key": "extraction_llm_concurrency", "value": "2", "description": "知识点分类LLM并发数(1-8)"},
    {"key": "ocr_workers", "value": "2", "description": "扫描版PDF并行渲染线程数(1-8)"},
    {"key": "ocr_cache_enabled", "value": "true", "description": "是否缓存OCR结果以加速重跑"},
]


@router.get("/configs", response_model=List[SystemConfigResponse])
async def list_configs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig))
    configs = result.scalars().all()
    existing_keys = {c.key for c in configs}
    missing = [cfg for cfg in DEFAULT_CONFIGS if cfg["key"] not in existing_keys]
    if missing:
        for cfg in missing:
            db.add(SystemConfig(**cfg))
        await db.commit()
        result = await db.execute(select(SystemConfig))
        configs = result.scalars().all()
    return [SystemConfigResponse.model_validate(c, from_attributes=True) for c in configs]


@router.put("/configs/{key}", response_model=SystemConfigResponse)
async def update_config(key: str, data: SystemConfigUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    config = result.scalar_one_or_none()
    if not config:
        config = SystemConfig(key=key, value=data.value, description=data.description or "")
        db.add(config)
    else:
        config.value = data.value
        if data.description:
            config.description = data.description
    await db.commit()
    await db.refresh(config)
    return SystemConfigResponse.model_validate(config, from_attributes=True)


@router.get("/llm-config", response_model=LLMConfigResponse)
async def get_llm_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SystemConfig))
    configs = result.scalars().all()
    config_dict = {c.key: c.value for c in configs}
    return LLMConfigResponse(
        api_key=config_dict.get("llm_api_key", ""),
        base_url=config_dict.get("llm_base_url", "https://api.deepseek.com/v1"),
        model=config_dict.get("llm_model", "deepseek-chat"),
        temperature=float(config_dict.get("llm_temperature", "0.1")),
        max_tokens=int(config_dict.get("llm_max_tokens", "4096")),
    )
