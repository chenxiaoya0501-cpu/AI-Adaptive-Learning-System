import unittest

from app.services.explanation_blocks import (
    markdown_from_blocks,
    normalize_content_blocks,
)


class ExplanationBlocksTest(unittest.TestCase):
    def test_geometry_keeps_only_allowlisted_fields_and_valid_relations(self):
        blocks = normalize_content_blocks([
            {
                "type": "visual",
                "visual_type": "geometry",
                "title": "三角形",
                "on_click": "alert(1)",
                "spec": {
                    "points": [
                        {"id": "A", "x": 10, "y": 20, "label": "A", "onclick": "bad"},
                        {"id": "B", "x": 80, "y": 20, "label": "B"},
                        {"id": "C", "x": 50, "y": 80, "label": "C"},
                    ],
                    "segments": [
                        {"from": "A", "to": "B", "color": "red"},
                        {"from": "A", "to": "missing", "color": "red"},
                    ],
                    "polygons": [{"points": ["A", "B", "C"], "color": "blue"}],
                    "raw_svg": "<script>alert(1)</script>",
                },
            }
        ])
        self.assertEqual(len(blocks), 1)
        self.assertNotIn("on_click", blocks[0])
        self.assertNotIn("raw_svg", blocks[0]["spec"])
        self.assertNotIn("onclick", blocks[0]["spec"]["points"][0])
        self.assertEqual(len(blocks[0]["spec"]["segments"]), 1)

    def test_invalid_function_plot_is_dropped_and_markdown_falls_back(self):
        blocks = normalize_content_blocks(
            [{
                "type": "visual",
                "visual_type": "function_plot",
                "spec": {
                    "x_min": -5,
                    "x_max": 5,
                    "series": [{"label": "y=x", "expression": "window.alert(1)"}],
                },
            }],
            "## 安全文本",
        )
        self.assertEqual(blocks, [{"type": "markdown", "content": "## 安全文本"}])

    def test_number_line_is_clamped_and_markdown_is_derived(self):
        blocks = normalize_content_blocks([
            {"type": "markdown", "content": "先观察数轴。"},
            {
                "type": "diagram",
                "diagram_type": "number_line",
                "caption": "数轴上的点 A",
                "spec": {
                    "min": -5,
                    "max": 5,
                    "step": 1,
                    "markers": [{"value": 999, "label": "A", "color": "unknown"}],
                },
            },
        ])
        self.assertEqual(markdown_from_blocks(blocks), "先观察数轴。")
        self.assertEqual(blocks[1]["visual_type"], "number_line")
        self.assertEqual(blocks[1]["spec"]["markers"][0]["value"], 5)
        self.assertEqual(blocks[1]["spec"]["markers"][0]["color"], "teal")

    def test_chart_requires_matching_labels_and_values(self):
        blocks = normalize_content_blocks([
            {
                "type": "visual",
                "visual_type": "bar_chart",
                "spec": {
                    "labels": ["甲", "乙"],
                    "series": [
                        {"label": "人数", "values": [10]},
                        {"label": "成绩", "values": [80, 90], "color": "green"},
                    ],
                },
            }
        ])
        self.assertEqual(len(blocks[0]["spec"]["series"]), 1)
        self.assertEqual(blocks[0]["spec"]["series"][0]["label"], "成绩")


if __name__ == "__main__":
    unittest.main()
