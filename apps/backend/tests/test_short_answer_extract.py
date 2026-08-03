"""简短答案提取：支持「故答案为」后的公式图片占位符"""
from app.services.word_parser import _extract_short_answer, _split_answer_analysis


def test_extract_short_answer_plain_text():
    assert _extract_short_answer("故答案为：3．") == "3"
    assert _extract_short_answer("故答案为：40°．") == "40°"
    assert _extract_short_answer("故答案为：1/4．") == "1/4"
    assert _extract_short_answer("故选：C．") == "C"


def test_extract_short_answer_img_placeholder_not_truncated():
    text = "故答案为：[IMG:img_035.png,9.8,26.2]．"
    assert _extract_short_answer(text) == "[IMG:img_035.png,9.8,26.2]"

    text2 = "故答案为：[IMG:img_074.png,12.0,26.2]．\n【点评】考查对称"
    assert _extract_short_answer(text2) == "[IMG:img_074.png,12.0,26.2]"


def test_split_answer_analysis_fill_with_formula_img():
    content = (
        "有8张卡片……概率是　　．\n"
        "【解答】解：……\n"
        "故答案为：[IMG:img_035.png,9.8,26.2]．\n"
        "【点评】考查概率"
    )
    pure, answer, analysis = _split_answer_analysis(content)
    assert "概率" in pure
    assert answer == "[IMG:img_035.png,9.8,26.2]"
    assert analysis and "故答案为" in analysis
