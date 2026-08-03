import unittest

from app.services.learning.mastery_evaluator import evaluate_mastery


def answers(count, correct=True, difficulty=3):
    return [
        {"is_correct": correct, "difficulty": difficulty}
        for _ in range(count)
    ]


class MasteryEvaluatorTest(unittest.TestCase):
    def test_three_questions_cannot_pass(self):
        result = evaluate_mastery(answers(3), target_mastery=75, prior_mastery=None)
        self.assertFalse(result["achieved"])
        self.assertFalse(result["evidence_sufficient"])
        self.assertLess(result["mastery_score"], 75)

    def test_four_correct_questions_can_reach_75(self):
        result = evaluate_mastery(answers(4), target_mastery=75, prior_mastery=None)
        self.assertTrue(result["achieved"])
        self.assertGreaterEqual(result["mastery_score"], 75)

    def test_difficulty_weight_affects_score(self):
        easy_wrong_hard_right = evaluate_mastery(
            [
                {"is_correct": False, "difficulty": 1},
                {"is_correct": True, "difficulty": 5},
                {"is_correct": True, "difficulty": 4},
                {"is_correct": False, "difficulty": 2},
            ],
            target_mastery=75,
            prior_mastery=50,
        )
        hard_wrong_easy_right = evaluate_mastery(
            [
                {"is_correct": True, "difficulty": 1},
                {"is_correct": False, "difficulty": 5},
                {"is_correct": False, "difficulty": 4},
                {"is_correct": True, "difficulty": 2},
            ],
            target_mastery=75,
            prior_mastery=50,
        )
        self.assertGreater(
            easy_wrong_hard_right["mastery_score"],
            hard_wrong_easy_right["mastery_score"],
        )


if __name__ == "__main__":
    unittest.main()
