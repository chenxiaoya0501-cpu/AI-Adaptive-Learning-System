import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from app.schemas.student.course import CourseTutorRequest
from app.services.learning.course_tutor_service import (
    _build_course_context,
    _build_user_prompt,
    _normalize_result,
)


class CourseTutorServiceTests(unittest.TestCase):
    def test_blank_question_is_rejected(self):
        with self.assertRaises(ValidationError):
            CourseTutorRequest(question="   ")

    def test_prompt_only_keeps_recent_history(self):
        history = [
            {"role": "user", "content": f"问题{i}"}
            for i in range(10)
        ]
        prompt = _build_user_prompt("课程资料", "本次问题", history)
        self.assertNotIn("问题0", prompt)
        self.assertNotIn("问题1", prompt)
        self.assertIn("问题2", prompt)
        self.assertIn("问题9", prompt)
        self.assertIn("本次问题", prompt)

    def test_course_context_contains_target_and_explanation(self):
        path = SimpleNamespace(id=8)
        node = SimpleNamespace(
            current_mastery=25.5,
            target_mastery=75,
            role="prerequisite",
        )
        kp = SimpleNamespace(
            short_name="几何图形初步",
            name="认识基本几何图形",
            domain="图形与几何",
            category_1="图形的性质",
            category_2="点线面角",
            grade="七年级上",
            chapter="第一章",
            cognitive_level="理解",
        )
        explanation = SimpleNamespace(
            title="从实物到图形",
            summary="从生活实物抽象几何图形。",
            content="点、线、面、体是构成几何图形的基本元素。",
            key_points='["区分平面图形和立体图形"]',
            examples="[]",
            common_mistakes="[]",
        )
        context = _build_course_context(path, node, kp, explanation)
        self.assertIn("几何图形初步", context)
        self.assertIn("目标掌握度：75", context)
        self.assertIn("点、线、面、体", context)

    def test_result_is_normalized_and_suggestions_are_deduplicated(self):
        result = _normalize_result({
            "answer": "先观察图形的组成部分。",
            "suggested_questions": ["什么是平面图形？", "什么是平面图形？", "如何区分立体图形？"],
        })
        self.assertEqual(result["answer"], "先观察图形的组成部分。")
        self.assertEqual(
            result["suggested_questions"],
            ["什么是平面图形？", "如何区分立体图形？"],
        )


if __name__ == "__main__":
    unittest.main()
