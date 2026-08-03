"""启动时补齐 SQLite 缺失列 / 修正过期配置（create_all 不会 ALTER 已有表）"""
import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# DeepSeek 旧模型名 → 当前可用名
_DEPRECATED_LLM_MODELS = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-coder": "deepseek-v4-flash",
}


async def ensure_sqlite_columns(conn: AsyncConnection):
    """为 questions 等表补充新列，并修正过期 LLM 模型名（仅 SQLite）"""
    dialect = conn.engine.dialect.name
    if dialect != "sqlite":
        return

    alters: list = [
        (
            "textbook_chapters",
            "content_summary",
            "ALTER TABLE textbook_chapters ADD COLUMN content_summary TEXT",
        ),
        ("questions", "primary_kp_id", "ALTER TABLE questions ADD COLUMN primary_kp_id VARCHAR(50)"),
        ("questions", "primary_kp_confidence", "ALTER TABLE questions ADD COLUMN primary_kp_confidence VARCHAR(20)"),
        ("questions", "secondary_kp_ids", "ALTER TABLE questions ADD COLUMN secondary_kp_ids JSON"),
        (
            "learning_goals",
            "mastery_status",
            "ALTER TABLE learning_goals ADD COLUMN mastery_status VARCHAR(30) DEFAULT 'pending_test'",
        ),
        (
            "exam_structure_templates",
            "category_score_stats",
            "ALTER TABLE exam_structure_templates ADD COLUMN category_score_stats JSON",
        ),
        (
            "test_questions",
            "source_exam_paper_id",
            "ALTER TABLE test_questions ADD COLUMN source_exam_paper_id INTEGER",
        ),
        (
            "questions",
            "ability_dimension",
            "ALTER TABLE questions ADD COLUMN ability_dimension VARCHAR(100)",
        ),
        (
            "test_questions",
            "ability_dimension",
            "ALTER TABLE test_questions ADD COLUMN ability_dimension VARCHAR(100)",
        ),
        (
            "test_papers",
            "assessment_status",
            "ALTER TABLE test_papers ADD COLUMN assessment_status VARCHAR(20)",
        ),
        (
            "test_papers",
            "assessment_json",
            "ALTER TABLE test_papers ADD COLUMN assessment_json JSON",
        ),
        (
            "kp_explanations",
            "content_blocks",
            "ALTER TABLE kp_explanations ADD COLUMN content_blocks TEXT",
        ),
    ]

    for table, column, sql in alters:
        try:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            cols = {row[1] for row in result.fetchall()}
            if column not in cols:
                await conn.execute(text(sql))
                logger.info(f"已为 {table} 添加列 {column}")
        except Exception as e:
            logger.warning(f"迁移列 {table}.{column} 跳过: {e}")

    # 修正已失效的 DeepSeek 模型名（知识抽取 / 智能关联共用）
    try:
        result = await conn.execute(
            text("SELECT value FROM system_configs WHERE key = 'llm_model'")
        )
        row = result.fetchone()
        if row and row[0] in _DEPRECATED_LLM_MODELS:
            new_model = _DEPRECATED_LLM_MODELS[row[0]]
            await conn.execute(
                text("UPDATE system_configs SET value = :v WHERE key = 'llm_model'"),
                {"v": new_model},
            )
            logger.info(f"已将过期模型 {row[0]} 更新为 {new_model}")
    except Exception as e:
        logger.warning(f"迁移 llm_model 跳过: {e}")

    # 回填组卷快照的源试卷 ID（供学生端解析 [IMG:] 图片）
    try:
        result = await conn.execute(text("PRAGMA table_info(test_questions)"))
        cols = {row[1] for row in result.fetchall()}
        if "source_exam_paper_id" in cols:
            await conn.execute(
                text(
                    """
                    UPDATE test_questions
                    SET source_exam_paper_id = (
                        SELECT q.exam_paper_id FROM questions q
                        WHERE q.id = test_questions.source_question_id
                    )
                    WHERE source_exam_paper_id IS NULL
                      AND source_question_id IS NOT NULL
                    """
                )
            )
    except Exception as e:
        logger.warning(f"回填 test_questions.source_exam_paper_id 跳过: {e}")

    # 清理一题多条作答脏数据，并补唯一索引（模型里有 UniqueConstraint，旧库可能未建）
    try:
        await conn.execute(
            text(
                """
                DELETE FROM test_answers
                WHERE id NOT IN (
                    SELECT MAX(id) FROM test_answers
                    GROUP BY test_paper_id, test_question_id
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_test_answer_paper_question
                ON test_answers (test_paper_id, test_question_id)
                """
            )
        )
        logger.info("已去重 test_answers 并确保唯一索引")
    except Exception as e:
        logger.warning(f"迁移 test_answers 唯一约束跳过: {e}")

    # 回填组卷快照能力维度
    try:
        result = await conn.execute(text("PRAGMA table_info(test_questions)"))
        cols = {row[1] for row in result.fetchall()}
        if "ability_dimension" in cols:
            await conn.execute(
                text(
                    """
                    UPDATE test_questions
                    SET ability_dimension = (
                        SELECT q.ability_dimension FROM questions q
                        WHERE q.id = test_questions.source_question_id
                    )
                    WHERE ability_dimension IS NULL
                      AND source_question_id IS NOT NULL
                    """
                )
            )
    except Exception as e:
        logger.warning(f"回填 test_questions.ability_dimension 跳过: {e}")
