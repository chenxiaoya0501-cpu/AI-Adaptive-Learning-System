"""学习地图与路径规划共享的认知状态读取入口。"""
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.learning import learning_map


async def build_mastery_snapshot(
    db: AsyncSession, user_id: int, goal_id: int
) -> Dict[str, Any]:
    """读取当前目标完整的多轮掌握度快照。

    当前掌握度算法仍由 learning_map 维护；路径服务只依赖本接口，
    后续移动计算实现时无需修改路径算法。
    """
    return await learning_map.build_learning_map(db, user_id, goal_id)
