"""Test option regex on Q8 option line"""
import re

OPTION_LINE_RE = re.compile(
    r'([A-D])(?:\s*[．.、)）]\s*|(?=\s*\[IMG\:])|\s+(?=[^\s]))'
)

lines = [
    'C 文艺类图书销售占比[IMG:img_121.png] D. 其他类图书销售占比[IMG:img_122.png]',
    'A. 科技类图书销售了60册    B. 文艺类图书销售了120册',
    'A.         B.      C.      D.',
    'C.         D.',
    'C[IMG:img_121.png] 文艺类图书销售占比[IMG:img_122.png]',
]

for line in lines:
    print(f"\nLine: {line}")
    matches = list(OPTION_LINE_RE.finditer(line))
    print(f"Matches: {[(m.group(1), m.start(), m.end()) for m in matches]}")
