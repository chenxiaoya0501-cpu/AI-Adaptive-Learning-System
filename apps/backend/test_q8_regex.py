"""Test the current OPTION_LINE_RE on Q8 line"""
from app.services.word_parser import OPTION_LINE_RE

line = '    C[IMG:img_121.png] 文艺类图书销售占比[IMG:img_122.png]    D. 其他类图书销售占比[IMG:img_123.png]'
print(f"Line: {line!r}")
print(f"Regex pattern: {OPTION_LINE_RE.pattern!r}")
matches = list(OPTION_LINE_RE.finditer(line))
print(f"Matches: {[(m.group(1), m.start(), m.end()) for m in matches]}")

# Also test stripped
s = line.strip()
print(f"\nStripped: {s!r}")
matches = list(OPTION_LINE_RE.finditer(s))
print(f"Matches: {[(m.group(1), m.start(), m.end()) for m in matches]}")
