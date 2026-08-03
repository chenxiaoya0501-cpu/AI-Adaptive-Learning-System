"""知识点抽取服务 - 从课标/教材PDF中通过LLM提取结构化知识点"""
import os
import re
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

from sqlalchemy import select, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.system import ExtractionTask, UploadedFile, SystemConfig
from app.models.knowledge import KnowledgePoint, KnowledgeRelation
from app.services.pdf_parser import extract_pdf_text, extract_curriculum_numbered_items, chunk_curriculum_for_classification
from app.services.llm_client import create_llm_client, LLMClient
from app.services.knowledge_relation_sync import sync_prerequisite_names
from app.config import settings

logger = logging.getLogger(__name__)

_sync_engine = None


def _get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.DATABASE_URL_SYNC,
            connect_args={"check_same_thread": False},
        )
    return _sync_engine


def _sync_update_task_progress(task_id: int, progress: int, summary: Optional[Dict] = None):
    """在同步 PDF/OCR 阶段回写进度（此时事件循环被阻塞，无法 await）"""
    try:
        eng = _get_sync_engine()
        with eng.begin() as conn:
            if summary is not None:
                conn.execute(
                    text(
                        "UPDATE extraction_tasks SET progress=:p, result_summary=:s WHERE id=:id"
                    ),
                    {"p": int(progress), "s": json.dumps(summary, ensure_ascii=False), "id": task_id},
                )
            else:
                conn.execute(
                    text("UPDATE extraction_tasks SET progress=:p WHERE id=:id"),
                    {"p": int(progress), "id": task_id},
                )
    except Exception as e:
        logger.warning(f"同步更新任务进度失败 task={task_id}: {e}")


# ===================== 课标分类提示词（用于对已提取的编号条目做分类） =====================
CURRICULUM_CLASSIFY_PROMPT = """你是一位专业的初中数学课程标准分析专家。

以下是从课程标准中预提取的编号条目（①②③...），每条后面的方括号是系统自动识别的上下文提示（可能不完全准确）。
请你为每个条目确认/修正其所属的知识领域、一级分类、二级分类，并判断能力等级。

课程标准的层级结构：
- 知识领域：数与代数 / 图形与几何 / 统计与概率 / 综合与实践
  - 一级分类（如：数与式、方程与不等式、函数）
    - 二级分类（如：(1)有理数、(2)实数、(3)整式、(4)分式）

能力等级判断规则：
- 了解：知道、识别、描述、列举
- 理解：理解、说明、解释、表示
- 掌握：掌握、计算、求解、应用
- 运用：运用、分析、综合、探索
（多个动词取最高级别）

请为每个条目输出分类结果，JSON格式：
{{
  "classifications": [
    {{
      "number": "①",
      "domain": "知识领域（四选一）",
      "category_1": "一级分类",
      "category_2": "二级分类（无则空字符串）",
      "cognitive_level": "了解/理解/掌握/运用"
    }}
  ]
}}

注意：
1. 输出的条目数量必须与输入完全一致，不要遗漏、不要新增！
2. 若上下文提示中没有二级分类（方括号里只有领域和一级分类），则 category_2 必须为 ""，不要自行编造（如「数据的集中趋势」「随机事件」等）！
3. 「抽样与数据分析」「随机事件的概率」下直接是 (1)(2)… 内容条目，本身就是知识点，没有二级分类。"""




# ===================== 关系抽取提示词 =====================
RELATION_EXTRACTION_PROMPT = """你是一位数学教育专家。请分析以下知识点列表，识别它们之间的依赖关系。

知识点列表（格式：[ID] 知识点名称）：
{points_text}

请输出JSON格式，使用知识点的ID来标识：
{{
  "relations": [
    {{
      "from_id": "前置/被依赖的知识点ID（如MATH-01-001）",
      "to_id": "后续/依赖方的知识点ID（如MATH-01-005）",
      "type": "关系类型（prerequisite/related）",
      "reason": "简要说明关系原因"
    }}
  ]
}}

关系类型说明（只有两种）：
- prerequisite: 前置依赖——from是to的前置知识，学to之前必须先学from
- related: 相关——from和to属于同类知识或有类比关系，没有严格先后顺序

重要规则：
1. from_id和to_id必须从上方列表中的[ID]里精确复制，不要自己编造
2. 只输出确定性高的关系，不确定的不要输出
3. 每对知识点之间只输出一种最主要的关系
4. 只使用prerequisite和related两种类型，不要输出其他类型"""


