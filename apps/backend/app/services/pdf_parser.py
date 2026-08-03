"""PDF解析服务 - 从课标和教材PDF中提取文本并结构化切片"""
import os
import re
import io
import json
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Tuple

import fitz  # PyMuPDF

from app.config import settings

logger = logging.getLogger(__name__)

# progress_callback(done: int, total: int, stage: str)
ProgressCallback = Optional[Callable[[int, int, str], None]]

OCR_CACHE_VERSION = "v1"
DEFAULT_OCR_DPI = 200
DEFAULT_OCR_WORKERS = 2

_ocr_reader = None
_ocr_reader_lock = threading.Lock()
_ocr_infer_lock = threading.Lock()  # EasyOCR Reader 非线程安全，推理串行；渲染可并行


def extract_pdf_text(
    pdf_path: str,
    ocr_full: bool = False,
    progress_callback: ProgressCallback = None,
    ocr_workers: int = DEFAULT_OCR_WORKERS,
    ocr_dpi: int = DEFAULT_OCR_DPI,
    use_ocr_cache: bool = True,
) -> List[Dict[str, Any]]:
    """提取PDF全文，按页返回文本。如果是扫描版PDF则自动使用OCR。
    
    Args:
        pdf_path: PDF文件路径
        ocr_full: 是否OCR全部页面。False时只OCR包含课程内容的页面范围（更快）。
        progress_callback: 可选进度回调 (done, total, stage)
        ocr_workers: OCR 并行渲染线程数（推理仍串行共享 Reader）
        ocr_dpi: 渲染 DPI
        use_ocr_cache: 是否使用按文件 hash 的 OCR 结果缓存
    """
    doc = fitz.open(pdf_path)
    pages = []

    if progress_callback:
        progress_callback(0, max(doc.page_count, 1), "detect")

    # 先检测是否为扫描版（前10页文字都为空但有图片）
    is_scanned = _detect_scanned_pdf(doc)

    if is_scanned:
        if ocr_full:
            page_range = (0, doc.page_count)
        else:
            # 先快速定位课程内容的页面范围，再只OCR那部分
            page_range = _find_curriculum_content_range(doc)
        pages = _ocr_pdf_pages(
            pdf_path,
            page_range=page_range,
            progress_callback=progress_callback,
            workers=ocr_workers,
            dpi=ocr_dpi,
            use_cache=use_ocr_cache,
        )
    else:
        total = doc.page_count or 1
        for i, page in enumerate(doc):
            text = page.get_text("text")
            pages.append({
                "page_num": page.number + 1,
                "text": text.strip(),
            })
            if progress_callback and (i % 5 == 0 or i + 1 == total):
                progress_callback(i + 1, total, "text")

    doc.close()
    return pages


def _detect_scanned_pdf(doc) -> bool:
    """检测PDF是否为扫描版（图片PDF）：前10页文字内容极少但有图片"""
    check_pages = min(10, doc.page_count)
    empty_count = 0
    for i in range(check_pages):
        page = doc[i]
        text = page.get_text("text").strip()
        images = page.get_images()
        if len(text) < 20 and len(images) > 0:
            empty_count += 1
    return empty_count >= check_pages * 0.7


def _file_sha256(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _ocr_cache_file(pdf_path: str, start: int, end: int, dpi: int) -> Path:
    digest = _file_sha256(pdf_path)
    key = f"{OCR_CACHE_VERSION}_{digest}_{start}_{end}_{dpi}"
    cache_dir = Path(settings.UPLOAD_DIR) / ".ocr_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.json"


def _load_ocr_cache(cache_path: Path) -> Optional[List[Dict[str, Any]]]:
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pages = data.get("pages")
        if isinstance(pages, list):
            return pages
    except Exception as e:
        logger.warning(f"读取 OCR 缓存失败 {cache_path}: {e}")
    return None


def _save_ocr_cache(cache_path: Path, pages: List[Dict[str, Any]]) -> None:
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"pages": pages}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"写入 OCR 缓存失败 {cache_path}: {e}")


