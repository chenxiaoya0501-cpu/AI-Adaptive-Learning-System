"""知识点名称AI生成服务 - 调用大模型将知识点描述概括为简短名称"""
import asyncio
import logging
from typing import List, Optional

from sqlalchemy import select, or_

from app.database import async_session
from app.models.knowledge import KnowledgePoint
from app.models.system import SystemConfig
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)

KP_SHORTNAME_PROMPT = """你是初中数学教研助手。请为以下知识点生成简短名称（2-8个字）。

要求：
1. 名称要精炼准确，能概括知识点的核心内容
2. 优先使用数学术语，如：有理数、一元二次方程、全等三角形、概率初步
3. 如果知识点描述中明确提到某个概念，直接提取该概念名称
4. 每个知识点只给一个名称

请严格输出 JSON 对象：
{{
  "results": [
    {{"index": 0, "short_name": "有理数"}},
    {{"index": 1, "short_name": "一元二次方程"}}
  ]
}}

results 数量必须与输入知识点数量一致，index 从 0 开始。"""


# 进度状态（简单内存存储，单进程足够）
_task_progress = {}


def get_shortname_task_progress(task_key: str) -> Optional[dict]:
    return _task_progress.get(task_key)


def run_shortname_task(task_key: str, mode: str, domain: Optional[str], grade: Optional[str], point_ids: Optional[List[str]] = None):
    """入口：在线程池中调用"""
    asyncio.run(_run_shortname_async(task_key, mode, domain, grade, point_ids))


async def _run_shortname_async(
    task_key: str,
    mode: str,
    domain: Optional[str],
    grade: Optional[str],
    point_ids: Optional[List[str]] = None,
):
    _task_progress[task_key] = {"status": "running", "progress": 0, "total": 0, "done": 0, "error": None}

    async with async_session() as db:
        try:
            # 读取LLM配置
            config_result = await db.execute(select(SystemConfig))
            configs = {c.key: c.value for c in config_result.scalars().all()}
            if not configs.get("llm_api_key"):
                _task_progress[task_key] = {
                    "status": "failed", "progress": 100, "total": 0, "done": 0,
                    "error": "未配置LLM API密钥，请到「系统配置 → 运行设置」填写",
                }
                return

            llm = create_llm_client(configs)

            # 查询知识点
            q = select(KnowledgePoint)
            if point_ids:
                q = q.where(KnowledgePoint.id.in_(point_ids))
            if mode == "empty_only":
                q = q.where(or_(KnowledgePoint.short_name.is_(None), KnowledgePoint.short_name == ""))
            if domain:
                q = q.where(KnowledgePoint.domain == domain)
            if grade:
                q = q.where(KnowledgePoint.grade.contains(grade))
            q = q.order_by(KnowledgePoint.id)

            result = await db.execute(q)
            kps = list(result.scalars().all())

            if not kps:
                _task_progress[task_key] = {
                    "status": "completed", "progress": 100, "total": 0, "done": 0,
                    "error": "没有符合条件的知识点需要处理",
                }
                return

            total = len(kps)
            _task_progress[task_key]["total"] = total
            done = 0
            batch_size = 20

            for i in range(0, total, batch_size):
                batch = kps[i:i + batch_size]
                lines = []
                for idx, kp in enumerate(batch):
                    name_text = (kp.name or "").strip()[:200]
                    cat_info = f"（{kp.category_1 or ''}/{kp.category_2 or ''}）" if kp.category_1 or kp.category_2 else ""
                    lines.append(f"知识点{idx}: {name_text}{cat_info}")

                user_prompt = f"请为以下{len(batch)}个知识点生成简短名称：\n\n" + "\n".join(lines)

                try:
                    data = await llm.extract_json(KP_SHORTNAME_PROMPT, user_prompt)
                except Exception as e:
                    logger.warning(f"知识点名称生成LLM失败 batch={i}: {e}")
                    done += len(batch)
                    _task_progress[task_key].update({"done": done, "progress": min(int(done / total * 100), 99)})
                    continue

                # 解析结果
                results = []
                if isinstance(data, dict):
                    results = data.get("results") or []
                elif isinstance(data, list):
                    results = data

                result_map = {}
                for r in results:
                    if isinstance(r, dict):
                        try:
                            result_map[int(r.get("index", -1))] = str(r.get("short_name", "")).strip()
                        except (ValueError, TypeError):
                            continue

                # 写回
                for idx, kp in enumerate(batch):
                    short = result_map.get(idx, "")
                    if short and len(short) <= 50:
                        kp.short_name = short

                done += len(batch)
                _task_progress[task_key].update({"done": done, "progress": min(int(done / total * 100), 99)})
                await db.commit()

            _task_progress[task_key] = {
                "status": "completed", "progress": 100, "total": total, "done": done, "error": None,
            }
            logger.info(f"知识点名称生成完成: {done}/{total}")

        except Exception as e:
            logger.error(f"知识点名称生成失败: {e}", exc_info=True)
            _task_progress[task_key] = {
                "status": "failed", "progress": 100, "total": 0, "done": 0,
                "error": str(e)[:500],
            }
