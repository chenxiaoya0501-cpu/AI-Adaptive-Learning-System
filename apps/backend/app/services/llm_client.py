"""LLM调用客户端 - 封装大模型API调用（知识抽取 / 智能关联共用）"""
import json
import logging
import asyncio
from typing import Optional, Dict, Any
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# DeepSeek 已弃用旧模型名，自动映射到当前可用模型
DEPRECATED_MODEL_MAP = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-coder": "deepseek-v4-flash",
}

# 单次请求默认超时（秒），避免标注/抽取任务永久挂起
DEFAULT_LLM_TIMEOUT = 120.0


class LLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout: float = DEFAULT_LLM_TIMEOUT,
    ):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def extract_json(
        self,
        system_prompt: str,
        user_prompt: str,
        retries: int = 2,
    ) -> Optional[Any]:
        """调用LLM并解析JSON响应（带超时与有限次重试，缓解偶发断连）"""
        last_err: Optional[Exception] = None
        for attempt in range(max(0, retries) + 1):
            content = None
            try:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        response_format={"type": "json_object"},
                    ),
                    timeout=self.timeout,
                )
                content = response.choices[0].message.content
                return json.loads(content)
            except asyncio.TimeoutError as e:
                last_err = e
                if attempt < retries:
                    logger.warning(f"LLM超时，重试 {attempt + 1}/{retries}")
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"LLM调用超时（>{self.timeout:.0f}s）")
            except json.JSONDecodeError:
                try:
                    if not content:
                        return None
                    start = content.find("{")
                    end = content.rfind("}") + 1
                    if start >= 0 and end > start:
                        return json.loads(content[start:end])
                    start = content.find("[")
                    end = content.rfind("]") + 1
                    if start >= 0 and end > start:
                        return json.loads(content[start:end])
                except Exception:
                    pass
                return None
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                retryable = any(
                    k in msg
                    for k in (
                        "connection",
                        "timeout",
                        "temporarily",
                        "429",
                        "rate limit",
                        "server disconnected",
                        "connect error",
                        "network",
                    )
                )
                if retryable and attempt < retries:
                    logger.warning(f"LLM调用失败将重试 ({attempt + 1}/{retries}): {e}")
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"LLM调用失败: {str(e)}")
        raise RuntimeError(f"LLM调用失败: {last_err}")


def create_llm_client(config: Dict[str, str]) -> LLMClient:
    """从系统配置字典创建LLM客户端（抽取与智能关联共用同一套配置）"""
    model = (config.get("llm_model") or "deepseek-v4-flash").strip()
    if model in DEPRECATED_MODEL_MAP:
        mapped = DEPRECATED_MODEL_MAP[model]
        logger.warning(f"模型名 {model} 已弃用，自动改用 {mapped}；建议在系统配置中更新")
        model = mapped

    try:
        max_tokens = int(config.get("llm_max_tokens") or 4096)
    except Exception:
        max_tokens = 4096
    # 防止配置过大被 API 拒绝；输出侧一般不需要特别大
    max_tokens = max(256, min(max_tokens, 8192))

    try:
        temperature = float(config.get("llm_temperature") or 0.1)
    except Exception:
        temperature = 0.1

    try:
        timeout = float(config.get("llm_timeout") or DEFAULT_LLM_TIMEOUT)
    except Exception:
        timeout = DEFAULT_LLM_TIMEOUT
    timeout = max(30.0, min(timeout, 600.0))

    return LLMClient(
        api_key=config.get("llm_api_key", ""),
        base_url=config.get("llm_base_url") or "https://api.deepseek.com/v1",
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
