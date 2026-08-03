"""章节/年级段标注服务 - 根据多本教材PDF综合为已有知识点标注grade和chapter"""
import os
import re
import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict, OrderedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.system import UploadedFile, SystemConfig
from app.models.knowledge import KnowledgePoint
from app.services.pdf_parser import extract_pdf_text, chunk_textbook_pdf
from app.services.llm_client import create_llm_client, LLMClient
from app.config import settings

logger = logging.getLogger(__name__)


TEXTBOOK_MATCHING_PROMPT = """你是一位初中数学教育专家。现有一批从课程标准中提取的知识点，请根据给定的教材内容，判断哪些知识点在这本教材中被**首次正式教学**，并为其匹配年级段和所属章节。

已有知识点列表（格式：ID|名称）：
{points_text}

本教材基本信息：**{grade_info}**

教材文本内容（含章节标注）：
{textbook_text}

请输出JSON格式：
{{
  "matches": [
    {{
      "point_id": "知识点ID（优先填写）",
      "point_name": "知识点名称（必须与上方列表一致）",
      "grade": "{grade_info}",
      "chapter": "所属章节（必须是教材中的章节标题，如：第一章 有理数）",
      "confidence": "high/medium/low"
    }}
  ]
}}

重要规则：
1. 只匹配该章节中**首次正式教学**的知识点，不要匹配仅仅是"提到"或"复习"的知识点
2. grade字段统一填写"{grade_info}"
3. chapter字段填写教材中的章标题（从文本中的[章节: ...]标注获取），不要填小节标题
4. 优先填写 point_id；若无 ID 则 point_name 必须从上方列表完整复制
5. 如果该段落中没有直接教学某个知识点，则不要输出
6. confidence：high=首次系统讲解, medium=较多涉及, low=少量相关
7. 宁可少匹配也不要错误匹配！"""


GRADE_ORDER = {
    "七年级上册": 1, "七年级下册": 2,
    "八年级上册": 3, "八年级下册": 4,
    "九年级上册": 5, "九年级下册": 6,
}

CONFIDENCE_SCORE = {"high": 3, "medium": 2, "low": 1}

# 单章送入 LLM 的最大字符数（避免超长请求）
MAX_CHAPTER_CHARS = 5000
# 每批合并的章数
DEFAULT_CHAPTERS_PER_BATCH = 2


def _merge_chunks_by_chapter(chunks: List[Dict[str, Any]], max_chars: int = MAX_CHAPTER_CHARS) -> List[Dict[str, Any]]:
    """将细粒度小节切片合并为「按章」单元，大幅减少 LLM 调用次数。"""
    by_ch: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for c in chunks:
        key = (c.get("chapter") or "").strip() or "未分章"
        if key not in by_ch:
            by_ch[key] = {
                "chapter": key,
                "section": "",
                "content": "",
                "grade": c.get("grade"),
                "semester": c.get("semester"),
            }
        if len(by_ch[key]["content"]) >= max_chars:
            continue
        part = ""
        if c.get("section"):
            part += f"\n[{c['section']}]\n"
        part += c.get("content") or ""
        remain = max_chars - len(by_ch[key]["content"])
        if remain > 0:
            by_ch[key]["content"] += part[:remain]
    return list(by_ch.values())


def _format_points_compact(points: List[KnowledgePoint]) -> str:
    """紧凑知识点列表，降低每次请求的 token 体积。"""
    lines = []
    for p in points:
        name = (p.name or "").replace("\n", " ").strip()
        if len(name) > 60:
            name = name[:60] + "…"
        lines.append(f"{p.id}|{name}")
    return "\n".join(lines)


