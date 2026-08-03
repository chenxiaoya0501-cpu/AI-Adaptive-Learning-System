"""章节内容概述提取服务 - 从电子教材PDF中提取各节的核心知识点概述（后台任务模式）"""
import os
import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from sqlalchemy import select

from app.database import async_session
from app.models.chapter import TextbookChapter
from app.models.system import ExtractionTask, SystemConfig, UploadedFile
from app.services.pdf_parser import extract_pdf_text
from app.services.llm_client import create_llm_client

logger = logging.getLogger(__name__)


def _build_system_prompt() -> str:
    return (
        "你是一位经验丰富的初中数学教师，擅长分析教材内容并提炼核心知识点。\n"
        "你需要根据提供的教材某一节的文本内容，提取该节的核心知识点概述。\n\n"
        "输出格式为 JSON：\n"
        "{\n"
        '  "summaries": [\n'
        '    {"section_title": "节标题", "summary": "该节的核心知识点概述（100-200字）"}\n'
        "  ]\n"
        "}\n\n"
        "要求：\n"
        "1. 概述必须简洁精炼，突出该节最核心的知识点和概念。\n"
        "2. 用通俗易懂的语言描述，适合教师和学生快速了解该节主要内容。\n"
        "3. 包含关键定义、公式、定理、性质等核心内容。\n"
        "4. 如果一节内容涉及多个知识点，用分号分隔列举。\n"
        "5. 仅输出 JSON，不要有其他文字。"
    )


def _build_user_prompt(chapter_title: str, sections_with_text: List[Dict[str, str]]) -> str:
    """构建用户提示词，包含章标题和各节文本"""
    parts = [f"【所属章】{chapter_title}\n"]
    parts.append("请为以下各节提取内容概述：\n")
    for item in sections_with_text:
        parts.append(f"--- {item['title']} ---")
        text = item.get("text", "")
        if len(text) > 3000:
            text = text[:3000] + "…（内容截断）"
        parts.append(text if text else "（无文本内容）")
        parts.append("")
    parts.append("\n请为每一节生成简洁的核心知识点概述（100-200字），以 JSON 格式输出。")
    return "\n".join(parts)


def _normalize_title(title: str) -> str:
    """标准化标题用于模糊匹配：去除空格、全角字符、标点差异"""
    import re
    t = title.replace(" ", "").replace("\u3000", "")
    # 统一全角数字/字母为半角
    t = t.translate(str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ))
    # 统一标点：全角点号→半角点号
    t = t.replace("．", ".").replace("·", ".")
    # 去除多余标点
    t = re.sub(r"[\s\u3000]+", "", t)
    return t


