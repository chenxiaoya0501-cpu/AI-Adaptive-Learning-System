from app.services.learning.diagnostic_priority import (
    calculate_diagnostic_priority,
    effective_evidence_from_confidence,
    recommended_question_count,
)


def test_recommended_questions_decrease_as_confidence_increases():
    assert recommended_question_count(0.0) == 4
    assert recommended_question_count(0.4) == 3
    assert recommended_question_count(0.65) == 1
    assert recommended_question_count(0.70) == 0


def test_confidence_can_be_explained_as_effective_evidence():
    evidence = effective_evidence_from_confidence(0.40)

    assert round(evidence, 4) == 1.5325


def test_diagnostic_priority_is_information_value_per_minute():
    result = calculate_diagnostic_priority(
        total_score=100,
        exam_weight=0.10,
        confidence=0.40,
    )

    assert result["total_score"] == 100
    assert result["score_exposure"] == 10
    assert round(result["effective_evidence"], 4) == 1.5325
    assert round(result["target_evidence"], 4) == 3.6119
    assert result["minutes_per_question"] == 3
    assert result["uncertainty"] == 0.6
    assert result["diagnostic_information_value"] == 6
    assert result["recommended_question_count"] == 3
    assert result["diagnostic_estimated_minutes"] == 9
    assert round(result["diagnostic_priority"], 4) == 0.6667


def test_sufficient_confidence_creates_no_diagnostic_task():
    result = calculate_diagnostic_priority(
        total_score=120,
        exam_weight=0.05,
        confidence=0.85,
    )

    assert result["recommended_question_count"] == 0
    assert result["diagnostic_estimated_minutes"] == 0
    assert result["diagnostic_priority"] == 0
