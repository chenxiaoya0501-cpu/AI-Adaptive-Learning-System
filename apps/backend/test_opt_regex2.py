"""Test simpler option regex"""
import re

patterns = [
    r'([A-D])(?:\s*[．.、)）]\s*|(?=\s*\[IMG\:])|\s+)',
    r'([A-D])(?:\s*[．.、)）]?\s*)',
    r'([A-D])(?=\s|$|\[)',
]

lines = [
    'C[IMG:img_121.png] 文艺类图书销售占比[IMG:img_122.png]',
    'A. xxx B. xxx',
    'C 文艺 D. 其他',
    'A[IMG] B[IMG]',
]

for pat in patterns:
    print(f"\nPattern: {pat}")
    regex = re.compile(pat)
    for line in lines:
        matches = list(regex.finditer(line))
        print(f"  {line}: {[(m.group(1), m.start(), m.end()) for m in matches]}")