def _get_easyocr_reader():
    """懒加载并复用全局 EasyOCR Reader（有 CUDA 时自动启用 GPU）"""
    global _ocr_reader
    if _ocr_reader is not None:
        return _ocr_reader
    with _ocr_reader_lock:
        if _ocr_reader is not None:
            return _ocr_reader
        import easyocr

        use_gpu = False
        try:
            import torch
            use_gpu = bool(torch.cuda.is_available())
        except Exception:
            use_gpu = False

        logger.info(f"初始化 EasyOCR Reader (gpu={use_gpu})")
        _ocr_reader = easyocr.Reader(["ch_sim", "en"], gpu=use_gpu)
        return _ocr_reader


def _render_page_image(pdf_path: str, page_idx: int, dpi: int):
    """在独立 Document 中渲染单页，避免共享 fitz.Document 的线程问题"""
    import numpy as np
    from PIL import Image

    doc = fitz.open(pdf_path)
    try:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return np.array(img)
    finally:
        doc.close()


def _ocr_single_page(pdf_path: str, page_idx: int, dpi: int) -> Tuple[int, str]:
    """渲染单页并 OCR。渲染可并行；推理通过锁串行。"""
    img_np = _render_page_image(pdf_path, page_idx, dpi)
    reader = _get_easyocr_reader()
    with _ocr_infer_lock:
        results = reader.readtext(img_np, detail=0)
    text = "\n".join(results).strip()
    return page_idx, text


def _ocr_pdf_pages(
    pdf_path: str,
    page_range: tuple = None,
    progress_callback: ProgressCallback = None,
    workers: int = DEFAULT_OCR_WORKERS,
    dpi: int = DEFAULT_OCR_DPI,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """使用 EasyOCR 对扫描版 PDF 进行 OCR（Reader 复用 + 并行渲染 + 可选缓存）。"""
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count

    start_page = page_range[0] if page_range else 0
    end_page = page_range[1] if page_range else page_count
    end_page = min(end_page, page_count)
    start_page = max(0, start_page)
    total = max(end_page - start_page, 0)
    if total == 0:
        return []

    cache_path = _ocr_cache_file(pdf_path, start_page, end_page, dpi) if use_cache else None
    if cache_path:
        cached = _load_ocr_cache(cache_path)
        if cached is not None:
            logger.info(f"命中 OCR 缓存: {cache_path.name} ({len(cached)} 页)")
            if progress_callback:
                progress_callback(total, total, "ocr_cache")
            return cached

    if progress_callback:
        progress_callback(0, 1, "ocr_init")

    # 预热 Reader（只加载一次）
    _get_easyocr_reader()

    page_indices = list(range(start_page, end_page))
    results_map: Dict[int, str] = {}
    workers = max(1, min(int(workers or 1), 8))
    done_count = 0

    if workers == 1 or total == 1:
        for page_idx in page_indices:
            idx, text = _ocr_single_page(pdf_path, page_idx, dpi)
            results_map[idx] = text
            done_count += 1
            if progress_callback:
                progress_callback(done_count, total, "ocr")
    else:
        # 流水线：多线程并行渲染，OCR 推理加锁串行 → 渲染与推理重叠
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(_ocr_single_page, pdf_path, page_idx, dpi)
                for page_idx in page_indices
            ]
            for fut in as_completed(futures):
                idx, text = fut.result()
                results_map[idx] = text
                done_count += 1
                if progress_callback:
                    progress_callback(done_count, total, "ocr")

    pages = [
        {"page_num": page_idx + 1, "text": results_map.get(page_idx, "")}
        for page_idx in page_indices
    ]

    if cache_path:
        _save_ocr_cache(cache_path, pages)

    return pages