def _normalize_cat2_spacing(cat2: str) -> str:
    """确保 category_2 格式为 '(N) 名称'，编号后有一个空格。"""
    m = re.match(r'^\((\d+)\)\s*(.*)', cat2)
    if m:
        return f"({m.group(1)}) {m.group(2).strip()}"
    return cat2


def _resolve_category_2(llm_cat2: str, pre_cat2: str) -> str:
    """在 LLM 返回的 category_2 和正则预提取的 category_2 之间择优。

    规则：
    1. 预提取值已有 (N) 编号前缀 → 优先使用（格式最规范）。
    2. LLM 值有 (N) 编号前缀 → 使用 LLM 值。
    3. 两者都没有编号 → 若预提取非空则用预提取，否则用 LLM。
    4. LLM 返回的纯名称与预提取的名称部分一致 → 用预提取（保留编号）。
    """
    llm_val = (llm_cat2 or "").strip()
    pre_val = (pre_cat2 or "").strip()

    _NUM_PREFIX = re.compile(r"^\(\d+\)")

    pre_has_num = bool(_NUM_PREFIX.search(pre_val))
    llm_has_num = bool(_NUM_PREFIX.search(llm_val))

    if pre_has_num:
        return _normalize_cat2_spacing(pre_val)
    if llm_has_num:
        return _normalize_cat2_spacing(llm_val)
    # 两者都没有编号：优先非空的预提取
    if pre_val:
        return pre_val
    return llm_val


def run_extraction_task(task_id: int):
    """同步入口，在后台线程中运行异步任务"""
    asyncio.run(_run_extraction_async(task_id))


async def _run_extraction_async(task_id: int):
    """异步执行知识抽取任务"""
    async with async_session() as db:
        try:
            result = await db.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                return

            # 章节目录抽取不依赖 LLM
            if task.task_type == "chapter_toc_extraction":
                from app.services.chapter_toc_service import run_chapter_toc_extraction
                await run_chapter_toc_extraction(task_id)
                return

            task.status = "running"
            task.started_at = datetime.now()
            await db.commit()

            # 获取LLM配置
            config_result = await db.execute(select(SystemConfig))
            configs = config_result.scalars().all()
            config_dict = {c.key: c.value for c in configs}

            if not config_dict.get("llm_api_key"):
                task.status = "failed"
                task.error_message = "未配置LLM API密钥，请先在系统配置中设置"
                await db.commit()
                return

            llm = create_llm_client(config_dict)

            if task.task_type == "knowledge_extraction":
                await _extract_knowledge_merged(db, task, llm, config_dict)
            elif task.task_type == "relation_extraction":
                await _extract_relations(db, task, llm)
            else:
                task.status = "failed"
                task.error_message = f"未知任务类型: {task.task_type}"
                await db.commit()

        except Exception as e:
            async with async_session() as db2:
                result = await db2.execute(select(ExtractionTask).where(ExtractionTask.id == task_id))
                task = result.scalar_one_or_none()
                if task:
                    task.status = "failed"
                    task.error_message = str(e)[:1000]
                    await db2.commit()


