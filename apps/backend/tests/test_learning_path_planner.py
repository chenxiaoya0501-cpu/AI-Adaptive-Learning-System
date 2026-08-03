from datetime import date

from app.services.learning.path_planner import (
    assign_secondary_category_stages,
    build_plan,
    dependency_order,
    role_for,
    tarjan_components,
)


def _meta(*ids):
    rows = {
        kp_id: {
            "subject": "数学",
            "display_name": kp_id,
            "domain": "数与代数",
            "category_1": "测试主题",
            "category_2": "(1) 测试二级分类",
            "chapter": "测试章",
            "cognitive_level": "掌握",
        }
        for kp_id in ids
    }
    rows["__goal__"] = {"subject": "数学"}
    return rows


def _node(kp_id, score, confidence, attempts):
    return {
        "kp_id": kp_id,
        "mastery_score": score,
        "confidence": confidence,
        "attempt_count": attempts,
        "recent_correct_streak": 0,
        "recent_wrong_streak": 1,
    }


def _plan(
    nodes,
    meta,
    weights,
    prereqs=None,
    dependents=None,
    capacity=240,
    daily_minutes=120,
    current_score=50,
    target_score=90,
):
    prereqs = prereqs or {}
    dependents = dependents or {}
    strengths = {
        (source, target): 1.0
        for source, targets in dependents.items()
        for target in targets
    }
    return build_plan(
        scope_nodes=nodes,
        kp_meta=meta,
        weights=weights,
        weight_sources={kp_id: "template" for kp_id in weights},
        prereqs_by_dependent=prereqs,
        dependent_by_prereq=dependents,
        relation_strengths=strengths,
        total_score=120,
        current_score=current_score,
        target_score=target_score,
        capacity_minutes=capacity,
        daily_minutes=daily_minutes,
        horizon_days=3,
        start_date=date(2026, 7, 29),
    )


def test_tarjan_groups_cycle_as_one_learning_unit():
    components = tarjan_components(
        ["foundation", "algebra", "equation"],
        {
            "foundation": {"algebra"},
            "algebra": {"equation"},
            "equation": {"algebra"},
        },
    )
    assert ["algebra", "equation"] in components
    assert ["foundation"] in components


def test_dependency_order_keeps_prerequisite_before_dependent():
    order, cycles = dependency_order(
        {"number", "equation", "function"},
        {"number": {"equation"}, "equation": {"function"}},
        {"number": 1.0, "equation": 2.0, "function": 3.0},
    )
    assert order.index("number") < order.index("equation") < order.index("function")
    assert cycles == []


def test_secondary_categories_are_indivisible_and_ordered_by_group_utility():
    order, stages, labels, cycles = assign_secondary_category_stages(
        {"alpha", "beta", "gamma"},
        {
            "alpha": {"base_estimated_minutes": 50},
            "beta": {"base_estimated_minutes": 50},
            "gamma": {"base_estimated_minutes": 50},
        },
        {
            "alpha": {"category_1": "一级A", "category_2": "二级A", "display_name": "alpha"},
            "beta": {"category_1": "一级A", "category_2": "二级A", "display_name": "beta"},
            "gamma": {"category_1": "一级B", "category_2": "二级B", "display_name": "gamma"},
        },
        {},
        {"alpha": 0.03, "beta": 0.01, "gamma": 0.06},
        {"alpha": 1.5, "beta": 0.5, "gamma": 3.0},
    )
    assert order == ["gamma", "alpha", "beta"]
    assert stages["gamma"] == 1
    assert stages["alpha"] == stages["beta"] == 2
    assert labels == {1: "二级B", 2: "二级A"}
    assert cycles == []


def test_points_without_secondary_category_fall_back_to_primary_category():
    order, stages, labels, _ = assign_secondary_category_stages(
        {"alpha", "beta"},
        {
            "alpha": {"base_estimated_minutes": 50},
            "beta": {"base_estimated_minutes": 50},
        },
        {
            "alpha": {"category_1": "一级A", "category_2": "", "display_name": "alpha"},
            "beta": {"category_1": "一级A", "category_2": "", "display_name": "beta"},
        },
        {},
        {"alpha": 0.03, "beta": 0.02},
        {"alpha": 1.5, "beta": 1.0},
    )
    assert order == ["alpha", "beta"]
    assert stages["alpha"] == stages["beta"]
    assert labels == {1: "一级A"}


