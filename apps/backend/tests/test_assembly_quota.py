"""组卷配额：Largest Remainder + 已学占比重归一（不依赖 DB）"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.learning.assembly import allocate_quotas, largest_remainder


def test_largest_remainder_sums_to_n():
    m = largest_remainder({"a": 0.5, "b": 0.3, "c": 0.2}, 10)
    assert sum(m.values()) == 10
    assert m["a"] >= m["b"] >= m["c"]


def test_allocate_keeps_type_count_and_renorms_learned():
    type_structure = [
        {"question_type": "choice", "count": 10, "subtotal": 30.0, "score_each": 3.0},
    ]
    # 模板含未学 KP_x；已学仅 k1/k2，占比 0.2/0.1 → 重归一后 2:1
    pi_kt = {
        "choice": {
            "k1": 0.2,
            "k2": 0.1,
            "k_unlearned": 0.7,
        }
    }
    learned = {"k1", "k2"}
    quotas, warnings, _ = allocate_quotas(type_structure, pi_kt, learned, lambda_value=0.0)
    assert "k_unlearned" not in quotas["choice"]
    assert sum(quotas["choice"].values()) == 10
    # λ=0 时大致按 2:1
    assert quotas["choice"]["k1"] > quotas["choice"]["k2"]