def _find_curriculum_content_range(doc) -> tuple:
    """快速定位课标PDF中包含课程内容的页面范围。
    
    课标PDF（义务教育数学课程标准2022年版）结构约189页：
    - 前25%：总论、课程性质、课程目标
    - 25%-55%：课程内容（小学1-6年级+初中7-9年级知识点，含编号条目①②③）
    - 55%-100%：学业质量、课程实施、附录
    
    只需OCR课程内容部分（约55页），大幅减少OCR时间。
    """
    total_pages = doc.page_count
    
    # 课程内容通常从25%开始到55%结束
    content_start = max(0, int(total_pages * 0.25))
    content_end = min(total_pages, int(total_pages * 0.55))

    return (content_start, content_end)


# 课标一级分类名（含「统计与概率」下无二级分类的扁平结构）
KNOWN_CAT1_NAMES = [
    "数与式", "方程与不等式", "函数",
    "图形的性质", "图形的变化", "图形与坐标",
    "统计", "概率", "抽样与数据分析", "随机事件的概率",
    "综合与实践", "数据的收集", "数据的分析",
]

# 一级分类下直接 (1)(2) 内容要求、无二级分类的扁平结构
FLAT_PAREN_KP_CAT1 = {"抽样与数据分析", "随机事件的概率", "概率"}

# 课程标准分类上下文。识别到更具体的分类时，应反向刷新上级分类，
# 避免 OCR 漏掉领域标题后继续沿用上一领域（例如把“点线面角”挂到“函数”）。
CAT2_TO_CAT1 = {
    "有理数": "数与式", "实数": "数与式", "代数式": "数与式", "分式": "数与式",
    "整式": "数与式",
    "方程与方程组": "方程与不等式", "不等式与不等式组": "方程与不等式",
    "函数的概念": "函数", "一次函数": "函数", "二次函数": "函数",
    "反比例函数": "函数",
    "点线面角": "图形的性质", "点、线、面、角": "图形的性质",
    "相交线与平行线": "图形的性质",
    "三角形": "图形的性质", "四边形": "图形的性质", "圆": "图形的性质",
    "尺规作图": "图形的性质", "定义": "图形的性质", "命题": "图形的性质",
    "图形的轴对称": "图形的变化", "图形的旋转": "图形的变化",
    "图形的平移": "图形的变化", "图形的相似": "图形的变化",
    "图形的投影": "图形的变化",
    "图形的位置与坐标": "图形与坐标",
}

CAT1_TO_DOMAIN = {
    "数与式": "数与代数", "方程与不等式": "数与代数", "函数": "数与代数",
    "图形的性质": "图形与几何", "图形的变化": "图形与几何",
    "图形与坐标": "图形与几何",
    "统计": "统计与概率", "概率": "统计与概率",
    "抽样与数据分析": "统计与概率", "随机事件的概率": "统计与概率",
}


def _domain_for_cat1(category_1: str) -> str:
    for cat1_name, domain_name in CAT1_TO_DOMAIN.items():
        if cat1_name in (category_1 or ""):
            return domain_name
    return ""


def _cat1_for_cat2(category_2: str) -> str:
    normalized = re.sub(r"^\(\d+\)\s*", "", category_2 or "")
    for cat2_name, cat1_name in CAT2_TO_CAT1.items():
        if cat2_name in normalized:
            return cat1_name
    return ""


SECTION_HEADING_RE = re.compile(
    r"(?<![\u4e00-\u9fffA-Za-z0-9])[\[【\(（]?\s*"
    r"(内容要求|学业要求|教学提示)\s*[\]】\)）]?"
)


def _is_valid_cat1_name(candidate: str) -> bool:
    candidate = (candidate or "").strip()
    # 「抽样与数据分析」等略长，放宽到 12
    if not candidate or len(candidate) > 12:
        return False
    return any(
        kw == candidate or candidate.startswith(kw) or candidate.endswith(kw)
        for kw in KNOWN_CAT1_NAMES
    )


