"""第3步：真题解析读分 + 各题型下一/二级分类分值比例"""
from types import SimpleNamespace

from app.services.exam_template_service import (
    compute_category_score_stats,
    average_category_score_stats,
    _paper_leaf_maps,
)
from app.services.word_parser import (
    _extract_score_per_question,
    _extract_per_number_scores,
    _detect_section,
    _parse_questions_from_lines,
    _find_split_appendix_index,
)


def test_extract_score_per_question():
    assert _extract_score_per_question("一、选择题（本大题共10小题，每小题3分，共30分）") == 3.0
    assert _extract_score_per_question("二、填空题（每题4分，共24分）") == 4.0
    assert _extract_score_per_question("三、解答题（本大题共6小题，共50分）") is None
    # 含题号分值表时，不能把首个「每题8分」当成全大题统一分
    assert _extract_score_per_question(
        "三、解答题（17-21 每题 8 分，22、23 每题 10 分，24 题 12 分）"
    ) is None


def test_extract_per_number_scores_zhejiang_answer():
    m = _extract_per_number_scores(
        "三、解答题（17-21 每题 8 分，22、23 每题 10 分，24 题 12 分）"
    )
    assert m[17] == 8.0 and m[21] == 8.0
    assert m[22] == 10.0 and m[23] == 10.0
    assert m[24] == 12.0
    assert 16 not in m


def test_detect_section_with_score():
    qtype, score, per = _detect_section(
        "一、选择题（本大题共10小题，每小题3分，共30分。请选出一项。）"
    )
    assert qtype == "choice"
    assert score == 3.0
    assert per == {}


def test_detect_section_single_choice_title():
    """杭州卷常见「一、单选题」（不含「选择」二字）也应识别为 choice。"""
    qtype, score, per = _detect_section("一、单选题")
    assert qtype == "choice"
    assert score is None
    assert per == {}


def test_parse_merges_answer_appendix_on_number_wrap():
    """题号回绕后进入答案附录：不重复建题，答案合并回原题。"""
    lines = [
        "一、单选题",
        "1．题一（  ）",
        "A．1  B．2  C．3  D．4",
        "2．题二（  ）",
        "A．1  B．2  C．3  D．4",
        "二、填空题",
        "3．填空____。",
        "1．B",
        "试题分析：选B。",
        "2．A",
        "3．1",
    ]
    qs = _parse_questions_from_lines(lines)
    assert len(qs) == 3
    assert [q["question_type"] for q in qs] == ["choice", "choice", "fill"]
    assert [q["question_number"] for q in qs] == [1, 2, 3]
    assert qs[0]["answer"] == "B"
    assert qs[1]["answer"] == "A"
    assert qs[2]["answer"] == "1"
    assert "选B" in (qs[0].get("analysis") or "")


def test_hangzhou_split_format_with_参考答案_header():
    """杭州2021式：上半题干 +「参考答案」+ 下半按题号答案，不得拆成两套题。"""
    lines = [
        "浙江省杭州市2021年中考数学真题",
        "一、单选题",
        "1．去括号（  ）",
        "A．1  B．2  C．3  D．4",
        "2．科学计数法（  ）",
        "A．1  B．2  C．3  D．4",
        "二、填空题",
        "3．2a+3a＝_____．",
        "三、解答题",
        "4．解不等式。",
        "参考答案",
        "1．B",
        "【分析】由去括号法则。",
        "【详解】解：… 故选：B．",
        "【点睛】本题考查去括号。",
        "2．B",
        "【详解】故选：B．",
        "3．5a",
        "4．见解析",
        "【详解】解：略。",
    ]
    assert _find_split_appendix_index(lines) == lines.index("参考答案")
    qs = _parse_questions_from_lines(lines)
    assert len(qs) == 4
    assert [q["question_number"] for q in qs] == [1, 2, 3, 4]
    assert qs[0]["question_type"] == "choice" and qs[0]["answer"] == "B"
    assert qs[1]["answer"] == "B"
    assert qs[2]["question_type"] == "fill" and qs[2]["answer"] == "5a"
    assert qs[3]["answer"] == "见解析"
    assert "去括号" in (qs[0].get("analysis") or "")
    # 答案附录不得再生成 content 仅为字母的假题目
    assert all(q.get("content") not in ("B", "A", "5a", "见解析") for q in qs)


def test_candidate_instructions_numbering_does_not_trigger_split():
    """考生须知「1. 2. 3.」不得把真正第1题误判为答案附录起点（否则整卷解析失败）。"""
    lines = [
        "机密★启用前",
        "浙江省2025年初中学业水平考试 数学",
        "考生须知：",
        "1. 本试题卷分选择题和非选择题两部分。",
        "2. 答题前，考生务必将自己的姓名填写清楚。",
        "3. 考试结束后，试题卷和答题卡一并上交。",
        "4. 本卷共24题。",
        "5. 请用黑色字迹作答。",
        "一、选择题（本大题共10小题，每小题3分，共30分）",
        "1．计算：1+1=（  ）",
        "A．1  B．2  C．3  D．4",
        "【答案】B",
        "2．计算：2+2=（  ）",
        "A．1  B．2  C．3  D．4",
        "【答案】D",
        "二、填空题（每题3分）",
        "11．3+1=____。",
        "【答案】4",
    ]
    assert _find_split_appendix_index(lines) is None
    qs = _parse_questions_from_lines(lines)
    assert len(qs) == 3
    assert qs[0]["question_number"] == 1 and qs[0]["question_type"] == "choice"
    assert qs[0]["answer"] == "B"
    assert "考生须知" not in (qs[0].get("content") or "")
    assert "本试题卷分选择题" not in (qs[0].get("content") or "")


