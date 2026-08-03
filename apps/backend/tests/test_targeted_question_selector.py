import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.learning.targeted_question_selector import (
    build_selection_plan,
    _difficulty_distribution,
    _estimate_difficulty,
    _largest_remainder,
    _select_candidates,
)


class TargetedQuestionSelectorTest(unittest.TestCase):
    def test_type_quota_sum_is_stable(self):
        quotas = _largest_remainder(
            {"choice": 0.5, "fill": 0.25, "short_answer": 0.25}, 10
        )
        self.assertEqual(sum(quotas.values()), 10)
        self.assertEqual(quotas["choice"], 5)

    def test_difficulty_distribution_uses_20_60_20(self):
        self.assertEqual(_difficulty_distribution(3, 10), {2: 2, 3: 6, 4: 2})
        self.assertEqual(_difficulty_distribution(1, 10), {1: 8, 2: 2})

    def test_recent_wrong_answers_choose_easier_success_target(self):
        now = datetime.utcnow()
        events = [
            {"difficulty": 3, "correct": False, "created_at": now - timedelta(minutes=2)},
            {"difficulty": 3, "correct": False, "created_at": now - timedelta(minutes=1)},
        ]
        result = _estimate_difficulty(events, current_mastery=60)
        self.assertEqual(result["recent_streak"], -2)
        self.assertEqual(result["target_success_rate"], 0.70)

    def test_mock_is_preferred_over_ai_at_same_difficulty(self):
        candidates = [
            SimpleNamespace(id=1, question_type="choice", difficulty=3, bank_type="ai"),
            SimpleNamespace(id=2, question_type="choice", difficulty=3, bank_type="mock"),
        ]
        selected = _select_candidates(
            candidates,
            answered_ids=set(),
            type_quotas={"choice": 1},
            difficulty_quotas={3: 1},
            count=1,
        )
        self.assertEqual(selected[0].bank_type, "mock")

    def test_mock_is_preferred_within_acceptable_difficulty_band(self):
        candidates = [
            SimpleNamespace(id=1, question_type="choice", difficulty=3, bank_type="ai"),
            SimpleNamespace(id=2, question_type="choice", difficulty=4, bank_type="mock"),
        ]
        selected = _select_candidates(
            candidates,
            answered_ids=set(),
            type_quotas={"choice": 1},
            difficulty_quotas={3: 1},
            count=1,
        )
        self.assertEqual(selected[0].bank_type, "mock")

    def test_ai_is_used_when_mock_is_far_from_target_difficulty(self):
        candidates = [
            SimpleNamespace(id=1, question_type="choice", difficulty=1, bank_type="ai"),
            SimpleNamespace(id=2, question_type="choice", difficulty=5, bank_type="mock"),
        ]
        selected = _select_candidates(
            candidates,
            answered_ids=set(),
            type_quotas={"choice": 1},
            difficulty_quotas={1: 1},
            count=1,
        )
        self.assertEqual(selected[0].bank_type, "ai")

    def test_template_quota_is_not_rewritten_by_candidate_inventory(self):
        candidates = [
            SimpleNamespace(
                id=index,
                question_type="choice",
                difficulty=3,
                bank_type="mock",
            )
            for index in range(1, 5)
        ]
        selected, diagnostics = build_selection_plan(
            candidates=candidates,
            template_weights={"choice": 0.5, "fill": 0.25, "short_answer": 0.25},
            template_id=1,
            template_source="kp_average_template",
            events=[],
            answered_ids=set(),
            current_mastery=50,
            question_count=4,
        )
        self.assertEqual(
            diagnostics["type_quotas"],
            {"choice": 2, "fill": 1, "short_answer": 1},
        )
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(question.question_type == "choice" for question in selected))


if __name__ == "__main__":
    unittest.main()
