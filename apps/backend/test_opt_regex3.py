"""Test new option regex"""
import re

patterns = [
    r'([A-D])(?:\s*[．.、)）]\s*|[ \t]+(?=\S)|(?=\[))',
    r'([A-D])(?:\s*[．.、)）]\s*|[ \t]+(?=\S)|(?=[A-D]*\[))',
    r'([A-D])(?=\s|\[|$)',
    r'([A-D])(?:\s*[．.、)）]\s*|[ \t]+|(?=\[))(?=\S|$)',
]

lines = [
    'C[IMG:img_121.png] 文艺类图书销售占比[IMG:img_122.png]    D. 其他类图书销售占比[IMG:img_123.png]',
    'A. 科技类图书销售了60册    B. 文艺类图书销售了120册',
    'A.         B.      C.      D.',
    'C 文艺 D. 其他',
]

for pat in patterns:
    print(f"\nPattern: {pat}")
    regex = re.compile(pat)
    for line in lines:
        matches = list(regex.finditer(line))
        print(f"  {line[:50]}...: {[(m.group(1), m.start(), m.end()) for m in matches]}")
