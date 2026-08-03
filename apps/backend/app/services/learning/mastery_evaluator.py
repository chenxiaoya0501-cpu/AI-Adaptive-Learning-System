"""课程练习掌握度评估规则。

规则目标：分数可解释、少量题不误判达标，并允许多轮练习逐步更新认知状态。
"""
import math
from typing import Any, Dict, List, Optional


DIFFICULTY_WEIGHTS = {1: 0.70, 2: 0.85, 3: 1.00, 4: 1.20, 5: 1.40}
MIN_PASS_QUESTIONS = 4
RECOMMENDED_QUESTIONS = 8


def evaluate_mastery(
    results: List[Dict[str, Any]],
    target_mastery: float,
    prior_mastery: Optional[float],
) -> Dict[str, Any]:
    answered_count = len(results)
    correct_count = sum(1 for item in results if item.get("is_correct"))
    total_weight = 0.0
    correct_weight = 0.0
    difficulty_breakdown: Dict[str, Dict[str, int]] = {}

    for item in results:
        difficulty = max(1, min(5, int(item.get("difficulty") or 3)))
        weight = DIFFICULTY_WEIGHTS[difficulty]
        total_weight += weight
        if item.get("is_correct"):
            correct_weight += weight
        bucket = difficulty_breakdown.setdefault(
            str(difficulty), {"answered": 0, "correct": 0}
        )
        bucket["answered"] += 1
        bucket["correct"] += int(bool(item.get("is_correct")))

    weighted_accuracy = correct_weight / total_weight if total_weight else 0.0
    raw_performance = weighted_accuracy * 100
    evidence_strength = 1 - math.exp(-answered_count / 5.0) if answered_count else 0.0
    baseline = 50.0 if prior_mastery is None else max(0.0, min(100.0, prior_mastery))
    mastery = baseline * (1 - evidence_strength) + raw_performance * evidence_strength

    # 少量题只能形成阶段判断，不能给出过高分数。
    if answered_count < MIN_PASS_QUESTIONS:
        mastery = min(mastery, 74.0)
    elif answered_count < 6:
        mastery = min(mastery, 85.0)
    elif answered_count < RECOMMENDED_QUESTIONS:
        mastery = min(mastery, 92.0)

    mastery = round(max(0.0, min(100.0, mastery)), 1)
    accuracy = round(correct_count / answered_count, 4) if answered_count else None
    confidence = round(evidence_strength, 4)
    confidence_level = "high" if confidence >= 0.80 else "medium" if confidence >= 0.55 else "low"
    evidence_sufficient = answered_count >= MIN_PASS_QUESTIONS
    achieved = bool(
        evidence_sufficient
        and mastery >= target_mastery
        and weighted_accuracy >= 0.60
    )

    if not evidence_sufficient:
        recommendation = f"至少完成 {MIN_PASS_QUESTIONS} 道有效题目后才能判断达标"
    elif achieved:
        recommendation = "已达到本知识点目标，可进入后续课程或继续挑战高难度题"
    elif weighted_accuracy < 0.60:
        recommendation = "正确率偏低，建议回看知识讲解和错题解析后再次练习"
    else:
        recommendation = f"距离目标还差 {max(0.0, target_mastery - mastery):.1f} 分，建议继续完成针对性练习"

    return {
        "mastery_score": mastery,
        "target_mastery": round(float(target_mastery), 1),
        "achieved": achieved,
        "evidence_sufficient": evidence_sufficient,
        "answered_count": answered_count,
        "correct_count": correct_count,
        "accuracy": accuracy,
        "weighted_accuracy": round(weighted_accuracy, 4),
        "confidence": confidence,
        "confidence_level": confidence_level,
        "prior_mastery": prior_mastery,
        "difficulty_breakdown": difficulty_breakdown,
        "minimum_pass_questions": MIN_PASS_QUESTIONS,
        "recommended_questions": RECOMMENDED_QUESTIONS,
        "recommendation": recommendation,
        "rule_version": "course-mastery-v1",
    }