async def _extract_knowledge_merged(db: AsyncSession, task: ExtractionTask, llm: LLMClient, config_dict: Dict):
    """合并多文件的知识点抽取任务：
    1. 先处理课标PDF，抽取知识领域/一级分类/二级分类/知识点/典型题目
    2. 再处理教材PDF，匹配年级段/所属章节/依赖知识点
    3. 去重：同名知识点不覆盖，只补充缺失字段
    """
    # 解析文件ID列表
    file_ids = []
    if task.source_file_ids:
        file_ids = [int(fid.strip()) for fid in task.source_file_ids.split(",") if fid.strip()]

    if not file_ids:
        task.status = "failed"
        task.error_message = "未选择源文件"
        await db.commit()
        return

    # 加载所有文件记录
    file_records = []
    for fid in file_ids:
        res = await db.execute(select(UploadedFile).where(UploadedFile.id == fid))
        record = res.scalar_one_or_none()
        if record:
            file_records.append(record)

    if not file_records:
        task.status = "failed"
        task.error_message = "源文件记录不存在"
        await db.commit()
        return

    # 仅处理课标文件（教材标注已独立为annotation_service）
    curriculum_files = [f for f in file_records if f.file_type == "curriculum"]
    if not curriculum_files:
        task.status = "failed"
        task.completed_at = datetime.now()
        task.error_message = "选中的文件不是课程标准文件，请先在资料上传中修正文件类型"
        task.result_summary = {"extracted_points": 0, "total_files": 0}
        await db.commit()
        return

    missing_files = [
        f.original_name or f.filename
        for f in curriculum_files
        if not os.path.exists(os.path.join(settings.UPLOAD_DIR, f.filename))
    ]
    if missing_files:
        task.status = "failed"
        task.completed_at = datetime.now()
        task.error_message = f"源文件不存在或部署时未保留：{'、'.join(missing_files)}"
        task.result_summary = {
            "extracted_points": 0,
            "total_files": len(curriculum_files),
        }
        await db.commit()
        return

    # 预加载已有知识点（用于去重和补充）
    existing_result = await db.execute(select(KnowledgePoint))
    existing_points = {p.name: p for p in existing_result.scalars().all()}

    # 全局序号计数器
    global_seq = len(existing_points)
    total_extracted = 0
    total_steps = len(curriculum_files)
    current_step = 0

    # ========== 阶段1: 处理课标PDF（正则预提取 + LLM分类） ==========
    for file_record in curriculum_files:
        pdf_path = os.path.join(settings.UPLOAD_DIR, file_record.filename)
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"源文件不存在：{file_record.original_name or file_record.filename}")

        file_record.status = "parsing"
        task.progress = 2
        task.error_message = None
        # 用 result_summary 临时展示阶段（完成后会被正式结果覆盖）
        task.result_summary = {"stage": "parsing_pdf", "detail": "正在解析课标PDF（扫描版需OCR，较慢）"}
        await db.commit()

        # 从文件名识别学科
        subject = "数学"
        fname = file_record.original_name or ""
        if "英语" in fname:
            subject = "英语"
        elif "语文" in fname:
            subject = "语文"
        elif "物理" in fname:
            subject = "物理"

        # PDF/OCR 阶段进度：2% ~ 45%（同步回写，避免界面一直停在 0%）
        task_id_for_cb = task.id

        def _pdf_progress(done: int, total: int, stage: str):
            total = max(total, 1)
            if stage == "ocr_init":
                pct = 5
                detail = "正在加载OCR引擎…"
            elif stage == "ocr_cache":
                pct = 45
                detail = f"命中OCR缓存，已加载 {done}/{total} 页"
            elif stage in ("ocr", "text"):
                pct = 5 + int(done / total * 40)  # 5~45
                detail = f"正在解析PDF {done}/{total} 页（{stage}）"
            else:
                pct = 3
                detail = "正在检测PDF类型…"
            _sync_update_task_progress(task_id_for_cb, min(pct, 45), {
                "stage": stage,
                "detail": detail,
                "done": done,
                "total": total,
            })

        # OCR 加速参数（可在系统配置调整）
        try:
            ocr_workers = max(1, min(8, int(config_dict.get("ocr_workers", "2"))))
        except (TypeError, ValueError):
            ocr_workers = 2
        use_ocr_cache = str(config_dict.get("ocr_cache_enabled", "true")).lower() in (
            "1", "true", "yes", "on",
        )

        # 第一步：用正则从PDF中精确提取所有①②③编号条目
        pages = extract_pdf_text(
            pdf_path,
            progress_callback=_pdf_progress,
            ocr_workers=ocr_workers,
            use_ocr_cache=use_ocr_cache,
        )
        numbered_items = extract_curriculum_numbered_items(pages)

        task.progress = 48
        task.result_summary = {
            "stage": "llm_classify",
            "detail": f"已提取 {len(numbered_items)} 条课标条目，开始大模型分类",
            "numbered_items": len(numbered_items),
        }
        await db.commit()

        if not numbered_items:
            file_record.status = "parsed"
            current_step += 1
            await db.commit()
            continue

        # 第二步：分批发送给LLM做分类（支持有限并发）
        try:
            batch_size = max(1, min(30, int(config_dict.get("extraction_batch_size", "10"))))
        except (TypeError, ValueError):
            batch_size = 10
        try:
            llm_concurrency = max(1, min(8, int(config_dict.get("extraction_llm_concurrency", "2"))))
        except (TypeError, ValueError):
            llm_concurrency = 2

        batches = chunk_curriculum_for_classification(numbered_items, batch_size)
        sem = asyncio.Semaphore(llm_concurrency)

        async def _classify_one(batch_idx: int, batch_data: Dict):
            items_in_batch = batch_data["items"]
            display_text = batch_data["display_text"]
            user_prompt = f"请为以下{len(items_in_batch)}个课标编号条目做分类：\n\n{display_text}"
            try:
                async with sem:
                    result = await llm.extract_json(CURRICULUM_CLASSIFY_PROMPT, user_prompt)
                cls_list = []
                if result and "classifications" in result:
                    cls_list = result["classifications"] or []
                return batch_idx, items_in_batch, cls_list, None
            except Exception as e:
                logger.warning(f"课标分类批次 {batch_idx + 1} 失败，将跳过: {e}")
                return batch_idx, items_in_batch, [], str(e)

        classify_tasks = [
            asyncio.create_task(_classify_one(i, b)) for i, b in enumerate(batches)
        ]
        finished_batches = 0
        failed_batches = 0
        # 先并发分类，再按课标条目顺序入库，保证 ID/列表顺序与原文一致
        batch_results: List[tuple] = []

        for fut in asyncio.as_completed(classify_tasks):
            batch_idx, items_in_batch, cls_list, batch_err = await fut
            if batch_err:
                failed_batches += 1
                cls_list = []
            batch_results.append((batch_idx, items_in_batch, cls_list, batch_err))

            finished_batches += 1
            sub_progress = min(finished_batches / max(len(batches), 1), 1.0)
            overall = 45 + int(sub_progress * 50)
            task.progress = min(overall, 95)
            detail = f"大模型分类中 {finished_batches}/{len(batches)}（并发{llm_concurrency}）"
            if failed_batches:
                detail += f"，跳过失败 {failed_batches} 批"
            task.result_summary = {
                "stage": "llm_classify",
                "detail": detail,
                "extracted_points": total_extracted,
                "failed_batches": failed_batches,
            }
            await db.commit()

        if failed_batches and failed_batches >= len(batches):
            raise RuntimeError(
                f"全部 {failed_batches} 批大模型分类均失败（多为网络断连），请检查 API 后重试"
            )

        batch_results.sort(key=lambda r: r[0])
        task.result_summary = {
            "stage": "llm_classify",
            "detail": "分类完成，按课标顺序写入知识点…",
            "extracted_points": total_extracted,
            "failed_batches": failed_batches,
        }
        await db.commit()

        for batch_idx, items_in_batch, cls_list, batch_err in batch_results:
            # 优先按 number 对齐；缺失时回退到下标
            by_number: Dict[str, Dict] = {}
            for c in cls_list:
                if not isinstance(c, dict):
                    continue
                num = c.get("number")
                if num is not None and str(num) not in by_number:
                    by_number[str(num)] = c

            for idx, item in enumerate(items_in_batch):
                point_name = item["text"]
                if not point_name:
                    continue

                cls = by_number.get(str(item.get("number")))
                if cls is None:
                    cls = cls_list[idx] if idx < len(cls_list) else {}
                if not isinstance(cls, dict):
                    cls = {}

                force_empty_cat2 = bool(item.get("force_empty_category_2"))
                if force_empty_cat2:
                    cat2 = ""
                else:
                    cat2 = _resolve_category_2(
                        llm_cat2=cls.get("category_2", ""),
                        pre_cat2=item.get("category_2", ""),
                    )

                if point_name in existing_points:
                    supplement_data = {
                        "domain": cls.get("domain", item["domain_hint"]),
                        "category_1": cls.get("category_1", item["category_1_hint"]),
                        "category_2": cat2,
                        "cognitive_level": cls.get("cognitive_level", ""),
                        "typical_question": item.get("typical_question", ""),
                        "force_empty_category_2": force_empty_cat2,
                    }
                    _supplement_point(existing_points[point_name], supplement_data, subject)
                else:
                    domain = cls.get("domain", "") or item["domain_hint"]
                    cat1 = cls.get("category_1", "") or item["category_1_hint"]
                    cog_level = cls.get("cognitive_level", "")

                    global_seq += 1
                    point_id = _generate_point_id(domain, global_seq)
                    new_point = KnowledgePoint(
                        id=point_id,
                        subject=subject,
                        domain=domain,
                        category_1=cat1,
                        category_2=cat2,
                        name=point_name,
                        typical_questions=item.get("typical_question", ""),
                        cognitive_level=cog_level,
                        source="curriculum",
                        status="draft",
                    )
                    db.add(new_point)
                    existing_points[point_name] = new_point
                    total_extracted += 1

            task.progress = min(95 + int((batch_idx + 1) / max(len(batches), 1) * 4), 99)
            task.result_summary = {
                "stage": "llm_classify",
                "detail": f"按课标顺序写入 {batch_idx + 1}/{len(batches)}",
                "extracted_points": total_extracted,
                "failed_batches": failed_batches,
            }
            await db.commit()

        file_record.status = "parsed"
        current_step += 1
        await db.commit()

    # 没有任何知识点时不能把任务标记为成功，否则管理端会出现“完成但无数据”。
    if not existing_points:
        task.status = "failed"
        task.progress = 100
        task.completed_at = datetime.now()
        task.error_message = "未从课程标准文件中抽取到任何知识点，请检查PDF内容和大模型配置"
        task.result_summary = {
            "extracted_points": 0,
            "total_files": len(curriculum_files),
        }
        await db.commit()
        return

    # 完成
    task.status = "completed"
    task.progress = 100
    task.completed_at = datetime.now()
    task.result_summary = {
        "extracted_points": total_extracted,
        "total_files": len(curriculum_files),
    }
    await db.commit()


