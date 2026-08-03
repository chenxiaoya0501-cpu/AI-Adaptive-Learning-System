"""自动批改：选择题 / 填空规则判分；解答题仅在可文本比对时判分。"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional, Tuple

from app.models.student.test_paper import TestAnswer, TestQuestion

_IMG_RE = re.compile(r"\[IMG:[^\]]+\]")


def normalize_choice(val: Optional[str]) -> str:
    if not val:
        return ""
    s = str(val).strip().upper()
    m = re.search(r"[A-D]", s)
    return m.group(0) if m else s[:1]


def strip_img_placeholders(val: Optional[str]) -> str:
    if not val:
        return ""
    return _IMG_RE.sub(" ", str(val))


def normalize_text_answer(val: Optional[str]) -> str:
    """去掉图片占位符后再规范化，避免尺寸数字误匹配。"""
    if not val:
        return ""
    s = strip_img_placeholders(val)
    s = unicodedata.normalize("NFKC", s).strip().lower()
    s = s.replace("\u3000", " ")
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("，", ",").replace("。", ".")
    s = re.sub(r"\s+", "", s)
    return s


def _text_comparable(key: str) -> bool:
    """标准答案去掉图片后，是否还有足够文本可供自动比对。"""
    if not key:
        return False
    # 至少含一个字母/数字/常见数学符号，避免只剩标点
    return bool(re.search(r"[\w\u4e00-\u9fff√π∞≤≥≠±°]+", key, flags=re.UNICODE))


def grade_one(
    question: TestQuestion, answer: Optional[TestAnswer]
) -> Tuple[Optional[bool], float, str]:
    """返回 (is_correct, score_got, method)。

    is_correct 为 None 表示当前无法自动判分（无文本答案 / 答案多为图片）。
    """
    qtype = question.question_type or ""
    full = float(question.score or 0)

    if answer is None or (
        not (answer.selected_option and str(answer.selected_option).strip())
        and not (answer.answer_text and str(answer.answer_text).strip())
    ):
        return False, 0.0, "empty"

    if qtype == "choice":
        key = normalize_choice(answer.selected_option)
        correct = normalize_choice(question.answer)
        if not correct:
            return None, 0.0, "no_key"
        ok = bool(key and key == correct)
        return ok, (full if ok else 0.0), "choice_rule"

    student = normalize_text_answer(answer.answer_text)
    correct_raw = question.answer or ""
    correct = normalize_text_answer(correct_raw)

    if not _text_comparable(correct):
        # 参考答案缺失，或几乎全是公式图片 → 不做文本自动判对
        return None, 0.0, "needs_review"

    if not student:
        return False, 0.0, "empty"

    if student == correct:
        return True, full, "text_exact"

    if qtype == "fill":
        alts = re.split(r"[;；|/｜]", correct_raw)
        for alt in alts:
            alt_n = normalize_text_answer(alt)
            if alt_n and student == alt_n:
                return True, full, "fill_alt"
        return False, 0.0, "fill_rule"

    # 解答 / 证明：仅允许「标准答案文本被完整包含在学生作答中」
    # 禁止 student in correct（会把 "33" 误匹配到图片尺寸 33.8）
    if len(correct) >= 2 and correct in student:
        return True, full, "text_contain_key"
    return False, 0.0, "text_rule"


def grade_paper(
    questions: List[TestQuestion],
    answers_map: Dict[int, TestAnswer],
) -> Dict[str, float]:
    """原地写入 answers 的判分字段，返回汇总。"""
    earned = 0.0
    correct_count = 0
    graded = 0
    pending = 0
    for q in questions:
        ans = answers_map.get(q.id)
        ok, got, method = grade_one(q, ans)
        if ans is not None:
            ans.is_correct = ok
            ans.score_got = got
        earned += got
        if ok is None:
            pending += 1
        else:
            graded += 1
            if ok:
                correct_count += 1
    return {
        "earned_score": round(earned, 2),
        "correct_count": correct_count,
        "graded_count": graded,
        "pending_count": pending,
        "total_count": len(questions),
    }