def test_parse_lines_writes_section_score():
    lines = [
        "一、选择题（本大题共2小题，每小题3分，共6分）",
        "1．题一（  ）",
        "A．1  B．2  C．3  D．4",
        "【答案】A",
        "2．题二（  ）",
        "A．1  B．2  C．3  D．4",
        "【答案】B",
        "二、填空题（本大题共1小题，每小题4分，共4分）",
        "11．填空____。",
        "【答案】1",
        "三、解答题（本大题共1小题，共8分）",
        "17．解答。",
        "【答案】略",
    ]
    qs = _parse_questions_from_lines(lines)
    by_num = {q["question_number"]: q for q in qs}
    assert by_num[1]["score"] == 3.0
    assert by_num[2]["score"] == 3.0
    assert by_num[11]["score"] == 4.0
    assert by_num[17].get("score") is None


def test_parse_answer_section_per_number_and_stem():
    lines = [
        "三、解答题（17-21 每题 8 分，22、23 每题 10 分，24 题 12 分）",
        "17．（8分）计算。",
        "【答案】1",
        "18．（8分）解方程。",
        "【答案】2",
        "19．无题干分时走题号表。",
        "【答案】3",
        "22．（10分）综合。",
        "【答案】4",
        "24．（12分）压轴。",
        "【答案】5",
    ]
    qs = _parse_questions_from_lines(lines)
    by_num = {q["question_number"]: q for q in qs}
    assert by_num[17]["score"] == 8.0
    assert by_num[18]["score"] == 8.0
    assert by_num[19]["score"] == 8.0  # 题号表
    assert by_num[22]["score"] == 10.0
    assert by_num[24]["score"] == 12.0
    # 题干优先于题号表
    lines2 = [
        "三、解答题（17-21 每题 8 分）",
        "17．（6分）以题干为准。",
        "【答案】1",
    ]
    qs2 = _parse_questions_from_lines(lines2)
    assert qs2[0]["score"] == 6.0


def test_kp_ratio_uses_full_type_total_not_linked_only():
    """占比分母=题型总分（含未挂载），分值来自题目真实 score。"""
    kp_a = SimpleNamespace(category_1="数与式", category_2="(2) 实数")
    kp_b = SimpleNamespace(category_1="函数", category_2="(3)二次函数")
    resolved = [
        (SimpleNamespace(question_type="answer", primary_kp_id="A"), 8.0, False),
        (SimpleNamespace(question_type="answer", primary_kp_id="A"), 10.0, False),
        (SimpleNamespace(question_type="answer", primary_kp_id=None), 40.0, False),  # 未挂载
        (SimpleNamespace(question_type="choice", primary_kp_id="B"), 3.0, False),
        (SimpleNamespace(question_type="choice", primary_kp_id="B"), 3.0, False),
        (SimpleNamespace(question_type="choice", primary_kp_id=None), 24.0, False),
    ]
    stats = compute_category_score_stats(
        resolved,
        {"A": kp_a, "B": kp_b},
        type_order=["answer", "choice"],
    )
    assert stats["type_totals"]["answer"] == 58.0
    assert stats["type_totals"]["choice"] == 30.0
    by_key = {
        (r["question_type"], r["category_1"], r["category_2"]): r
        for r in stats["ratio_rows"]
    }
    ans = by_key[("answer", "数与式", "(2) 实数")]
    assert ans["score_sum"] == 18.0
    assert ans["score_ratio"] == round(18.0 / 58.0, 4)
    # 绝不能按「仅已挂载 18」做成 100%
    assert abs(ans["score_ratio"] - 1.0) > 0.01
    ch = by_key[("choice", "函数", "(3)二次函数")]
    assert ch["score_sum"] == 6.0
    assert ch["score_ratio"] == round(6.0 / 30.0, 4)


def test_multi_paper_equal_weight_average_ratio():
    """多套：对各卷占比等权平均，避免大卷主导（≠ 合卷加总）。"""
    kp = SimpleNamespace(category_1="函数", category_2="(3)二次函数")
    meta = {"K": kp}
    # 卷A：30 分选择题里 15 分该分类 → 50%
    paper_a = [
        (SimpleNamespace(question_type="choice", primary_kp_id="K"), 15.0, False),
        (SimpleNamespace(question_type="choice", primary_kp_id=None), 15.0, False),
    ]
    # 卷B：90 分选择题里 9 分该分类 → 10%
    paper_b = [
        (SimpleNamespace(question_type="choice", primary_kp_id="K"), 9.0, False),
        (SimpleNamespace(question_type="choice", primary_kp_id=None), 81.0, False),
    ]
    stats = average_category_score_stats(
        [_paper_leaf_maps(paper_a, meta), _paper_leaf_maps(paper_b, meta)],
        type_order=["choice"],
    )
    # 等权平均占比 (50%+10%)/2 = 30%；合卷加总是 24/120 = 20%
    assert stats["aggregate"] == "equal_weight_mean_ratio"
    assert stats["type_totals"]["choice"] == 60.0  # (30+90)/2
    row = stats["ratio_rows"][0]
    assert row["score_ratio"] == round(0.3, 4)
    assert row["score_sum"] == round(0.3 * 60.0, 2)