async def run_annotation_task(textbook_file_ids: List[int], mode: str = "overwrite", task_id: Optional[int] = None, point_ids: Optional[List[str]] = None):
    """异步执行标注任务：解析多本教材PDF，综合权衡为知识点匹配最佳的grade/chapter"""
    from app.models.system import ExtractionTask as TaskModel
    from datetime import datetime

    async with async_session() as db:
        task = None
        try:
            if task_id:
                res = await db.execute(select(TaskModel).where(TaskModel.id == task_id))
                task = res.scalar_one_or_none()
                if task:
                    task.status = "running"
                    task.started_at = datetime.now()
                    task.progress = 0
                    task.result_summary = {"stage": "init", "detail": "正在准备标注任务…"}
                    await db.commit()

            config_result = await db.execute(select(SystemConfig))
            configs = config_result.scalars().all()
            config_dict = {c.key: c.value for c in configs}

            if not config_dict.get("llm_api_key"):
                logger.error("标注任务：未配置LLM API Key")
                await _update_files_status(db, textbook_file_ids, "failed", {"error": "未配置LLM API Key"})
                if task:
                    task.status = "failed"
                    task.error_message = "未配置LLM API Key"
                    await db.commit()
                return

            llm = create_llm_client(config_dict)
            await _update_files_status(db, textbook_file_ids, "annotating", None)

            kp_query = select(KnowledgePoint)
            if point_ids:
                kp_query = kp_query.where(KnowledgePoint.id.in_(point_ids))
            points_result = await db.execute(kp_query)
            all_points = list(points_result.scalars().all())
            existing_points = {p.name: p for p in all_points}
            points_by_id = {p.id: p for p in all_points}

            if not existing_points:
                await _update_files_status(db, textbook_file_ids, "failed", {"error": "没有知识点数据，请先进行知识点抽取"})
                if task:
                    task.status = "failed"
                    task.error_message = "没有知识点数据，请先进行知识点抽取"
                    await db.commit()
                return

            points_text = _format_points_compact(all_points)

            try:
                chapters_per_batch = max(1, min(5, int(config_dict.get("extraction_batch_size", "2"))))
                # batch_size 对标注含义改为「每批章数」；配置偏大时压到合理范围
                if chapters_per_batch > 3:
                    chapters_per_batch = DEFAULT_CHAPTERS_PER_BATCH
            except (TypeError, ValueError):
                chapters_per_batch = DEFAULT_CHAPTERS_PER_BATCH

            candidates: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

            if task:
                task.progress = 2
                task.result_summary = {
                    "stage": "parsing_pdf",
                    "detail": f"正在解析 {len(textbook_file_ids)} 本教材…",
                }
                await db.commit()

            file_entries = []
            total_batches = 0
            for file_id in textbook_file_ids:
                res = await db.execute(select(UploadedFile).where(UploadedFile.id == file_id))
                fr = res.scalar_one_or_none()
                if not fr:
                    continue
                pdf_path = os.path.join(settings.UPLOAD_DIR, fr.filename)
                if not os.path.exists(pdf_path):
                    logger.warning(f"标注任务：文件不存在 {pdf_path}")
                    continue

                pages = extract_pdf_text(pdf_path)
                grade_num = int(fr.grade) if fr.grade else 7
                semester = fr.semester or "上"
                raw_chunks = chunk_textbook_pdf(pages, grade=grade_num, semester=semester)
                chapters = _merge_chunks_by_chapter(raw_chunks)
                n_batches = max(1, (len(chapters) + chapters_per_batch - 1) // chapters_per_batch) if chapters else 0
                file_entries.append({
                    "record": fr,
                    "chapters": chapters,
                    "n_batches": n_batches,
                })
                total_batches += n_batches
                logger.info(
                    f"标注任务：{fr.original_name} 原始切片 {len(raw_chunks)} → 合并为 {len(chapters)} 章，{n_batches} 批"
                )

            if task:
                task.progress = 5
                task.result_summary = {
                    "stage": "llm_match",
                    "detail": f"解析完成，共 {total_batches} 批待匹配（按章合并）",
                    "total_batches": total_batches,
                }
                await db.commit()

            if total_batches == 0:
                if task:
                    task.status = "failed"
                    task.error_message = "未能从教材中识别出章节结构"
                    await db.commit()
                await _update_files_status(db, textbook_file_ids, "failed", {"error": "未能识别章节结构"})
                return

            processed_batches = 0

            for entry in file_entries:
                file_record = entry["record"]
                chapters = entry["chapters"]
                if not chapters:
                    logger.warning(f"标注任务：{file_record.original_name} 未能识别出章节结构，跳过")
                    continue

                fname = file_record.original_name or ""
                grade_info = _detect_grade_from_filename(fname, file_record.grade, file_record.semester)
                grade_order = GRADE_ORDER.get(grade_info, 99)

                for i in range(0, len(chapters), chapters_per_batch):
                    batch = chapters[i:i + chapters_per_batch]
                    batch_parts = []
                    for c in batch:
                        chapter_ctx = f"[章节: {c['chapter']}]" if c.get("chapter") else ""
                        batch_parts.append(f"{chapter_ctx}\n{c['content']}")
                    batch_text = "\n\n---\n\n".join(batch_parts)

                    prompt = TEXTBOOK_MATCHING_PROMPT.format(
                        points_text=points_text,
                        grade_info=grade_info,
                        textbook_text=batch_text,
                    )

                    try:
                        result_data = await llm.extract_json(
                            "你是初中数学教育专家，请根据教材内容为知识点匹配年级段和章节。",
                            prompt,
                        )
                    except Exception as llm_err:
                        logger.warning(
                            f"标注任务：LLM调用失败({file_record.original_name} batch {i}): {llm_err}"
                        )
                        result_data = None

                    if result_data and "matches" in result_data:
                        for match in result_data["matches"]:
                            point_id = (match.get("point_id") or "").strip()
                            point_name = (match.get("point_name") or "").strip()
                            new_grade = (match.get("grade") or "").strip()
                            new_chapter = (match.get("chapter") or "").strip()
                            confidence = (match.get("confidence") or "medium").strip().lower()
                            if not new_grade or not new_chapter:
                                continue

                            # 优先用 ID 定位，避免长名称错位
                            resolved_name = None
                            if point_id and point_id in points_by_id:
                                resolved_name = points_by_id[point_id].name
                            elif point_name:
                                resolved_name = point_name
                            if not resolved_name:
                                continue

                            candidates[resolved_name].append({
                                "grade": new_grade,
                                "chapter": new_chapter,
                                "confidence": confidence,
                                "grade_order": grade_order,
                            })

                    processed_batches += 1
                    if task:
                        progress = 5 + int(processed_batches / total_batches * 85)
                        task.progress = min(progress, 90)
                        task.result_summary = {
                            "stage": "llm_match",
                            "detail": (
                                f"{file_record.original_name} · "
                                f"批次 {processed_batches}/{total_batches} · "
                                f"已收集候选 {len(candidates)}"
                            ),
                            "processed_batches": processed_batches,
                            "total_batches": total_batches,
                            "candidate_points": len(candidates),
                        }
                        await db.commit()

                    logger.info(
                        f"标注任务：{file_record.original_name} "
                        f"{min(i + chapters_per_batch, len(chapters))}/{len(chapters)} 章"
                    )

            logger.info(f"标注任务：所有教材处理完毕，开始综合投票，候选知识点 {len(candidates)} 个")
            if task:
                task.progress = 92
                task.result_summary = {
                    "stage": "voting",
                    "detail": f"综合投票中，候选 {len(candidates)} 个知识点",
                    "candidate_points": len(candidates),
                }
                await db.commit()

            total_matched = 0
            for point_name, votes in candidates.items():
                matched_point = None
                if point_name in existing_points:
                    matched_point = existing_points[point_name]
                else:
                    matched_point = _fuzzy_match_point(point_name, existing_points)
                if not matched_point:
                    continue

                best = _select_best_match(votes)
                if not best:
                    continue

                if mode == "overwrite":
                    matched_point.grade = best["grade"]
                    matched_point.chapter = best["chapter"]
                else:
                    if matched_point.grade and best["grade"] not in matched_point.grade:
                        matched_point.grade = matched_point.grade + "; " + best["grade"]
                    elif not matched_point.grade:
                        matched_point.grade = best["grade"]
                    if matched_point.chapter and best["chapter"] not in matched_point.chapter:
                        matched_point.chapter = matched_point.chapter + "; " + best["chapter"]
                    elif not matched_point.chapter:
                        matched_point.chapter = best["chapter"]
                total_matched += 1

            await db.commit()
            await _update_files_status(db, textbook_file_ids, "parsed", {"annotated_points": total_matched})

            if task:
                task.status = "completed"
                task.progress = 100
                task.completed_at = datetime.now()
                task.result_summary = {
                    "matched_points": total_matched,
                    "total_files": len(textbook_file_ids),
                    "total_batches": total_batches,
                }
                await db.commit()

            logger.info(f"标注任务完成：综合 {len(textbook_file_ids)} 本教材，共标注 {total_matched} 个知识点")

        except Exception as e:
            logger.error(f"标注任务异常: {e}", exc_info=True)
            try:
                await _update_files_status(db, textbook_file_ids, "failed", {"error": str(e)[:500]})
                if task:
                    task.status = "failed"
                    task.error_message = str(e)[:1000]
                    await db.commit()
            except Exception:
                try:
                    async with async_session() as db2:
                        await _update_files_status(db2, textbook_file_ids, "failed", {"error": str(e)[:500]})
                        if task_id:
                            res = await db2.execute(select(TaskModel).where(TaskModel.id == task_id))
                            t = res.scalar_one_or_none()
                            if t:
                                t.status = "failed"
                                t.error_message = str(e)[:1000]
                                await db2.commit()
                except Exception as inner_e:
                    logger.error(f"标注任务：无法更新失败状态: {inner_e}")


def _select_best_match(votes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从多个候选中选出最佳匹配。"""
    if not votes:
        return None

    score_map: Dict[tuple, float] = defaultdict(float)
    for v in votes:
        key = (v["grade"], v["chapter"])
        conf_score = CONFIDENCE_SCORE.get(v["confidence"], 1)
        early_bonus = max(0, (7 - v["grade_order"]) * 0.5)
        score_map[key] += conf_score + early_bonus

    best_key = max(score_map, key=score_map.get)
    for v in votes:
        if (v["grade"], v["chapter"]) == best_key:
            return v
    return votes[0]


async def _update_files_status(db: AsyncSession, file_ids: List[int], status: str, parse_result: Optional[Dict]):
    """批量更新文件状态"""
    for fid in file_ids:
        result = await db.execute(select(UploadedFile).where(UploadedFile.id == fid))
        file_record = result.scalar_one_or_none()
        if file_record:
            file_record.status = status
            if parse_result is not None:
                file_record.parse_result = parse_result
    await db.commit()


def _fuzzy_match_point(name: str, existing_points: Dict[str, Any]) -> Optional[Any]:
    """模糊匹配知识点：先精确匹配，再尝试包含匹配"""
    if not name:
        return None

    if name in existing_points:
        return existing_points[name]

    for point_name, point in existing_points.items():
        if name in point_name and len(name) > 8:
            return point
        if point_name in name and len(point_name) > 8:
            return point

    name_prefix = name[:15]
    if len(name_prefix) >= 8:
        for point_name, point in existing_points.items():
            if point_name.startswith(name_prefix):
                return point

    return None


def _detect_grade_from_filename(filename: str, grade_field: Optional[str], semester_field: Optional[str]) -> str:
    """从文件名中智能提取年级段信息"""
    grade_map = {"7": "七", "8": "八", "9": "九"}

    match = re.search(r'([七八九789])年级\s*([上下])[册学期]?', filename)
    if match:
        grade_char = match.group(1)
        if grade_char in grade_map:
            grade_char = grade_map[grade_char]
        semester_char = match.group(2)
        return f"{grade_char}年级{semester_char}册"

    if grade_field:
        grade_char = grade_map.get(str(grade_field), str(grade_field))
        semester_char = semester_field or "上"
        return f"{grade_char}年级{semester_char}册"

    return "七年级上册"
