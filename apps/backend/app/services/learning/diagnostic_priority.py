"""诊断任务优先级计算。

诊断任务用于减少掌握状态的不确定性，不承诺直接提分，也不参与学习任务
边际价值计算。这里统一把诊断收益与测评成本换算成可解释的排期指标。
"""
from __future__ import annotations

import math
from typing import Any, Dict


TARGET_CONFIDENCE = 0.70
EVIDENCE_SCALE = 3.0
MINUTES_PER_QUESTION = 3
MAX_DIAGNOSTIC_QUESTIONS = 5


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def effective_evidence_from_confidence(confidence: float) -> float:
    """把可信度反解为规划器实际使用的加权有效证据量。"""
    current = _clamp(confidence, high=0.999999)
    return -EVIDENCE_SCALE * math.log(1 - current)


def recommended_question_count(
    confidence: float,
    target_confidence: float = TARGET_CONFIDENCE,
) -> int:
    """估算把证据可信度提升到目标水平所需的有效题数。

    可信度沿用系统现有 ``1 - exp(-有效证据量 / 3)`` 模型，反解当前有效
    证据量后计算缺口。达到目标可信度时不再安排诊断题。
    """
    current = _clamp(confidence, high=0.999999)
    target = _clamp(target_confidence, low=0.01, high=0.99)
    if current >= target:
        return 0
    current_evidence = effective_evidence_from_confidence(current)
    target_evidence = effective_evidence_from_confidence(target)
    return max(
        1,
        min(
            MAX_DIAGNOSTIC_QUESTIONS,
            math.ceil(target_evidence - current_evidence),
        ),
    )


def calculate_diagnostic_priority(
    *,
    total_score: float,
    exam_weight: float,
    confidence: float,
) -> Dict[str, Any]:
    """返回诊断候选的可解释指标。

    诊断信息价值不是考试提分，而是当前不确定状态涉及的考试分值规模：
    ``考试分值影响范围 × (1 - 可信度)``。再除以预计测评时间，得到单位
    时间能够消除的不确定价值，用于决定先测哪个知识点。
    """
    safe_confidence = _clamp(confidence)
    safe_weight = max(0.0, float(exam_weight))
    safe_total_score = max(0.0, float(total_score))
    effective_evidence = effective_evidence_from_confidence(safe_confidence)
    target_evidence = effective_evidence_from_confidence(TARGET_CONFIDENCE)
    score_exposure = safe_total_score * safe_weight
    uncertainty = 1 - safe_confidence
    questions = recommended_question_count(safe_confidence)
    estimated_minutes = questions * MINUTES_PER_QUESTION
    information_value = score_exposure * uncertainty
    priority = (
        information_value / estimated_minutes if estimated_minutes > 0 else 0.0
    )
    return {
        "total_score": safe_total_score,
        "confidence": safe_confidence,
        "target_confidence": TARGET_CONFIDENCE,
        "effective_evidence": effective_evidence,
        "target_evidence": target_evidence,
        "exam_weight": safe_weight,
        "minutes_per_question": MINUTES_PER_QUESTION,
        "uncertainty": uncertainty,
        "score_exposure": score_exposure,
        "recommended_question_count": questions,
        "diagnostic_estimated_minutes": estimated_minutes,
        "diagnostic_information_value": information_value,
        "diagnostic_priority": priority,
    }
