"""教材章节目录抽取服务"""
import os
import re
import logging
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy import select, delete

from app.database import async_session
from app.config import settings
from app.models.system import ExtractionTask, UploadedFile, SystemConfig
from app.models.chapter import TextbookChapter
from app.services.pdf_parser import extract_pdf_text

logger = logging.getLogger(__name__)

CHAPTER_RE = re.compile(r'^第[一二三四五六七八九十百零\d]+章\s*.+')
SECTION_RE = re.compile(r'^\d+\s*[.．]\s*\d+\s+[\u4e00-\u9fff].*')


def extract_toc_from_pages(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从PDF页文本提取章/节目录（去重保序）"""
    full_text = "\n".join([p.get("text") or "" for p in pages])
    chapters: List[Dict[str, Any]] = []
    current_chapter = None
    seen_chapters = set()
    seen_sections = set()

    for line in full_text.split("\n"):
        stripped = line.strip()
        if not stripped or len(stripped) > 80:
            continue

        if CHAPTER_RE.match(stripped):
            # 规范化标题
            title = re.sub(r'\s+', ' ', stripped)
            if title in seen_chapters:
                continue
            seen_chapters.add(title)
            current_chapter = {"title": title, "level": "chapter", "sections": []}
            chapters.append(current_chapter)
            continue

        if current_chapter and SECTION_RE.match(stripped):
            title = re.sub(r'\s+', ' ', stripped)
            key = f"{current_chapter['title']}::{title}"
            if key in seen_sections:
                continue
            seen_sections.add(key)
            current_chapter["sections"].append({"title": title, "level": "section"})

    return chapters


async def run_chapter_toc_extraction(task_id: int):
    """执行章节目录抽取（由 extraction 后台任务调用）"""
    async with async_session() as db:
        result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return

        try:
            task.status = "running"
            task.started_at = datetime.now()
            task.progress = 5
            await db.commit()

            file_ids = []
            if task.source_file_ids:
                file_ids = [int(x.strip()) for x in task.source_file_ids.split(",") if x.strip()]
            if not file_ids:
                task.status = "failed"
                task.error_message = "未选择教材文件"
                await db.commit()
                return

            total_chapters = 0
            total_sections = 0
            processed = 0
            file_results = []

            for fid in file_ids:
                res = await db.execute(select(UploadedFile).where(UploadedFile.id == fid))
                file_record = res.scalar_one_or_none()
                if not file_record:
                    file_results.append({"file_id": fid, "ok": False, "reason": "文件不存在"})
                    continue

                # 章节目录抽取允许从资料上传中的任意 PDF 选择；
                # 若原标记为课标但实际是课本，抽取时纠正为教材，便于章节目录页展示
                if file_record.file_type != "textbook":
                    file_record.file_type = "textbook"
                    logger.info(f"文件{fid}已标记为教材（章节目录抽取）")

                pdf_path = os.path.join(settings.UPLOAD_DIR, file_record.filename)
                if not os.path.exists(pdf_path):
                    file_results.append({
                        "file_id": fid,
                        "name": file_record.original_name,
                        "ok": False,
                        "reason": "PDF文件缺失",
                    })
                    continue

                task.progress = 10 + int(processed / max(len(file_ids), 1) * 70)
                await db.commit()

                pages = extract_pdf_text(pdf_path)
                toc = extract_toc_from_pages(pages)

                # 仅覆盖「当前这本」的旧目录，不影响其他教材（多本之间是累加）
                await db.execute(delete(TextbookChapter).where(TextbookChapter.uploaded_file_id == fid))

                grade = file_record.grade or ""
                # grade 可能是 "7"，转成「七年级」展示用
                grade_map = {"7": "七年级", "8": "八年级", "9": "九年级"}
                grade_label = grade_map.get(str(grade), str(grade) if grade else "")
                semester = file_record.semester or ""

                ch_count = 0
                sec_count = 0
                sort_i = 0
                for ch in toc:
                    sort_i += 1
                    chapter_row = TextbookChapter(
                        uploaded_file_id=fid,
                        subject="数学",
                        grade=grade_label or grade,
                        semester=semester,
                        parent_id=None,
                        level="chapter",
                        title=ch["title"],
                        sort_order=sort_i,
                        status="draft",
                    )
                    db.add(chapter_row)
                    await db.flush()
                    ch_count += 1
                    total_chapters += 1

                    for sec in ch.get("sections") or []:
                        sort_i += 1
                        db.add(TextbookChapter(
                            uploaded_file_id=fid,
                            subject="数学",
                            grade=grade_label or grade,
                            semester=semester,
                            parent_id=chapter_row.id,
                            level="section",
                            title=sec["title"],
                            sort_order=sort_i,
                            status="draft",
                        ))
                        sec_count += 1
                        total_sections += 1

                await db.commit()
                processed += 1
                file_results.append({
                    "file_id": fid,
                    "name": file_record.original_name,
                    "ok": True,
                    "chapters": ch_count,
                    "sections": sec_count,
                })

            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.now()
            task.result_summary = {
                "files": processed,
                "chapters": total_chapters,
                "sections": total_sections,
                "per_file": file_results,
            }
            await db.commit()
            logger.info(f"章节目录抽取完成 task={task_id}: {total_chapters}章 {total_sections}节 / {processed}本")

        except Exception as e:
            logger.error(f"章节目录抽取失败: {e}", exc_info=True)
            task.status = "failed"
            task.error_message = str(e)[:1000]
            await db.commit()
