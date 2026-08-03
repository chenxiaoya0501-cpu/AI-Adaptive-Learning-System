from app.services.pdf_parser import extract_curriculum_numbered_items


def test_curriculum_context_switches_from_function_to_geometry_after_ocr_section():
    pages = [{
        "page_num": 1,
        "text": """
(内容要求]
3
函数
(4) 反比例函数
0结合具体情境体会反比例函数的意义，能确定反比例函数表达式。
@能画反比例函数的图象，理解图象的变化情况。
@能用反比例函数解决简单实际问题。
(学业要求]
1。数与式
@理解有理数的意义，这一条属于学业要求，不能重复抽取。
(内容要求]1. 图形的性质
(1) 点、线、面、角
0通过实物和模型，了解几何体、平面、直线和点等概念。
@会比较线段的长短，理解线段的和、差及线段中点的意义。
@掌握基本事实：两点确定一条直线。
@掌握基本事实：两点之间线段最短。
@理解两点间距离的意义，能度量和表达两点间的距离。
@理解角的概念，能比较角的大小。
""",
    }]

    items = extract_curriculum_numbered_items(pages)

    assert len(items) == 9
    inverse_items = items[:3]
    geometry_items = items[3:]

    assert all(item["domain_hint"] == "数与代数" for item in inverse_items)
    assert all(item["category_1_hint"] == "函数" for item in inverse_items)
    assert all(item["category_2"] == "(4) 反比例函数" for item in inverse_items)
    assert inverse_items[-1]["text"] == "能用反比例函数解决简单实际问题。"

    assert all(item["domain_hint"] == "图形与几何" for item in geometry_items)
    assert all(item["category_1_hint"] == "图形的性质" for item in geometry_items)
    assert all(item["category_2"] == "(1) 点、线、面、角" for item in geometry_items)
    assert not any("学业要求" in item["text"] for item in items)