def test_points_without_any_category_keep_separate_fallback_stages():
    order, stages, labels, _ = assign_secondary_category_stages(
        {"alpha", "beta"},
        {
            "alpha": {"base_estimated_minutes": 50},
            "beta": {"base_estimated_minutes": 50},
        },
        {
            "alpha": {"category_1": "", "category_2": "", "display_name": "alpha"},
            "beta": {"category_1": "", "category_2": "", "display_name": "beta"},
        },
        {},
        {"alpha": 0.03, "beta": 0.02},
        {"alpha": 1.5, "beta": 1.0},
    )
    assert order == ["alpha", "beta"]
    assert stages["alpha"] != stages["beta"]
    assert labels == {1: "alpha", 2: "beta"}


def test_role_uses_mastery_and_confidence():
    assert role_for(None, 0.0) == "verify"
    assert role_for(60, 0.8) == "remediate"
    assert role_for(82, 0.8) == "strengthen"
    assert role_for(95, 0.8) == "review"
    assert role_for(95, 0.8, prerequisite=True) == "prerequisite"


def test_zero_weight_untested_node_is_not_used_to_fill_time():
    result = _plan(
        [_node("valuable", 25, 0.8, 3), _node("zero", None, 0, 0)],
        _meta("valuable", "zero"),
        {"valuable": 1.0, "zero": 0.0},
        capacity=500,
    )
    selected = {node["kp_id"] for node in result["nodes"]}
    assert "valuable" in selected
    assert "zero" not in selected
    assert result["summary"]["unused_minutes"] > 0


def test_low_weight_prerequisite_gets_unlock_value_and_precedes_target():
    meta = _meta("base", "target")
    meta["base"]["category_2"] = "二级基础"
    meta["target"]["category_2"] = "二级核心"
    result = _plan(
        [_node("base", 30, 0.8, 2), _node("target", 35, 0.8, 2)],
        meta,
        {"base": 0.0, "target": 1.0},
        prereqs={"target": {"base"}},
        dependents={"base": {"target"}},
        capacity=300,
    )
    nodes = {node["kp_id"]: node for node in result["nodes"]}
    assert nodes["base"]["role"] == "prerequisite"
    assert nodes["base"]["unlock_gain"] > 0
    assert nodes["base"]["order_index"] < nodes["target"]["order_index"]
    assert nodes["base"]["stage_index"] < nodes["target"]["stage_index"]
    assert (
        nodes["base"]["reason"]["stage_basis"]
        == "most_specific_category_marginal_value_and_prerequisite"
    )


def test_same_secondary_category_stays_in_one_stage():
    meta = _meta("alpha", "beta", "gamma")
    meta["alpha"]["category_2"] = "二级A"
    meta["beta"]["category_2"] = "二级A"
    meta["gamma"]["category_2"] = "二级B"
    result = _plan(
        [
            _node("alpha", 30, 0.8, 2),
            _node("beta", 30, 0.8, 2),
            _node("gamma", 30, 0.8, 2),
        ],
        meta,
        {"alpha": 0.4, "beta": 0.35, "gamma": 0.25},
        capacity=360,
        daily_minutes=240,
        current_score=0,
        target_score=120,
    )
    nodes = {node["kp_id"]: node for node in result["nodes"]}
    assert len(nodes) == 3
    assert nodes["alpha"]["stage_index"] == nodes["beta"]["stage_index"]
    assert nodes["alpha"]["stage_index"] != nodes["gamma"]["stage_index"]