def _supplement_point(existing: KnowledgePoint, new_data: Dict, subject: str = "数学"):
    """补充已有知识点的缺失字段；扁平无二级分类时强制清空 category_2。"""
    if not existing.subject:
        existing.subject = subject
    if not existing.domain and new_data.get("domain"):
        existing.domain = new_data["domain"]
    if not existing.category_1 and new_data.get("category_1"):
        existing.category_1 = new_data["category_1"]
    if new_data.get("force_empty_category_2"):
        existing.category_2 = ""
    elif not existing.category_2 and new_data.get("category_2"):
        existing.category_2 = new_data["category_2"]
    if not existing.typical_questions and new_data.get("typical_question"):
        existing.typical_questions = new_data["typical_question"]
    if not existing.cognitive_level and new_data.get("cognitive_level"):
        existing.cognitive_level = new_data["cognitive_level"]


async def _extract_relations(db: AsyncSession, task: ExtractionTask, llm: LLMClient):
    """抽取知识点之间的关系"""
    import logging
    logger = logging.getLogger(__name__)

    result = await db.execute(select(KnowledgePoint).order_by(KnowledgePoint.id))
    points = result.scalars().all()

    if not points:
        task.status = "failed"
        task.error_message = "没有知识点数据，请先进行知识点抽取"
        await db.commit()
        return

    logger.info(f"关系抽取：共 {len(points)} 个知识点")

    # 建立ID集合用于验证LLM返回的ID
    valid_ids = {p.id for p in points}

    # 按领域分组处理
    domain_groups: Dict[str, List] = {}
    for p in points:
        domain = p.domain or "其它"
        if domain not in domain_groups:
            domain_groups[domain] = []
        domain_groups[domain].append(p)

    # 计算总批次数用于进度
    BATCH_SIZE = 30  # 每批最多30个知识点，避免prompt过长
    total_batches = 0
    batched_groups: List[tuple] = []  # [(domain, batch_points)]
    for domain, group_points in domain_groups.items():
        for i in range(0, len(group_points), BATCH_SIZE):
            batch = group_points[i:i + BATCH_SIZE]
            batched_groups.append((domain, batch))
            total_batches += 1

    logger.info(f"关系抽取：{len(domain_groups)} 个领域，分为 {total_batches} 批处理")

    processed = 0
    total_relations = 0
    skipped_invalid = 0

    for domain, batch_points in batched_groups:
        points_text = "\n".join([
            f"- [{p.id}] {p.name}（{p.category_1 or ''}/{p.category_2 or ''}，{p.grade or '?'}）"
            for p in batch_points
        ])

        prompt = RELATION_EXTRACTION_PROMPT.format(points_text=points_text)

        try:
            result_data = await llm.extract_json(
                "你是数学教育知识图谱专家，请分析知识点间的依赖关系。",
                prompt,
            )
        except Exception as llm_err:
            logger.warning(f"关系抽取：LLM调用失败(领域={domain}): {llm_err}")
            processed += 1
            task.progress = min(int(processed / total_batches * 100), 99)
            await db.commit()
            continue

        if result_data and "relations" in result_data:
            logger.info(f"关系抽取：领域={domain}，LLM返回 {len(result_data['relations'])} 条关系")

            for rel in result_data["relations"]:
                # 优先用ID匹配（新prompt要求返回ID）
                from_id = rel.get("from_id", "").strip()
                to_id = rel.get("to_id", "").strip()
                rel_type = rel.get("type", "prerequisite").strip()

                # 验证关系类型（只保留prerequisite和related）
                if rel_type not in ("prerequisite", "related"):
                    rel_type = "prerequisite"

                # 验证ID有效性
                if from_id not in valid_ids or to_id not in valid_ids:
                    skipped_invalid += 1
                    continue
                if from_id == to_id:
                    continue

                # 检查是否已存在
                try:
                    existing = await db.execute(
                        select(KnowledgeRelation).where(
                            KnowledgeRelation.from_point_id == from_id,
                            KnowledgeRelation.to_point_id == to_id,
                            KnowledgeRelation.relation_type == rel_type,
                        )
                    )
                    if not existing.scalar_one_or_none():
                        relation = KnowledgeRelation(
                            from_point_id=from_id,
                            to_point_id=to_id,
                            relation_type=rel_type,
                        )
                        db.add(relation)
                        total_relations += 1
                except Exception as db_err:
                    logger.warning(f"关系抽取：写入关系失败 {from_id}->{to_id}: {db_err}")
        else:
            logger.warning(f"关系抽取：领域={domain}，LLM未返回有效数据: {result_data}")

        processed += 1
        task.progress = min(int(processed / total_batches * 100), 99)
        await db.commit()

    task.status = "completed"
    task.progress = 100
    task.completed_at = datetime.now()
    task.result_summary = {"total_relations": total_relations, "skipped_invalid_ids": skipped_invalid}
    await sync_prerequisite_names(db)
    await db.commit()
    logger.info(f"关系抽取完成：共 {total_relations} 条关系，跳过无效ID {skipped_invalid} 条")



def _generate_point_id(domain: str, seq: int) -> str:
    """生成知识点ID: MATH-{领域编码}-{序号}"""
    domain_codes = {
        "数与代数": "01",
        "图形与几何": "02",
        "统计与概率": "03",
        "综合与实践": "04",
    }
    domain_code = domain_codes.get(domain, "00")
    return f"MATH-{domain_code}-{seq:03d}"