def _extract_section_text_from_pages(
    pages: List[Dict[str, Any]],
    sections: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """从PDF全文中按节标题定位各节的文本内容。"""
    full_text = "\n".join(p.get("text", "") for p in pages)
    full_text_normalized = _normalize_title(full_text)
    results = []

    # 记录每个 section 在全文中的起始位置
    positions: List[int] = []  # -1 means not found

    for sec in sections:
        title = sec["title"]
        # 先尝试原始匹配
        start = full_text.find(title)
        if start >= 0:
            positions.append(start)
            continue

        # 标准化匹配
        title_norm = _normalize_title(title)
        idx = full_text_normalized.find(title_norm)
        if idx >= 0:
            # 将标准化位置映射回原始位置（近似）
            # 由于标准化会缩短字符串，用比例映射
            ratio = len(full_text) / max(len(full_text_normalized), 1)
            approx_pos = int(idx * ratio)
            # 在附近搜索确认
            search_start = max(0, approx_pos - 200)
            search_end = min(len(full_text), approx_pos + 200 + len(title))
            local = full_text[search_start:search_end]
            # 尝试在附近找到包含关键数字的位置
            import re
            digits = re.findall(r'[\d.]+', title)
            if digits:
                pattern = re.escape(digits[0])
                m = re.search(pattern, local)
                if m:
                    positions.append(search_start + m.start())
                    continue
            positions.append(approx_pos)
        else:
            positions.append(-1)

    # 根据位置提取文本
    for i, sec in enumerate(sections):
        start = positions[i]
        if start < 0:
            results.append({"title": sec["title"], "text": ""})
            continue

        # 找到下一个 section 的起始位置作为结束
        end = len(full_text)
        for j in range(i + 1, len(sections)):
            if positions[j] > start:
                end = positions[j]
                break

        title_len = len(sec["title"])
        section_text = full_text[start + title_len:end].strip()
        results.append({"title": sec["title"], "text": section_text[:4000]})

    return results


def run_summary_extraction_task(task_id: int):
    """同步入口，在后台线程中运行异步任务"""
    asyncio.run(_run_summary_extraction_async(task_id))


async def _run_summary_extraction_async(task_id: int):
    """异步执行内容概述提取任务"""
    from app.config import settings

    async with async_session() as db:
        result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return

        try:
            task.status = "running"
            task.started_at = datetime.now()
            task.progress = 5
            task.result_summary = {"stage": "init", "detail": "正在初始化…"}
            await db.commit()

            # 解析文件ID
            file_ids = []
            if task.source_file_ids:
                file_ids = [int(x.strip()) for x in task.source_file_ids.split(",") if x.strip()]
            if not file_ids:
                task.status = "failed"
                task.error_message = "未指定教材文件"
                await db.commit()
                return

            uploaded_file_id = file_ids[0]

            # 获取文件信息
            file_record = (await db.execute(
                select(UploadedFile).where(UploadedFile.id == uploaded_file_id)
            )).scalar_one_or_none()
            if not file_record:
                task.status = "failed"
                task.error_message = f"文件 {uploaded_file_id} 不存在"
                await db.commit()
                return

            pdf_path = os.path.join(settings.UPLOAD_DIR, file_record.filename)
            if not os.path.exists(pdf_path):
                task.status = "failed"
                task.error_message = "PDF 文件缺失，可能已被删除"
                await db.commit()
                return

            # 获取章节目录
            chapters = (await db.execute(
                select(TextbookChapter)
                .where(TextbookChapter.uploaded_file_id == uploaded_file_id)
                .order_by(TextbookChapter.sort_order, TextbookChapter.id)
            )).scalars().all()

            chapter_nodes = [c for c in chapters if c.level == "chapter"]
            section_nodes = [c for c in chapters if c.level == "section"]

            if not section_nodes:
                task.status = "failed"
                task.error_message = "该教材没有可提取的节目录"
                await db.commit()
                return

            sections_by_chapter: Dict[int, List] = {}
            for s in section_nodes:
                sections_by_chapter.setdefault(s.parent_id, []).append(s)

            # 提取PDF文本
            task.progress = 10
            task.result_summary = {"stage": "parsing_pdf", "detail": "正在解析PDF文本…"}
            await db.commit()

            pages = extract_pdf_text(pdf_path)

            task.progress = 25
            task.result_summary = {"stage": "parsing_pdf", "detail": "PDF解析完成，准备调用大模型…"}
            await db.commit()

            # 获取LLM配置
            config_result = await db.execute(select(SystemConfig))
            configs = {c.key: c.value for c in config_result.scalars().all()}
            if not configs.get("llm_api_key"):
                task.status = "failed"
                task.error_message = "未配置 LLM API Key，请在系统配置中设置"
                await db.commit()
                return

            llm = create_llm_client(configs)
            llm.max_tokens = min(8192, max(llm.max_tokens, 4096))
            llm.temperature = 0.2

            system_prompt = _build_system_prompt()
            total_updated = 0
            total_chapters = len(chapter_nodes)
            processed_chapters = 0

            for ch in chapter_nodes:
                secs = sections_by_chapter.get(ch.id, [])
                if not secs:
                    processed_chapters += 1
                    continue

                # 更新进度
                progress = 25 + int(processed_chapters / max(total_chapters, 1) * 70)
                task.progress = min(progress, 95)
                task.result_summary = {
                    "stage": "llm_extract",
                    "detail": f"正在提取: {ch.title}（{processed_chapters + 1}/{total_chapters} 章）",
                    "updated": total_updated,
                    "total_sections": len(section_nodes),
                }
                await db.commit()

                sec_dicts = [{"title": s.title} for s in secs]
                sections_with_text = _extract_section_text_from_pages(pages, sec_dicts)

                user_prompt = _build_user_prompt(ch.title, sections_with_text)
                logger.info(f"提取内容概述: 章={ch.title}, 节数={len(secs)}")

                try:
                    llm_result = await llm.extract_json(system_prompt, user_prompt, retries=2)
                except Exception as e:
                    logger.warning(f"LLM调用失败({ch.title}): {e}")
                    processed_chapters += 1
                    continue

                if not llm_result or not isinstance(llm_result, dict):
                    processed_chapters += 1
                    continue

                summaries = llm_result.get("summaries", [])
                if not isinstance(summaries, list):
                    processed_chapters += 1
                    continue

                summary_map = {}
                summary_map_normalized = {}
                for item in summaries:
                    if isinstance(item, dict) and "section_title" in item:
                        raw_title = item["section_title"].strip()
                        summary_map[raw_title] = item.get("summary", "")
                        summary_map_normalized[_normalize_title(raw_title)] = item.get("summary", "")

                for sec_row in secs:
                    # 精确匹配
                    summary = summary_map.get(sec_row.title.strip())
                    if not summary:
                        # 标准化匹配
                        sec_norm = _normalize_title(sec_row.title)
                        summary = summary_map_normalized.get(sec_norm)
                    if not summary:
                        # 子串匹配
                        for key, val in summary_map.items():
                            if key in sec_row.title or sec_row.title in key:
                                summary = val
                                break
                    if not summary:
                        # 标准化子串匹配
                        sec_norm = _normalize_title(sec_row.title)
                        for key_norm, val in summary_map_normalized.items():
                            if key_norm in sec_norm or sec_norm in key_norm:
                                summary = val
                                break
                    if summary:
                        sec_row.content_summary = summary
                        total_updated += 1

                await db.commit()
                processed_chapters += 1

            # 完成
            task.status = "completed"
            task.progress = 100
            task.completed_at = datetime.now()
            task.result_summary = {
                "stage": "done",
                "detail": f"已为 {total_updated}/{len(section_nodes)} 个节提取内容概述",
                "updated": total_updated,
                "total_sections": len(section_nodes),
            }
            await db.commit()
            logger.info(f"内容概述提取完成: task={task_id}, file={uploaded_file_id}, updated={total_updated}/{len(section_nodes)}")

        except Exception as e:
            logger.error(f"内容概述提取失败: {e}", exc_info=True)
            task.status = "failed"
            task.error_message = str(e)[:1000]
            await db.commit()