def _is_paren_numbered_kp_body(text: str) -> bool:
    """判断「(1) xxx」是知识点正文，还是短二级分类标题（如「(1) 有理数」）。

    统计与概率第四学段：一级分类下直接 (1)(2) 内容要求，无二级分类。
    """
    text = (text or "").strip()
    if not text:
        return False
    # 短标题：纯主题名
    if len(text) <= 12 and "。" not in text and "；" not in text:
        knowledge_verbs = (
            "理解", "掌握", "了解", "能", "会", "知道", "探索", "借助",
            "结合", "通过", "体会", "认识", "经历", "感知", "初步",
        )
        if not any(text.startswith(v) for v in knowledge_verbs):
            return False
    if len(text) >= 18:
        return True
    if "。" in text or "；" in text:
        return True
    knowledge_verbs = (
        "理解", "掌握", "了解", "能", "会", "知道", "探索", "借助",
        "结合", "通过", "体会", "认识", "经历", "感知", "初步",
    )
    return any(text.startswith(v) or text.startswith("进一步") for v in knowledge_verbs)


def extract_curriculum_numbered_items(pages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    从课程标准PDF中用正则表达式精确提取所有编号条目。

    支持格式：
    1. 原生文字PDF：①②③… 编号条目（常见于数与代数等，下属二级分类）
    2. OCR：行首 0/@ + 知识点动词
    3. 扁平结构：一级分类下直接 (1)(2)… 内容要求（统计与概率第四学段等，无二级分类）

    返回列表字段：number, text, typical_question, category_2, category_1_hint, domain_hint
    """
    full_text = "\n".join([p["text"] for p in pages])
    items = []

    circle_nums = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"

    current_domain = ""
    current_cat1 = ""
    current_cat2 = ""
    in_content_requirements = False  # 【内容要求】区块内才抽取课程知识点
    section_seen = False

    is_ocr_text = _detect_ocr_format(full_text)

    lines = full_text.split("\n")
    i = 0
    item_counter = 0

    while i < len(lines):
        line = lines[i].strip()

        section_match = SECTION_HEADING_RE.search(line)
        if section_match:
            section_seen = True
            section_name = section_match.group(1)
            in_content_requirements = section_name == "内容要求"
            # 每个分区必须重新建立分类上下文，不能继承上一区块。
            current_domain = ""
            current_cat1 = ""
            current_cat2 = ""
            item_counter = 0
            if not in_content_requirements:
                i += 1
                continue
            # 兼容 OCR 将“【内容要求】1. 图形的性质”粘在同一行。
            line = line[section_match.end():].strip()
            if not line:
                i += 1
                continue

        # 已明确进入“学业要求/教学提示”后，不再把其中的编号段落当作知识点。
        if section_seen and not in_content_requirements:
            i += 1
            continue

        for domain_name in ["数与代数", "图形与几何", "统计与概率", "综合与实践"]:
            if domain_name in line:
                # 离开统计扁平区进入综合与实践等时，清空一级分类，避免 (1)(2) 误挂
                if (
                    current_domain == "统计与概率"
                    and domain_name != "统计与概率"
                    and current_cat1 in FLAT_PAREN_KP_CAT1
                ):
                    current_cat1 = ""
                    current_cat2 = ""
                current_domain = domain_name

        # 分隔符含 OCR 误识别的中文句号「2。随机事件的概率」
        cat1_match = re.match(r'^(\d+)\s*[\.．。\s]\s*(.+?)$', line)
        glued_cat1 = re.match(r'^(\d+)([\u4e00-\u9fff].+)$', line)  # 「2随机事件的概率」
        if cat1_match:
            candidate = cat1_match.group(2).strip()
            if _is_valid_cat1_name(candidate):
                current_cat1 = candidate
                current_cat2 = ""
                current_domain = _domain_for_cat1(current_cat1) or current_domain
                item_counter = 0
        elif glued_cat1 and _is_valid_cat1_name(glued_cat1.group(2).strip()):
            current_cat1 = glued_cat1.group(2).strip()
            current_cat2 = ""
            current_domain = _domain_for_cat1(current_cat1) or current_domain
            item_counter = 0
        elif re.match(r'^\d+\s*[\.．。]?\s*$', line) and i + 1 < len(lines):
            # OCR 常见：单独一行「1.」下一行才是「抽样与数据分析」
            next_cand = lines[i + 1].strip()
            if _is_valid_cat1_name(next_cand):
                current_cat1 = next_cand
                current_cat2 = ""
                current_domain = _domain_for_cat1(current_cat1) or current_domain
                item_counter = 0
                i += 2
                continue
        else:
            inline_cat1 = re.search(r'(\d+)\s+([^\d\s][^\n]{2,})$', line)
            if inline_cat1:
                candidate = inline_cat1.group(2).strip()
                if _is_valid_cat1_name(candidate):
                    current_cat1 = candidate
                    current_cat2 = ""
                    current_domain = _domain_for_cat1(current_cat1) or current_domain
                    item_counter = 0

        is_numbered_item = False
        item_text_start = ""
        number_override = None
        category_2_for_item = None  # None → 用 current_cat2

        # "(1) xxx"：短标题 → 二级分类；长内容要求 → 直接作为知识点
        cat2_match = re.match(r'^[\(（]\s*(\d+)\s*[\)）]\s*(.+?)$', line)
        if cat2_match:
            num = cat2_match.group(1)
            candidate = cat2_match.group(2).strip()
            if len(candidate) >= 2:
                allow_flat_kp = (
                    in_content_requirements
                    and (
                        current_cat1 in FLAT_PAREN_KP_CAT1
                        or (
                            current_domain == "统计与概率"
                            and bool(current_cat1)
                        )
                    )
                )
                if allow_flat_kp and _is_paren_numbered_kp_body(candidate):
                    is_numbered_item = True
                    item_text_start = candidate
                    number_override = f"({num})"
                    category_2_for_item = ""  # 无二级分类
                elif not _is_paren_numbered_kp_body(candidate):
                    current_cat2 = f"({num}) {candidate}"
                    inferred_cat1 = _cat1_for_cat2(current_cat2)
                    if inferred_cat1:
                        current_cat1 = inferred_cat1
                        current_domain = _domain_for_cat1(current_cat1) or current_domain
                    item_counter = 0

        if not is_numbered_item:
            if is_ocr_text:
                is_numbered_item, item_text_start = _detect_ocr_numbered_item(line)
            else:
                if line and line[0] in circle_nums:
                    is_numbered_item = True
                    item_text_start = line[1:].strip()

        if is_numbered_item:
            if number_override is None:
                item_counter += 1
                if item_counter <= len(circle_nums):
                    number = circle_nums[item_counter - 1]
                else:
                    number = f"({item_counter})"
            else:
                number = number_override

            item_text = item_text_start
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    j += 1
                    continue
                if _is_next_item_or_heading(next_line, is_ocr_text, circle_nums):
                    break
                if re.match(r'^\d+\s*[+\-*/=]', next_line):
                    j += 1
                    break
                item_text += next_line
                j += 1
            i = j

            if item_text:
                typical_q = ""
                example_matches = re.findall(r'[\(（]例\s*(\d+)[\)）]', item_text)
                if example_matches:
                    typical_q = "、".join([f"例{n}" for n in example_matches])
                clean_text = re.sub(r'[\(（]例\s*\d+[\)）]\s*[=；;]?\s*', '', item_text).strip()
                clean_text = clean_text.lstrip('．.、 ;；=')
                clean_text = re.sub(r'\[?\d\]?标有.*$', '', clean_text).strip()
                clean_text = re.sub(r'\s*\d{1,3}\s*$', '', clean_text).strip()

                # 去掉串进正文的「学业要求」等后续块
                clean_text = SECTION_HEADING_RE.split(clean_text, maxsplit=1)[0].strip()
                clean_text = re.sub(r"\s*\d{1,3}\s*$", "", clean_text).strip()

                # 扁平结构课标条目编号通常不超过 20（抽样与数据分析有到(11)）；更高多为 OCR 误分段
                skip_flat = False
                if number_override and (
                    current_cat1 in FLAT_PAREN_KP_CAT1
                    or (current_domain == "统计与概率" and bool(current_cat1))
                ):
                    try:
                        n = int(re.search(r"\d+", number_override).group())
                        if n > 20:
                            skip_flat = True
                    except Exception:
                        pass

                if len(clean_text) >= 5 and not skip_flat:
                    cat2_val = current_cat2 if category_2_for_item is None else category_2_for_item
                    # 扁平 (1)(2) 知识点：无二级分类，后续禁止 LLM 编造
                    force_empty_cat2 = category_2_for_item == ""
                    items.append({
                        "number": number,
                        "text": clean_text,
                        "typical_question": typical_q,
                        "category_2": cat2_val,
                        "category_1_hint": current_cat1,
                        "domain_hint": current_domain,
                        "force_empty_category_2": force_empty_cat2,
                    })
        else:
            i += 1

    for item in items:
        if not item["category_1_hint"] and item["category_2"]:
            item["category_1_hint"] = _cat1_for_cat2(item["category_2"])
        if not item["domain_hint"] and item["category_1_hint"]:
            item["domain_hint"] = _domain_for_cat1(item["category_1_hint"])

    return items


def _detect_ocr_format(full_text: str) -> bool:
    """检测文本是否为OCR产出格式。
    OCR特征：没有真正的①②③字符，但有"0"或"@"开头的知识点行。
    """
    has_circle_nums = bool(re.search(r'[①②③④⑤]', full_text))
    if has_circle_nums:
        return False

    # 检查是否有OCR特征的编号行
    knowledge_verbs = ['理解', '掌握', '了解', '能', '会', '知道', '探索', '借助', '结合', '通过']
    ocr_item_count = 0
    lines = full_text.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith(('0', '@')) and len(line) > 5:
            rest = line[1:]
            if any(rest.startswith(v) or rest.lstrip().startswith(v) for v in knowledge_verbs):
                ocr_item_count += 1
    return ocr_item_count >= 5


def _detect_ocr_numbered_item(line: str):
    """检测OCR格式的编号条目行。
    OCR把①识别为"0"，把②③④等识别为"@"。
    需要区分真正的编号行和普通以0/@开头的行。
    """
    knowledge_verbs = ['理解', '掌握', '了解', '能', '会用', '会求', '会把',
                       '会运', '会画', '会', '知道', '探索', '借助', '结合',
                       '通过', '体会']
    
    if not line:
        return False, ""

    # 以"0"开头（OCR的①）
    if line[0] == '0' and len(line) > 3:
        rest = line[1:].strip()
        if any(rest.startswith(v) for v in knowledge_verbs):
            return True, rest

    # 以"@"开头（OCR的②③④⑤等）
    if line[0] == '@' and len(line) > 3:
        rest = line[1:].strip()
        if any(rest.startswith(v) for v in knowledge_verbs):
            return True, rest

    # 以"*"开头（选学内容，如 "④ * 能解简单的三元一次方程组"）
    if line.startswith('*') and len(line) > 3:
        rest = line[1:].strip()
        if any(rest.startswith(v) for v in knowledge_verbs):
            return True, "*" + rest

    return False, ""


def _is_next_item_or_heading(line: str, is_ocr: bool, circle_nums: str) -> bool:
    """判断一行是否是下一个编号条目或者分类标题"""
    # 编号条目检测
    if is_ocr:
        is_item, _ = _detect_ocr_numbered_item(line)
        if is_item:
            return True
    else:
        if line and line[0] in circle_nums:
            return True

    # 知识领域标题检测
    for domain_name in ["数与代数", "图形与几何", "统计与概率", "综合与实践"]:
        if line.strip() == domain_name or line.strip().endswith(domain_name):
            return True

    # 分类标题检测
    # 二级分类：(1) xxx / （2）xxx
    if re.match(r'^[\(（]\s*\d+\s*[\)）]', line):
        return True
    # 一级分类：带点的 "1. xxx" / "1．xxx" / OCR 误作 "2。xxx"
    if re.match(r'^\d+\s*[\.．。]\s*\S', line):
        return True
    # OCR：无点号粘连「2随机事件的概率」
    glued = re.match(r'^(\d+)([\u4e00-\u9fff].+)$', line)
    if glued and _is_valid_cat1_name(glued.group(2).strip()):
        return True
    # 一级分类（OCR格式）：数字+2个以上空格+中文 "2  方程与不等式"
    cat1_ocr_match = re.match(r'^(\d+)\s{2,}(\S+)', line)
    if cat1_ocr_match:
        candidate = cat1_ocr_match.group(2)
        if any(kw in candidate for kw in KNOWN_CAT1_NAMES):
            return True
    # 一级分类（OCR格式）：数字+1个空格+已知分类名
    cat1_single_space = re.match(r'^(\d+)\s+(\S+)', line)
    if cat1_single_space:
        candidate = cat1_single_space.group(2)
        if candidate in KNOWN_CAT1_NAMES or _is_valid_cat1_name(candidate):
            return True
    # 选学标记开头
    if line.startswith('*') and len(line) > 3:
        knowledge_verbs = ['能', '会', '理解', '掌握', '了解']
        rest = line[1:].strip()
        if any(rest.startswith(v) for v in knowledge_verbs):
            return True
    # 其他标题
    if SECTION_HEADING_RE.search(line):
        return True
    # 页码行（纯数字）
    if line.isdigit() and len(line) <= 3:
        return True

    return False


def chunk_curriculum_for_classification(items: List[Dict[str, str]], batch_size: int = 10) -> List[Dict[str, Any]]:
    """
    将正则预提取的编号条目分批，用于发送给LLM做分类。
    每批包含条目列表及其上下文信息。
    """
    chunks = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        # 构建批次文本
        lines = []
        for item in batch:
            ctx = ""
            if item["domain_hint"]:
                ctx += f"[{item['domain_hint']}]"
            if item["category_1_hint"]:
                ctx += f"[{item['category_1_hint']}]"
            if item["category_2"]:
                ctx += f"[{item['category_2']}]"
            lines.append(f"{item['number']} {item['text']}  {ctx}")
        chunks.append({
            "items": batch,
            "display_text": "\n".join(lines),
        })
    return chunks


def chunk_textbook_pdf(pages: List[Dict[str, Any]], grade: int = 7, semester: str = "上") -> List[Dict[str, Any]]:
    """
    教材PDF切片：按章节结构切分
    """
    full_text = "\n".join([p["text"] for p in pages])
    chunks = []

    # 教材常见结构：第X章 XXX / X.X 中文标题
    chapter_pattern = r'^第[一二三四五六七八九十\d]+章\s*[\u4e00-\u9fff]'
    # 小节标题必须是 "数字.数字 中文" 格式，排除纯数字/公式行
    section_pattern = r'^\d+\s*[.．]\s*\d+\s+[\u4e00-\u9fff]'

    current_chapter = ""
    current_section = ""

    lines = full_text.split("\n")
    buffer = []

    for line in lines:
        stripped = line.strip()
        chapter_match = re.match(chapter_pattern, stripped)
        section_match = re.match(section_pattern, stripped)

        if chapter_match:
            # 保存之前的buffer
            if buffer and current_chapter:
                chunks.append({
                    "content": "\n".join(buffer)[:2000],
                    "chapter": current_chapter,
                    "section": current_section,
                    "grade": grade,
                    "semester": semester,
                })
            current_chapter = stripped
            current_section = ""
            buffer = []
        elif section_match and current_chapter:
            if buffer:
                chunks.append({
                    "content": "\n".join(buffer)[:2000],
                    "chapter": current_chapter,
                    "section": current_section,
                    "grade": grade,
                    "semester": semester,
                })
            current_section = stripped
            buffer = []
        else:
            buffer.append(line)

    # 最后一块
    if buffer and current_chapter:
        chunks.append({
            "content": "\n".join(buffer)[:2000],
            "chapter": current_chapter,
            "section": current_section,
            "grade": grade,
            "semester": semester,
        })

    return chunks


def _find_page_range(pages: List[Dict[str, Any]], text_snippet: str) -> str:
    """根据文本片段找到所在页码"""
    snippet = text_snippet[:50]
    for page in pages:
        if snippet in page["text"]:
            return str(page["page_num"])
    return ""