def test_unlock_value_participates_in_capacity_selection():
    result = _plan(
        [
            _node("gateway", 30, 0.8, 2),
            _node("future_target", 35, 0.8, 2),
            _node("standalone", 30, 0.8, 2),
        ],
        _meta("gateway", "future_target", "standalone"),
        {"gateway": 0.06, "future_target": 0.82, "standalone": 0.12},
        prereqs={"future_target": {"gateway"}},
        dependents={"gateway": {"future_target"}},
        capacity=70,
    )
    selected = {node["kp_id"] for node in result["nodes"]}
    assert "gateway" in selected
    assert "standalone" not in selected
    assert "future_target" not in selected


def test_insufficient_evidence_is_deferred_to_next_round():
    result = _plan(
        [_node("unknown", None, 0, 0)],
        _meta("unknown"),
        {"unknown": 1.0},
        capacity=30,
    )
    assert result["nodes"] == []
    assert result["tasks"] == []
    assert result["summary"]["expected_gain"] == 0
    assert result["summary"]["insufficient_mastery_evidence_count"] == 1
    assert result["summary"]["deferred_nodes"] == [
        {"kp_id": "unknown", "reason": "insufficient_evidence_next_round"}
    ]


def test_target_with_unverified_prerequisite_is_deferred_to_next_round():
    result = _plan(
        [_node("unknown_base", None, 0, 0), _node("target", 30, 0.8, 3)],
        _meta("unknown_base", "target"),
        {"unknown_base": 0.0, "target": 1.0},
        prereqs={"target": {"unknown_base"}},
        dependents={"unknown_base": {"target"}},
        capacity=240,
    )
    assert result["nodes"] == []
    assert result["summary"]["insufficient_mastery_evidence_count"] == 1
    assert {
        "kp_id": "target",
        "reason": "prerequisite_evidence_insufficient_next_round",
    } in result["summary"]["deferred_nodes"]


def test_path_expected_gain_equals_sum_of_planned_knowledge_point_gains():
    result = _plan(
        [
            _node("alpha", 20, 0.8, 3),
            _node("beta", 35, 0.75, 2),
        ],
        _meta("alpha", "beta"),
        {"alpha": 0.55, "beta": 0.45},
        capacity=320,
        current_score=0,
        target_score=120,
    )

    node_gain_total = sum(float(node["expected_gain"]) for node in result["nodes"])
    node_optimistic_total = sum(
        float(node["reason"]["optimistic_gain"]) for node in result["nodes"]
    )

    assert result["summary"]["expected_gain"] == round(node_gain_total, 1)
    assert result["summary"]["expected_gain_optimistic"] == round(
        node_optimistic_total, 1
    )


def test_more_capacity_does_not_add_unverified_reinforcement_gain():
    nodes = [_node("valuable", 25, 0.8, 3)]
    meta = _meta("valuable")
    short = _plan(
        nodes,
        meta,
        {"valuable": 1.0},
        capacity=100,
        current_score=0,
        target_score=120,
    )
    long = _plan(
        nodes,
        meta,
        {"valuable": 1.0},
        capacity=200,
        current_score=0,
        target_score=120,
    )
    assert long["summary"]["expected_gain"] == short["summary"]["expected_gain"]
    assert long["nodes"][0]["target_mastery"] == short["nodes"][0]["target_mastery"]
    assert "reinforcement_blocks" not in long["nodes"][0]
    assert "reinforcement_gain" not in long["nodes"][0]["reason"]


def test_first_round_contains_no_reinforcement_tasks_or_estimates():
    result = _plan(
        [_node("alpha", 25, 0.8, 3), _node("beta", 25, 0.8, 3)],
        _meta("alpha", "beta"),
        {"alpha": 0.5, "beta": 0.5},
        capacity=320,
        current_score=0,
        target_score=120,
    )
    assert len(result["nodes"]) == 2
    assert all(task["task_type"] != "reinforcement" for task in result["tasks"])
    assert all(
        "reinforcement_gain" not in node["reason"] for node in result["nodes"]
    )
    assert result["summary"]["planning_round"] == 1
    assert result["summary"]["planning_scope"] == "first_pass"
    assert result["summary"]["first_round_completion_date"] == max(
        task["scheduled_date"] for task in result["tasks"]
    ).isoformat()
