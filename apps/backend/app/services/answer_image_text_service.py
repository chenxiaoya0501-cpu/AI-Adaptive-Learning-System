"""将题目答案中的公式图片 [IMG:...] 批量 OCR/识别为纯文本。"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.question import Question
from app.services.pdf_parser import _get_easyocr_reader, _ocr_infer_lock

logger = logging.getLogger(__name__)

IMG_TOKEN_RE = re.compile(r"\[IMG:([^,\]]+)(?:,([\d.]+),([\d.]+))?\]")

# 公式小图 OCR 字符集（避免中文噪声灌入一次式）
_MATH_ALLOWLIST = (
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "=+-×÷·./()[]<>≤≥√π°²³^,;:"
)


def _paper_image_path(paper_id: Optional[int], filename: str) -> Optional[str]:
    if not paper_id or not filename:
        return None
    path = os.path.join(
        settings.UPLOAD_DIR, "papers", f"paper_{paper_id}_images", filename
    )
    return path if os.path.isfile(path) else None


def _upscale_for_ocr(im: Image.Image, min_h: int = 96) -> Image.Image:
    w, h = im.size
    scale = max(3, int(np.ceil(min_h / max(h, 1))))
    out = im.resize((max(1, w * scale), max(1, h * scale)), Image.Resampling.LANCZOS)
    return ImageOps.autocontrast(out)


def _is_flat_line_formula(gray: np.ndarray) -> bool:
    """扁长图（如 y=-10x+600）是行内一次式，不是分式。"""
    h, w = gray.shape[:2]
    if h < 1:
        return True
    return (w / float(h)) >= 2.2


def _find_fraction_bar_y(gray: np.ndarray) -> Optional[int]:
    """检测水平分数线；扁长行内公式一律不走分式。"""
    h, w = gray.shape[:2]
    if h < 12 or w < 8:
        return None
    # 扁长图：中间墨迹常是字母笔画像素，极易误判分数线
    if _is_flat_line_formula(gray):
        return None
    binary = gray < 200
    row_ink = binary.mean(axis=1)
    mid0, mid1 = int(h * 0.22), int(h * 0.78)
    if mid1 <= mid0:
        return None
    best_y = None
    best_score = 0.0
    for y in range(mid0, mid1):
        ink = float(row_ink[y])
        if ink < 0.28:
            continue
        neighbors = []
        if y > 0:
            neighbors.append(float(row_ink[y - 1]))
        if y + 1 < h:
            neighbors.append(float(row_ink[y + 1]))
        neigh = max(neighbors) if neighbors else 0.0
        # 真分数线：本行很黑，邻行明显更淡（细线）
        if neigh > ink * 0.55:
            continue
        col_span = float(binary[y].mean())
        score = ink * 1.2 + col_span * 0.8 - neigh * 0.8
        min_ink = 0.28 if w >= h else 0.32
        if ink >= min_ink and col_span >= 0.3 and score > best_score:
            best_score = score
            best_y = y
    if best_y is None:
        return None
    top = gray[: max(1, best_y - 1), :]
    bot = gray[min(h, best_y + 2) :, :]
    if top.size == 0 or bot.size == 0:
        return None
    if top.mean() > 248 or bot.mean() > 248:
        return None
    if binary[: max(1, best_y - 1)].mean() < 0.02:
        return None
    if binary[min(h, best_y + 2) :].mean() < 0.02:
        return None
    # 上下内容高度不能差太悬殊到像整行被切开
    top_h, bot_h = top.shape[0], bot.shape[0]
    if min(top_h, bot_h) / max(top_h, bot_h, 1) < 0.25:
        return None
    return best_y


def _detect_fraction_by_bar(gray: np.ndarray) -> Optional[Tuple[str, str]]:
    """中间有分数线时标记为可分割上下区域。"""
    if _find_fraction_bar_y(gray) is None:
        return None
    return "top_bot", ""


def _find_partial_fraction_bar(gray: np.ndarray) -> Optional[Tuple[int, int, int]]:
    """检测局部分数线（如分式右侧还跟根号），返回 (bar_y, x0, x1)。"""
    h, w = gray.shape[:2]
    if h < 20 or w < 20:
        return None
    if _is_flat_line_formula(gray):
        return None
    binary = gray < 200
    mid0, mid1 = int(h * 0.22), int(h * 0.78)
    best: Optional[Tuple[int, int, int]] = None
    best_score = 0.0
    for y in range(mid0, mid1):
        row = binary[y]
        # 邻行应更淡（细分数线）
        neigh = 0.0
        if y > 0:
            neigh = max(neigh, float(binary[y - 1].mean()))
        if y + 1 < h:
            neigh = max(neigh, float(binary[y + 1].mean()))
        i = 0
        while i < w:
            if not row[i]:
                i += 1
                continue
            j = i
            while j < w and row[j]:
                j += 1
            run_w = j - i
            # 局部横线：占整宽 12%~70%，且该段邻行更淡
            if run_w >= max(10, int(w * 0.12)) and run_w <= int(w * 0.72):
                seg = binary[y, i:j]
                above = binary[max(0, y - 1), i:j].mean() if y > 0 else 0.0
                below = binary[min(h - 1, y + 1), i:j].mean() if y + 1 < h else 0.0
                if float(seg.mean()) < 0.7:
                    i = j
                    continue
                if max(above, below) > 0.45:
                    i = j
                    continue
                top_ink = float(binary[: max(1, y - 1), i:j].mean()) if y > 1 else 0.0
                bot_ink = float(binary[min(h, y + 2) :, i:j].mean()) if y + 2 < h else 0.0
                if top_ink < 0.04 or bot_ink < 0.04:
                    i = j
                    continue
                score = run_w / w + top_ink + bot_ink - max(above, below)
                if score > best_score:
                    best_score = score
                    # 向两侧略扩，避免切掉分子/分母边缘
                    pad = max(2, run_w // 10)
                    best = (y, max(0, i - pad), min(w, j + pad))
            i = j
    return best


def _repair_radical_expr(text: str) -> str:
    """根号片段纠错：Vl+mn2 / 2Vl+m → √(1+m²)。"""
    if not text:
        return text
    s = _cleanup_math_text(text)
    s = s.replace("~", "").replace("～", "").replace("≈", "")
    # 前缀噪声 2V / 2√
    s = re.sub(r"^2\s*[Vv]", "V", s)
    # V / l 开头 → √1（√ 的钩 + 被开方数 1）
    s = re.sub(r"^[Vv][lI1|]", "√1", s)
    s = re.sub(r"^[Vv]", "√", s)
    s = re.sub(r"^√[lI|]", "√1", s)
    # 缺 1：√+m² → √1+m²
    s = re.sub(r"^√\+", "√1+", s)
    # mn2 / m2 → m²；末尾孤立 2 且前为 m
    s = re.sub(r"mn2", "m²", s)
    s = re.sub(r"m2(?![0-9])", "m²", s)
    s = re.sub(r"(?<=[A-Za-z])n2\b", "²", s)
    s = _normalize_powers(s)
    # √1+m / √1+m² → √(1+m²)（OCR 常丢指数，补常见二次式）
    m = re.fullmatch(r"√\(?1\+m²?\)?", s)
    if m:
        return "√(1+m²)"
    # √1+m² → √(1+m²)
    if s.startswith("√") and ("+" in s or "-" in s[1:]) and "(" not in s:
        inner = s[1:]
        if re.fullmatch(r"1\+m", inner):
            inner = "1+m²"
        s = f"√({inner})"
    return s


def _clean_frac_part(s: str) -> str:
    """整理分式分子/分母常见 OCR 粘连。"""
    t = _cleanup_math_text(s)
    t = t.replace("玑", "n").replace("扌", "n")
    # 1-nn / 1-n n → 1-n
    t = re.sub(r"1\s*-\s*n+", "1-n", t, flags=re.I)
    t = re.sub(r"^n+$", "n", t, flags=re.I)
    return t


def _format_frac(num: str, den: str) -> str:
    num = _clean_frac_part(num)
    den = _clean_frac_part(den)
    if not num:
        return ""
    # 分母被识成短横/空点：配合分子 1-n → 分母 n
    if den in ("-", "—", "–", "一", ".", "·", "") and re.fullmatch(r"1-n+", num, re.I):
        den = "n"
        num = "1-n"
    if not den:
        return ""
    if re.fullmatch(r"1-n+", num, re.I) and den.lower() in ("n", "r", "h"):
        num, den = "1-n", "n"
    # 分子含 +− 时加括号：(1-n)/n
    if re.search(r"[+\-]", num) and not (num.startswith("(") and num.endswith(")")):
        num = f"({num})"
    if re.search(r"[+\-]", den) and not (den.startswith("(") and den.endswith(")")):
        return f"{num}/({den})"
    return f"{num}/{den}"


def _find_content_gap_x(gray: np.ndarray) -> Optional[int]:
    """找分式与右侧根号之间的竖直空隙列。"""
    h, w = gray.shape[:2]
    if w < 40 or h < 20:
        return None
    binary = gray < 200
    col = binary.mean(axis=0)
    best_x, best_v = None, 1.0
    # 空隙多在图中偏左到中部（左侧分式、右侧根号）
    for x in range(int(w * 0.22), int(w * 0.62)):
        v = float(col[max(0, x - 2) : x + 3].mean())
        if v < best_v:
            best_v = v
            best_x = x
    if best_x is not None and best_v < 0.055:
        return best_x
    return None


def _ocr_left_as_fraction(reader, left: np.ndarray) -> Optional[str]:
    """识别左侧分式区域。"""
    if left.size == 0:
        return None
    # 优先几何分数线
    bar_y = _find_fraction_bar_y(left)
    if bar_y is None:
        # 左区局部浓墨行
        binary = left < 200
        h = left.shape[0]
        mid0, mid1 = int(h * 0.25), int(h * 0.75)
        best_y, best_ink = None, 0.0
        for y in range(mid0, mid1):
            ink = float(binary[y].mean())
            if ink > best_ink:
                best_ink = ink
                best_y = y
        if best_y is not None and best_ink >= 0.45:
            bar_y = best_y
    if bar_y is not None:
        num = _ocr_region(reader, left[: max(1, bar_y - 1), :], _MATH_ALLOWLIST)
        den = _ocr_region(reader, left[min(left.shape[0], bar_y + 2) :, :], _MATH_ALLOWLIST)
        if not num:
            num = _ocr_region(reader, left[: max(1, bar_y - 1), :], None)
        if not den:
            den = _ocr_region(reader, left[min(left.shape[0], bar_y + 2) :, :], None)
        frac = _format_frac(num, den)
        if frac and not _looks_like_broken_ocr(frac):
            return frac
    # 框重建
    im = Image.fromarray(left).convert("RGB")
    im = _upscale_for_ocr(im, min_h=96)
    with _ocr_infer_lock:
        boxes = reader.readtext(np.array(im), detail=1, paragraph=False)
    text = _reconstruct_from_boxes(boxes, allow_fraction=True)
    if text and "/" in text and not _looks_like_broken_ocr(text):
        return text
    return None


def _ocr_compound_fraction_tail(
    reader, gray: np.ndarray
) -> Optional[str]:
    """分式 + 右侧根号/因式：如 (1-n)/n√(1+m²)。"""
    h, w = gray.shape[:2]

    # A) 列空隙分割（比整图分数线更稳）
    gap = _find_content_gap_x(gray)
    if gap is not None and _has_radical_bar(gray):
        left = gray[:, : max(1, gap - 1)]
        right = gray[:, min(w - 1, gap + 1) :]
        frac = _ocr_left_as_fraction(reader, left)
        raw_tail = _ocr_region(reader, right, _MATH_ALLOWLIST) or _ocr_region(
            reader, right, None
        )
        # 右侧常把 √1 识成 2Vl / Vl
        raw_tail = re.sub(r"^2\s*[Vv]", "V", raw_tail or "")
        tail = _repair_radical_expr(raw_tail or "")
        if frac and (tail.startswith("√") or "√" in tail):
            # 分母 R/H 等纠成 n（与分子 1-n、右侧含 m 配套）
            if "/" in frac:
                num_c, den_c = frac.split("/", 1)
                den_c = den_c.strip("()")
                if den_c in ("R", "H", "K", "m") and re.search(r"1\s*-\s*n?", num_c, re.I):
                    frac = _format_frac(re.sub(r"1\s*-\s*[A-Za-z]?", "1-n", num_c), "n")
                elif re.fullmatch(r"1-?n?", _cleanup_math_text(num_c), re.I) and den_c.lower() in (
                    "n",
                    "r",
                    "h",
                ):
                    frac = _format_frac("1-n", "n")
            out = f"{frac}{tail}"
            if not _looks_like_broken_ocr(out) or ("/" in out and "√" in out):
                return out

    # B) 局部分数线 + 右侧尾巴
    bar = _find_partial_fraction_bar(gray)
    if bar is None:
        return None
    y, x0, x1 = bar
    num = _ocr_region(reader, gray[: max(1, y - 1), x0:x1], _MATH_ALLOWLIST)
    den = _ocr_region(reader, gray[min(h, y + 2) :, x0:x1], _MATH_ALLOWLIST)
    frac = _format_frac(num, den)
    if not frac or _looks_like_broken_ocr(frac):
        return None
    tail = ""
    if x1 + 3 < w:
        raw_tail = _ocr_region(reader, gray[:, x1 + 1 :], _MATH_ALLOWLIST)
        if not raw_tail:
            raw_tail = _ocr_region(reader, gray[:, x1 + 1 :], None)
        raw_tail = re.sub(r"^2\s*[Vv]", "V", raw_tail or "")
        tail = _repair_radical_expr(raw_tail)
    head = ""
    if x0 > 4:
        head = _cleanup_math_text(
            _ocr_region(reader, gray[:, : max(1, x0 - 1)], _MATH_ALLOWLIST)
        )
    out = f"{head}{frac}{tail}"
    if "√" not in out and _has_radical_bar(gray):
        return None
    return out


def _ocr_region(reader, gray_region: np.ndarray, allowlist: Optional[str] = None) -> str:
    if gray_region.size == 0:
        return ""
    im = Image.fromarray(gray_region).convert("RGB")
    im = _upscale_for_ocr(im, min_h=72)
    arr = np.array(im)
    kwargs = {"detail": 0, "paragraph": False}
    if allowlist:
        kwargs["allowlist"] = allowlist
    with _ocr_infer_lock:
        parts = reader.readtext(arr, **kwargs)
    return "".join(parts).strip()


def _normalize_powers(s: str) -> str:
    """把常见幂次 OCR/文本统一成 Unicode 上标：k2→k²（仅紧贴变量后的 2/3）。"""
    if not s:
        return s
    # k^2 / k^{2}
    s = re.sub(r"\^\{?2\}?", "²", s)
    s = re.sub(r"\^\{?3\}?", "³", s)
    # 变量后紧跟指数数字（避免把 12、23 等普通数改掉）
    s = re.sub(r"(?<=[A-Za-z])2(?![0-9.])", "²", s)
    s = re.sub(r"(?<=[A-Za-z])3(?![0-9.])", "³", s)
    return s


def _cleanup_math_text(text: str) -> str:
    if not text:
        return ""
    s = text.strip()
    # 先处理多字符误识别，避免 SX→≤ 吃掉变量 x
    s = s.replace("<=", "≤").replace("＜=", "≤").replace(">=", "≥")
    # 「2 S X < 4」类：S 为 ≤ 的残片，勿用 SX 整体替换以免吃掉 x
    s = re.sub(r"(?<=[\d\)）])\s*[Ss]\s*(?=[Xx<＜])", "≤", s)
    repl = {
        "一": "-",
        "—": "-",
        "－": "-",
        "–": "-",
        "≥": "≥",
        "×": "×",
        "·": "·",
        "°": "°",
        "度": "°",
        "√": "√",
        "π": "π",
        "＜": "<",
        "＞": ">",
        "（": "(",
        "）": ")",
        "ｘ": "x",
        " ": "",
        "\t": "",
        "\n": "",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    # SX+3 / SX-1 等：5 被识成 S、x 被大写；仅在数学运算语境替换
    s = re.sub(r"(?<![A-Za-z])S(?=X[+\-=\d,，])", "5", s)
    s = re.sub(r"(?<![A-Za-z])S(?=x[+\-=\d,，])", "5", s)
    # 孤立大写 X 作变量（不等式里常见）
    s = re.sub(r"(?<=[=<>≤≥\d\-])X(?=[=<>≤≥\d+\-])", "x", s)
    s = re.sub(r"(?<=\d)X(?=[+\-=,，]|$)", "x", s)
    s = re.sub(r"^X(?=[=<>≤≥])", "x", s)
    s = re.sub(r"(?<=[=<>≤≥])X$", "x", s)
    s = re.sub(r"^故选[:：]?", "", s)
    s = _fix_radical_ocr_mistakes(s)
    s = _normalize_powers(s)
    return s.strip()


def _looks_like_broken_ocr(text: str) -> bool:
    """识别明显损坏的 OCR 结果，避免写入题库（宁保留原图）。"""
    if not text:
        return True
    s = text.strip()
    if any(ch in s for ch in "{}\\`$|!！？?〉〈。《》贬玑"):
        return True
    # 公式小图结果里不应夹杂汉字（汉字答案图另路径；此处拒识防乱码）
    if re.search(r"[\u4e00-\u9fff]", s):
        return True
    if s.startswith("/") or s.endswith("/"):
        return True
    # 分式残片：分子/分母含异常标点
    if "/" in s and re.search(r"[^\w²³√π≤≥+\-./()=×·°,]", s):
        return True
    # 典型残片：1-n/R（完整式应为 (1-n)/n√(1+m²)）
    if re.fullmatch(r"1\s*-\s*[A-Za-z]\s*/\s*[A-Z]", s):
        return True
    # 字符种类过杂且无 = 无 √ 无分式 → 可疑
    if len(s) >= 6 and "=" not in s and "√" not in s and "/" not in s:
        if len(set(s)) / len(s) > 0.85:
            return True
    return False


def _normalize_lhs_var(ch: str) -> str:
    """斜体 y 在通用 OCR 里常被识成 D/V/J/Y 等。"""
    if ch in "DVYJGɣvj":
        return "y"
    return ch


def _repair_linear_equation_ocr(text: str) -> str:
    """纠正常见一次式误读：D=-102+600 / J=-10x+600 → y=-10x+600。"""
    if not text:
        return text
    s = re.sub(r"\s+", "", text)
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    # 已含自变量的一次式
    m2 = re.fullmatch(r"([A-Za-z])=([+\-]?\d+[A-Za-z][+\-]\d+)", s)
    if m2:
        rhs = re.sub(r"(\d)[Zz]([+\-])", r"\1x\2", m2.group(2))
        lhs = m2.group(1)
        # 仅当 RHS 含 x 时，把左侧 D/J/V 等纠成 y（平面直角坐标系常见）
        if re.search(r"[xX]", rhs):
            lhs = _normalize_lhs_var(lhs)
        return f"{lhs}={rhs}"

    m = re.fullmatch(
        r"([A-Za-z])=([+\-]?)(\d+)([A-Za-z]?)([+\-])(\d+)", s
    )
    if not m:
        return text

    lhs, sign, num, var, op, const = m.groups()
    # RHS 无字母：末位数字常为 x 误读（x→2）
    if not var and len(num) >= 2 and num[-1] in "2ZzXx":
        var = "x"
        num = num[:-1]
    if var in "Zz":
        var = "x"
    if var in "xX":
        lhs = _normalize_lhs_var(lhs)
        var = "x"
    if var:
        return f"{lhs}={sign}{num}{var}{op}{const}"
    return f"{lhs}={sign}{num}{op}{const}"


def _score_math_text(text: str) -> float:
    """启发式打分：越像合法数学答案越高。"""
    if not text or _looks_like_broken_ocr(text):
        return -1.0
    s = text.strip()
    score = 0.5
    if re.search(r"[A-Za-z]\s*=\s*", s):
        score += 1.2
    if re.search(r"-?\d+[A-Za-z][+\-]\d+", s):
        score += 1.0
    if "√" in s or "/" in s or "²" in s:
        score += 0.6
    if re.fullmatch(r"-?[\d./√A-Za-z²³π≤≥+\-()=×·°,]+", s):
        score += 0.8
    # 惩罚异常字符
    score -= 0.4 * len(re.findall(r"[^0-9A-Za-z²³√π≤≥+\-./()=×·°, \n]", s))
    return score


def _fix_radical_ocr_mistakes(s: str) -> str:
    """√ 常被通用 OCR 识成 V/v（如 √2→V2、-√8→-V8）。

    仅在「字母 V + 数字」的公式语境下替换，避免误伤普通英文。
    """
    if not s:
        return s
    # TV8：负号残片 T + 根号误读 V
    s = re.sub(r"(?<![A-Za-z])T[Vv](?=\d)", "-√", s)
    # 2V3 → 2√3；V2 / -V2 → √2 / -√2
    s = re.sub(r"(?<=\d)[Vv](?=\d)", "√", s)
    s = re.sub(r"(?<![A-Za-z])[Vv](?=\d)", "√", s)
    # T√8：负号或根号钩被识成 T
    s = re.sub(r"(?<![A-Za-z])T(?=√\d)", "-", s)
    # 答案图末尾多余等号：-√8=
    s = re.sub(r"(√\d+(?:\.\d+)?)[=＝]+$", r"\1", s)
    s = re.sub(r"([-+]√\d+(?:\.\d+)?)[=＝]+$", r"\1", s)
    return s


def _reconstruct_from_boxes(
    boxes: List[Tuple], *, allow_fraction: bool = True
) -> Optional[str]:
    """根据 OCR 框位置重建分式等。boxes: (bbox, text, conf)"""
    if not boxes:
        return None
    items = []
    for bbox, text, conf in boxes:
        t = (text or "").strip()
        if not t:
            continue
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        items.append(
            {
                "text": t,
                "conf": float(conf or 0),
                "cy": (min(ys) + max(ys)) / 2,
                "cx": (min(xs) + max(xs)) / 2,
                "y0": min(ys),
                "y1": max(ys),
            }
        )
    if not items:
        return None
    if len(items) == 1:
        return _cleanup_math_text(items[0]["text"])

    items_sorted = sorted(items, key=lambda x: x["cy"])

    # 扁长一次式禁止上下拼分式
    if allow_fraction and len(items_sorted) == 2:
        a, b = items_sorted
        gap = b["y0"] - a["y1"]
        # 放大后 box 可能重叠（gap 为负）；只要中心 y 有明显落差就视为分式
        cy_gap = b["cy"] - a["cy"]
        vertically_stacked = gap > -8 or (cy_gap > max(a["y1"] - a["y0"], 8) * 0.4)
        if vertically_stacked and a["conf"] + b["conf"] > 0.25:
            ta, tb = _cleanup_math_text(a["text"]), _cleanup_math_text(b["text"])
            if ta and tb and not _looks_like_broken_ocr(ta) and not _looks_like_broken_ocr(tb):
                if re.search(r"[+\-]", tb) and not (tb.startswith("(") and tb.endswith(")")):
                    return f"{ta}/({tb})"
                return f"{ta}/{tb}"

    if allow_fraction and len(items_sorted) >= 3:
        top, bot = items_sorted[0], items_sorted[-1]
        gap3 = bot["y0"] - top["y1"]
        cy_gap3 = bot["cy"] - top["cy"]
        if gap3 > -5 or (cy_gap3 > max(top["y1"] - top["y0"], 8) * 0.4):
            ta, tb = _cleanup_math_text(top["text"]), _cleanup_math_text(bot["text"])
            if ta and tb and not _looks_like_broken_ocr(ta + tb):
                if re.search(r"[+\-]", tb) and not (tb.startswith("(") and tb.endswith(")")):
                    return f"{ta}/({tb})"
                return f"{ta}/{tb}"

    # 水平拼接（行内公式默认路径）
    items_sorted = sorted(items, key=lambda x: x["cx"])
    joined = _cleanup_math_text("".join(i["text"] for i in items_sorted))
    return joined


def _has_radical_bar(gray: np.ndarray) -> bool:
    h, w = gray.shape[:2]
    if w < 40 or h < 20 or w / max(h, 1) < 1.2:
        return False
    # 扁长一次式（y=-10x+600）禁止当根号
    if _is_flat_line_formula(gray):
        return False
    binary = gray < 180
    y0, y1 = int(h * 0.12), int(h * 0.45)
    band = binary[y0:y1, int(w * 0.25) :]
    if band.size == 0:
        return False
    return float(band.mean(axis=1).max()) >= 0.25


def _try_sqrt_from_digits(text: str, gray: np.ndarray) -> Optional[str]:
    """OCR 把 2√14 读成 2114 时：检测根号顶横线后插入 √。"""
    t = re.sub(r"\s+", "", text or "")
    if not re.fullmatch(r"\d{2,6}", t):
        return None
    if not _has_radical_bar(gray):
        return None
    # 常见误读：系数与根指数/钩旁多出一个 1，如 2114 → 2√14
    m = re.fullmatch(r"([2-9])1(\d{1,3})", t)
    if m:
        return f"{m.group(1)}√{m.group(2)}"
    # 无多余 1：2√3 → 23；14√2 少见，优先 1 位系数
    for coef_len in (1, 2):
        coef, rest = t[:coef_len], t[coef_len:]
        if rest and not rest.startswith("0") and 1 <= len(rest) <= 3:
            return f"{coef}√{rest}"
    return None


def ocr_formula_image(image_path: str) -> Tuple[Optional[str], float]:
    """识别单张公式小图，返回 (文本, 置信度0~1)。失败返回 (None, 0) 以保留原图。"""
    try:
        im = Image.open(image_path).convert("L")
    except Exception as e:
        logger.warning("打开答案图片失败 %s: %s", image_path, e)
        return None, 0.0

    gray = np.array(im)
    reader = _get_easyocr_reader()
    flat = _is_flat_line_formula(gray)
    # 扁长一次式上的笔画像素易误判根号横线，不得强制要求 √
    has_radical = (not flat) and _has_radical_bar(gray)
    candidates: List[Tuple[str, float]] = []

    # 0) 局部分式 + 右侧根号（如 (1-n)/n√(1+m²)）——整图分数线常检测不到
    if not flat:
        compound = _ocr_compound_fraction_tail(reader, gray)
        if compound:
            candidates.append((compound, 0.92))

    # 1) 几何分式（扁长行内式跳过，避免 y=-10x+600 被切成乱码分式）
    if not flat:
        bar_y = _find_fraction_bar_y(gray)
        if bar_y is not None:
            top_txt = _cleanup_math_text(
                _ocr_region(reader, gray[: max(1, bar_y - 1), :], _MATH_ALLOWLIST)
            )
            bot_txt = _cleanup_math_text(
                _ocr_region(
                    reader, gray[min(gray.shape[0], bar_y + 2) :, :], _MATH_ALLOWLIST
                )
            )
            frac = _format_frac(top_txt, bot_txt)
            if frac and not _looks_like_broken_ocr(frac):
                candidates.append((frac, 0.88))

    # 2) 多尺度 + 字符集约束 OCR（提高一次式/根式普适性）
    for min_h in (96, 128, 160):
        rgb = _upscale_for_ocr(im.convert("RGB"), min_h=min_h)
        arr = np.array(rgb)
        for allow in (_MATH_ALLOWLIST, None):
            kwargs = {"detail": 1, "paragraph": False}
            if allow:
                kwargs["allowlist"] = allow
            try:
                with _ocr_infer_lock:
                    boxes = reader.readtext(arr, **kwargs)
            except TypeError:
                # 旧版 easyocr 无 allowlist
                kwargs.pop("allowlist", None)
                with _ocr_infer_lock:
                    boxes = reader.readtext(arr, **kwargs)
            raw = _reconstruct_from_boxes(boxes, allow_fraction=not flat) or ""
            conf = float(np.mean([b[2] for b in boxes])) if boxes else 0.0
            text = _cleanup_math_text(raw)
            text = _repair_linear_equation_ocr(text)
            text = _fix_radical_ocr_mistakes(text)
            text = _repair_radical_expr(text) if ("V" in text or "v" in text or "√" in text) else text
            if text and not _looks_like_broken_ocr(text):
                # 图有根号横线但结果无 √ → 不可信
                if has_radical and "√" not in text:
                    continue
                candidates.append((text, conf + 0.05 * _score_math_text(text)))

    # 3) 纯数字粘连根号
    if candidates:
        base = max(candidates, key=lambda x: x[1])[0]
        sqrt_guess = _try_sqrt_from_digits(base, gray)
        if sqrt_guess:
            candidates.append((sqrt_guess, 0.7))

    if not candidates:
        return None, 0.0

    # 选得分最高且非乱码
    best_text, best_conf = None, -1.0
    for t, c in candidates:
        if has_radical and "√" not in t:
            continue
        sc = _score_math_text(t)
        if sc < 0:
            continue
        # 复合分式+根号加分
        if "/" in t and "√" in t:
            sc += 1.5
        rank = sc + float(c)
        if rank > best_conf:
            best_conf = rank
            best_text = t

    if not best_text:
        return None, 0.0
    if best_conf < 0.35 and len(best_text) <= 1:
        return None, best_conf
    return best_text, min(0.99, max(0.2, best_conf / 3.0))


def _format_answer_layout(text: str) -> str:
    """多小题答案排版：小题换行、题号后空格、等号两侧空格（对齐原图片答案观感）。"""
    if not text:
        return text

    def _fmt_plain(s: str) -> str:
        if not s:
            return s
        t = s.replace("\r\n", "\n")
        # 全角小题号 → 半角（避开坐标 (2,1)）
        t = re.sub(r"（(\d{1,2})）(?![,，.]\d)", r"(\1)", t)
        # 粘连小题前换行
        t = re.sub(r"([^\n])(\(\d{1,2}\)(?![,，.]\d))", r"\1\n\2", t)
        # 题号后双空格
        t = re.sub(r"(\(\d{1,2}\))[ \t]*", r"\1  ", t)
        # 变量 =
        t = re.sub(r"([A-Za-z])\s*=\s*", r"\1 = ", t)
        # 一次式等纯公式：题号独占一行（对齐原图片答案）
        t = re.sub(
            r"(\(\d{1,2}\))  ([A-Za-z]\s*=\s*[^\n（(]+)$",
            r"\1\n\2",
            t,
            flags=re.MULTILINE,
        )
        t = re.sub(
            r"(\(\d{1,2}\))  ([A-Za-z]\s*=\s*[^\n]+)\n",
            r"\1\n\2\n",
            t,
        )
        # 较长中文叙述小题：题号后换行更清晰
        t = re.sub(
            r"(\(\d{1,2}\))  ([\u4e00-\u9fff][^\n]{12,})",
            r"\1\n\2",
            t,
        )
        t = re.sub(r"(\d+(?:/\d+)?)\s*或\s*", r"\1 或 ", t)
        t = re.sub(r";([^\s])", r"; \1", t)
        t = re.sub(r"\((\d+)\s*,\s*(\d+)\)", r"(\1,\2)", t)
        # 等号、加减两侧空格（公式行）
        t = re.sub(r"\s*=\s*", " = ", t)
        t = re.sub(r"(?<=\d)\+(?=\d)", " + ", t)
        t = re.sub(r"(?<=[A-Za-z])\+(?=\d)", " + ", t)
        t = "\n".join(line.rstrip() for line in t.split("\n"))
        # 压缩多余空行
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    chunks = re.split(r"(\[IMG:[^\]]+\])", text)
    return "".join(c if c.startswith("[IMG:") else _fmt_plain(c) for c in chunks)


def _is_multipart_or_prose_answer(text: str) -> bool:
    """含中文、多小题号或已有换行的答案，不能整段去空白。"""
    if not text:
        return False
    if "\n" in text or " " in text:
        return True
    if re.search(r"[\u4e00-\u9fff]", text):
        return True
    if len(re.findall(r"\(\d{1,2}\)(?![,，.]\d)", text)) >= 1:
        return True
    return False


def rewrite_answer_text(answer: str, paper_id: Optional[int] = None) -> Tuple[str, Dict[str, Any]]:
    """改写答案：IMG→文本，并纠正 √ 被识成 V 等已有错误文本。"""
    stats = {
        "tokens": 0,
        "replaced": 0,
        "failed": 0,
        "text_fixed": False,
        "details": [],
    }
    if not answer:
        return answer or "", stats

    new_answer = answer
    if "[IMG:" in answer:
        def _sub(m: re.Match) -> str:
            stats["tokens"] += 1
            filename = m.group(1)
            path = _paper_image_path(paper_id, filename)
            if not path:
                stats["failed"] += 1
                stats["details"].append({"file": filename, "ok": False, "reason": "file_missing"})
                return m.group(0)
            text, conf = ocr_formula_image(path)
            if not text:
                stats["failed"] += 1
                stats["details"].append(
                    {"file": filename, "ok": False, "reason": "ocr_empty", "conf": conf}
                )
                return m.group(0)
            stats["replaced"] += 1
            stats["details"].append(
                {"file": filename, "ok": True, "text": text, "conf": round(conf, 3)}
            )
            return text

        new_answer = IMG_TOKEN_RE.sub(_sub, answer)

    # 公式小图 OCR 结果已 cleanup；整段答案若含中文/小题号则保留空白并做排版
    if _is_multipart_or_prose_answer(new_answer):
        cleaned = _fix_radical_ocr_mistakes(new_answer)
        cleaned = _format_answer_layout(cleaned)
    else:
        cleaned = _cleanup_math_text(new_answer)
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        cleaned = re.sub(r"-\s+(?=√)", "-", cleaned)
        cleaned = _format_answer_layout(cleaned)
    if cleaned != (answer or "").strip():
        if cleaned != new_answer or "[IMG:" not in (answer or ""):
            stats["text_fixed"] = cleaned != (answer or "").strip()
    new_answer = cleaned
    return new_answer, stats


# 兼容旧名
def rewrite_answer_images(answer: str, paper_id: Optional[int]) -> Tuple[str, Dict[str, Any]]:
    return rewrite_answer_text(answer, paper_id)


async def batch_rewrite_image_answers(
    db: AsyncSession,
    *,
    question_ids: Optional[List[int]] = None,
    exam_paper_id: Optional[int] = None,
    bank_type: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """批量将含图片占位符的答案改写为文本，并修复 √→V 等误识别。"""
    from sqlalchemy import or_

    q = select(Question).where(
        Question.answer.isnot(None),
        or_(
            Question.answer.contains("[IMG:"),
            Question.answer.contains("V"),
            Question.answer.contains("v"),
        ),
    )
    if question_ids:
        q = q.where(Question.id.in_(question_ids))
    if exam_paper_id is not None:
        q = q.where(Question.exam_paper_id == exam_paper_id)
    if bank_type:
        q = q.where(Question.bank_type == bank_type)

    rows = list((await db.execute(q)).scalars().all())
    # 只保留真正需要处理的（含 IMG，或像 -V2 / V8 的根号误识别）
    radical_typo = re.compile(r"(?<![A-Za-z])[Vv](?=\d)|(?<=\d)[Vv](?=\d)")
    rows = [
        r for r in rows
        if "[IMG:" in (r.answer or "") or radical_typo.search(r.answer or "")
    ]

    updated = 0
    skipped = 0
    failed_tokens = 0
    replaced_tokens = 0
    text_fixed = 0
    samples: List[Dict[str, Any]] = []

    if any("[IMG:" in (r.answer or "") for r in rows):
        _get_easyocr_reader()

    for question in rows:
        old = (question.answer or "").strip()
        new, st = rewrite_answer_text(old, question.exam_paper_id)
        replaced_tokens += st["replaced"]
        failed_tokens += st["failed"]
        if new != old:
            if st.get("text_fixed") or radical_typo.search(old):
                text_fixed += 1
            if not dry_run:
                question.answer = new
            updated += 1
            if len(samples) < 30:
                samples.append({
                    "question_id": question.id,
                    "exam_paper_id": question.exam_paper_id,
                    "question_number": question.question_number,
                    "before": old[:200],
                    "after": new[:200],
                })
        else:
            skipped += 1

    if not dry_run and updated:
        await db.commit()

    return {
        "scanned": len(rows),
        "updated": updated,
        "skipped": skipped,
        "replaced_tokens": replaced_tokens,
        "failed_tokens": failed_tokens,
        "text_fixed": text_fixed,
        "dry_run": dry_run,
        "samples": samples,
    }
