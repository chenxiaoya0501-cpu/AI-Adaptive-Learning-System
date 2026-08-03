# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")
from app.services.word_parser import _split_answer_analysis, _extract_short_answer

cases = [
    (
        "2025 【答案】",
        "题干...\n【答案】2√14\n【解析】解：...",
    ),
    (
        "2024 故答案为 纯文本",
        "题干...\n【解答】解：...\n故答案为：3．\n【点评】...",
    ),
    (
        "2024 故答案为 分数文本",
        "题干...\n【解答】解：...\n故答案为：1/4．\n【点评】...",
    ),
    (
        "2024 故答案为 公式图片",
        "题干...\n【解答】解：...\n故答案为：[IMG:img_035.png,9.8,26.2]．\n【点评】...",
    ),
]

for name, content in cases:
    pure, answer, analysis = _split_answer_analysis(content)
    print(f"[{name}]")
    print(f"  answer = {answer!r}")
    if analysis:
        print(f"  from analysis short = {_extract_short_answer(analysis)!r}")
    print()
