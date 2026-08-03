"""修复 2022 版课标 OCR 分类串行造成的知识点错误。

用法：
    python scripts/repair_curriculum_kp_categories.py --apply

脚本是一次性、可审计且幂等的：
1. 将两条几何知识点归入「图形的性质 / (1) 点线面角」；
2. 将重复的「反比例函数应用」关系合并到正式记录；
3. 删除无业务引用的重复知识点。
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "apps" / "backend" / "learning_system.db"


def repair(db_path: Path, apply: bool) -> None:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = {
            row["id"]: row
            for row in conn.execute(
                "SELECT * FROM knowledge_points WHERE id IN (?,?,?)",
                ("MATH-01-044", "MATH-01-045", "MATH-01-123"),
            )
        }

        # 已执行过时允许重复检查，不再次修改关系。
        if "MATH-01-123" not in rows:
            fixed = list(
                conn.execute(
                    """SELECT id, domain, category_1, category_2
                       FROM knowledge_points WHERE id IN (?,?) ORDER BY id""",
                    ("MATH-01-044", "MATH-01-045"),
                )
            )
            expected = ("图形与几何", "图形的性质", "(1) 点线面角")
            if len(fixed) == 2 and all(
                (row["domain"], row["category_1"], row["category_2"]) == expected
                for row in fixed
            ):
                conn.rollback()
                print("知识点分类修复已执行，无需重复处理。")
                return
            raise RuntimeError("重复记录已不存在，但几何分类未达到预期，请人工核查。")

        if set(rows) != {"MATH-01-044", "MATH-01-045", "MATH-01-123"}:
            raise RuntimeError(f"目标知识点不完整：{sorted(rows)}")
        if "几何体" not in rows["MATH-01-044"]["name"]:
            raise RuntimeError("MATH-01-044 内容不符合预期，已中止。")
        if "线段" not in rows["MATH-01-045"]["name"]:
            raise RuntimeError("MATH-01-045 内容不符合预期，已中止。")
        if "反比例函数" not in rows["MATH-01-123"]["name"]:
            raise RuntimeError("MATH-01-123 不是预期的重复反比例函数记录，已中止。")

        geometry_fields = (
            "图形与几何",
            "图形的性质",
            "(1) 点线面角",
            "七年级上册",
            "第六章　几何图形初步",
        )
        conn.execute(
            """UPDATE knowledge_points
               SET domain=?, category_1=?, category_2=?, grade=?, chapter=?,
                   name=?, updated_at=CURRENT_TIMESTAMP
               WHERE id='MATH-01-044'""",
            geometry_fields
            + ("通过实物和模型，了解从物体抽象出来的几何体、平面、直线和点等概念。",),
        )
        conn.execute(
            """UPDATE knowledge_points
               SET domain=?, category_1=?, category_2=?, grade=?, chapter=?,
                   name=?, updated_at=CURRENT_TIMESTAMP
               WHERE id='MATH-01-045'""",
            geometry_fields
            + ("会比较线段的长短，理解线段的和、差，以及线段中点的意义。",),
        )
        conn.execute(
            """UPDATE knowledge_points
               SET name='能用反比例函数解决简单实际问题。',
                   prerequisites='反比例函数图象',
                   updated_at=CURRENT_TIMESTAMP
               WHERE id='MATH-01-043'"""
        )

        duplicate_relations = list(
            conn.execute(
                """SELECT from_point_id, relation_type, weight, created_at
                   FROM knowledge_relations WHERE to_point_id=?""",
                ("MATH-01-123",),
            )
        )
        for relation in duplicate_relations:
            exists = conn.execute(
                """SELECT 1 FROM knowledge_relations
                   WHERE from_point_id=? AND to_point_id='MATH-01-043'
                     AND relation_type=?""",
                (relation["from_point_id"], relation["relation_type"]),
            ).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO knowledge_relations
                       (from_point_id, to_point_id, relation_type, weight, created_at)
                       VALUES (?, 'MATH-01-043', ?, ?, ?)""",
                    (
                        relation["from_point_id"],
                        relation["relation_type"],
                        relation["weight"],
                        relation["created_at"],
                    ),
                )

        conn.execute(
            """DELETE FROM knowledge_relations
               WHERE from_point_id='MATH-01-123' OR to_point_id='MATH-01-123'"""
        )
        deleted = conn.execute(
            "DELETE FROM knowledge_points WHERE id='MATH-01-123'"
        ).rowcount
        if deleted != 1:
            raise RuntimeError(f"重复知识点删除数量异常：{deleted}")

        if apply:
            conn.commit()
            print("修复完成：2 条几何分类已纠正，1 条反比例函数重复记录已合并删除。")
        else:
            conn.rollback()
            print("校验通过（预演模式，未写入数据库）。使用 --apply 正式执行。")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repair(args.db.resolve(), apply=args.apply)


if __name__ == "__main__":
    main()
