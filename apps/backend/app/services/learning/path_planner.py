"""学习路径 v2 纯算法：候选准入、价值计算、依赖优化与主题排期。"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ALGORITHM_VERSION = "path-v2.8"
STABLE_MASTERY = 90.0
STABLE_CONFIDENCE = 0.70
CORE_MASTERY = 75.0
LOW_CONFIDENCE = 0.35
MAX_PREREQUISITE_DEPTH = 5
MIN_DIRECT_GAIN = 0.05
MIN_GAIN_PER_MINUTE = 0.0005
UNLOCK_ALPHA = 0.70
DISTANCE_DECAY = 0.70
REINFORCEMENT_TARGETS = (0.82, 0.88, 0.94, 1.00)
REINFORCEMENT_GAP_DAYS = (1, 2, 4, 7)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def percentile(values: List[float], ratio: float) -> float:
    positive = sorted(v for v in values if v > 0)
    if not positive:
        return 0.0
    index = min(len(positive) - 1, max(0, math.ceil(len(positive) * ratio) - 1))
    return positive[index]


def effective_mastery(score: Optional[float], confidence: float) -> float:
    if score is None:
        return 0.50
    return clamp(confidence) * clamp(score / 100.0) + (1 - clamp(confidence)) * 0.50


def role_for(score: Optional[float], confidence: float, prerequisite: bool = False) -> str:
    if prerequisite:
        return "prerequisite"
    if score is None or confidence < LOW_CONFIDENCE:
        return "verify"
    if score < CORE_MASTERY:
        return "remediate"
    if score < STABLE_MASTERY:
        return "strengthen"
    return "review"


def cognitive_base_minutes(level: Optional[str]) -> int:
    text = (level or "").strip()
    if "运用" in text or "应用" in text:
        return 75
    if "掌握" in text:
        return 55
    if "理解" in text:
        return 40
    return 25


def learnability(level: Optional[str], evidence: Dict[str, Any]) -> float:
    text = (level or "").strip()
    base = 0.55 if ("运用" in text or "应用" in text) else 0.65 if "掌握" in text else 0.75 if "理解" in text else 0.85
    correct_streak = min(2, int(evidence.get("recent_correct_streak") or 0))
    wrong_streak = min(2, int(evidence.get("recent_wrong_streak") or 0))
    return clamp(base + correct_streak * 0.04 - wrong_streak * 0.05, 0.35, 0.90)


def transfer_rate(weight_source: str, cognitive_level: Optional[str]) -> float:
    rate = 0.82 if weight_source == "template" else 0.72
    if "运用" in (cognitive_level or ""):
        rate -= 0.08
    return clamp(rate, 0.50, 0.88)


def target_mastery(weight: float, high_cut: float, medium_cut: float, cognitive_level: Optional[str]) -> float:
    target = 0.88 if high_cut > 0 and weight >= high_cut else 0.82 if medium_cut > 0 and weight >= medium_cut else 0.75
    if "运用" in (cognitive_level or ""):
        target = min(0.90, target + 0.03)
    return target


def estimate_minutes(
    cognitive_level: Optional[str], gap: float, confidence: float, role: str
) -> int:
    if role == "verify":
        return 10
    base = cognitive_base_minutes(cognitive_level)
    uncertainty = 1 + 0.25 * (1 - clamp(confidence))
    return max(20, min(120, round(base * (0.65 + gap) * uncertainty)))


def reinforcement_minutes(
    cognitive_level: Optional[str], mastery_increment: float, pass_index: int
) -> int:
    """Estimate one spaced reinforcement block."""
    base = cognitive_base_minutes(cognitive_level)
    spacing_factor = 1 + max(0, pass_index - 1) * 0.08
    return max(
        12,
        min(
            60,
            round(base * (0.25 + 1.80 * mastery_increment) * spacing_factor),
        ),
    )


def reinforcement_blocks(
    item: Dict[str, Any],
    meta: Dict[str, Any],
    total_score: float,
) -> List[Dict[str, Any]]:
    """Build sequential marginal blocks beyond the first-pass mastery target."""
    start = clamp(float(item["target_mastery"]) / 100)
    effective = clamp(float(item["effective_mastery"]) / 100)
    learn = float(item.get("learnability") or 0.65)
    transfer = float(item.get("transfer_rate") or 0.70)
    previous_probability = learn * transfer
    previous_optimistic_probability = min(0.95, learn + 0.15) * min(
        0.95, transfer + 0.10
    )
    blocks: List[Dict[str, Any]] = []
    current = start
    for pass_index, target in enumerate(
        (value for value in REINFORCEMENT_TARGETS if value > start + 1e-9),
        start=1,
    ):
        increment = target - current
        success = min(0.98, learn + 0.08 * pass_index)
        applied_transfer = min(0.98, transfer + 0.06 * pass_index)
        probability = success * applied_transfer
        optimistic_probability = min(0.995, success + 0.08) * min(
            0.995, applied_transfer + 0.05
        )
        weighted_score = total_score * float(item["exam_weight"])
        existing_span = max(0.0, current - effective)
        # Reinforcement has two effects: it raises the mastery ceiling and also
        # increases the probability that already planned learning is retained and
        # transferred into the exam. The latter was missing in the one-pass model.
        gain = weighted_score * (
            increment * probability
            + existing_span * max(0.0, probability - previous_probability)
        )
        optimistic_gain = weighted_score * (
            increment * optimistic_probability
            + existing_span
            * max(
                0.0,
                optimistic_probability - previous_optimistic_probability,
            )
        )
        blocks.append(
            {
                "pass_index": pass_index,
                "from_mastery": round(current * 100, 1),
                "to_mastery": round(target * 100, 1),
                "estimated_minutes": reinforcement_minutes(
                    meta.get("cognitive_level"), increment, pass_index
                ),
                "expected_gain": gain,
                "optimistic_gain": optimistic_gain,
            }
        )
        current = target
        previous_probability = probability
        previous_optimistic_probability = optimistic_probability
    return blocks


def tarjan_components(nodes: Iterable[str], edges: Dict[str, Set[str]]) -> List[List[str]]:
    node_set = set(nodes)
    index = 0
    indices: Dict[str, int] = {}
    low: Dict[str, int] = {}
    stack: List[str] = []
    on_stack: Set[str] = set()
    result: List[List[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(edges.get(node, set()) & node_set):
            if nxt not in indices:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], indices[nxt])
        if low[node] == indices[node]:
            component: List[str] = []
            while stack:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            result.append(sorted(component))

    for node in sorted(node_set):
        if node not in indices:
            visit(node)
    return result


def dependency_order(
    selected: Set[str], prerequisite_to_dependent: Dict[str, Set[str]], utility: Dict[str, float]
) -> Tuple[List[str], List[List[str]]]:
    components = tarjan_components(selected, prerequisite_to_dependent)
    component_of = {node: i for i, group in enumerate(components) for node in group}
    dag: Dict[int, Set[int]] = defaultdict(set)
    indegree = {i: 0 for i in range(len(components))}
    for source in selected:
        for target in prerequisite_to_dependent.get(source, set()) & selected:
            a, b = component_of[source], component_of[target]
            if a != b and b not in dag[a]:
                dag[a].add(b)
                indegree[b] += 1
    ready = [i for i, degree in indegree.items() if degree == 0]
    order: List[str] = []
    while ready:
        ready.sort(
            key=lambda i: max((utility.get(kp, 0.0) for kp in components[i]), default=0),
            reverse=True,
        )
        current = ready.pop(0)
        order.extend(sorted(components[current], key=lambda kp: utility.get(kp, 0), reverse=True))
        for nxt in dag.get(current, set()):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    return order, [group for group in components if len(group) > 1]


def assign_secondary_category_stages(
    selected: Set[str],
    items: Dict[str, Dict[str, Any]],
    kp_meta: Dict[str, Dict[str, Any]],
    prerequisite_to_dependent: Dict[str, Set[str]],
    utility: Dict[str, float],
    strategic_value: Dict[str, float],
) -> Tuple[List[str], Dict[str, int], Dict[int, str], List[List[str]]]:
    """Build dependency-safe stages from the most specific available category.

    Categories are ordered by aggregate marginal value. Knowledge points use
    category_2 when available; otherwise they fall back to category_1 and stay
    in the same primary-category stage. Only points without either category
    receive a private fallback group.
    """
    group_by_kp: Dict[str, str] = {}
    group_labels: Dict[str, str] = {}
    group_members: Dict[str, Set[str]] = defaultdict(set)
    for kp_id in selected:
        meta = kp_meta[kp_id]
        category_1 = (meta.get("category_1") or "").strip()
        category_2 = (meta.get("category_2") or "").strip()
        if category_2:
            group_key = f"{category_1}\x1f{category_2}"
            group_label = category_2
        elif category_1:
            group_key = f"__primary__\x1f{category_1}"
            group_label = category_1
        else:
            group_key = f"__uncategorized__\x1f{kp_id}"
            group_label = meta["display_name"]
        group_by_kp[kp_id] = group_key
        group_labels[group_key] = group_label
        group_members[group_key].add(kp_id)

    group_edges: Dict[str, Set[str]] = defaultdict(set)
    for source in selected:
        source_group = group_by_kp[source]
        for target in prerequisite_to_dependent.get(source, set()) & selected:
            target_group = group_by_kp[target]
            if source_group != target_group:
                group_edges[source_group].add(target_group)

    group_utility: Dict[str, float] = {}
    for group_key, members in group_members.items():
        value = sum(strategic_value[kp_id] for kp_id in members)
        minutes = sum(
            max(
                1,
                int(
                    items[kp_id].get("base_estimated_minutes")
                    or items[kp_id].get("estimated_minutes")
                    or 1
                ),
            )
            for kp_id in members
        )
        group_utility[group_key] = value / max(minutes, 1)

    group_order, group_cycles = dependency_order(
        set(group_members),
        group_edges,
        group_utility,
    )
    order: List[str] = []
    stage_by_kp: Dict[str, int] = {}
    stage_labels: Dict[int, str] = {}
    node_cycles: List[List[str]] = []
    for stage_index, group_key in enumerate(group_order, start=1):
        members = group_members[group_key]
        restricted_edges = {
            kp_id: prerequisite_to_dependent.get(kp_id, set()) & members
            for kp_id in members
        }
        group_node_order, cycles = dependency_order(
            members,
            restricted_edges,
            utility,
        )
        order.extend(group_node_order)
        node_cycles.extend(cycles)
        stage_labels[stage_index] = group_labels[group_key]
        for kp_id in group_node_order:
            stage_by_kp[kp_id] = stage_index

    return order, stage_by_kp, stage_labels, [*group_cycles, *node_cycles]


def weak_prerequisite_closure(
    kp_id: str,
    prereqs_by_dependent: Dict[str, Set[str]],
    mastery: Dict[str, Tuple[Optional[float], float]],
    valid_ids: Set[str],
) -> Set[str]:
    found: Set[str] = set()
    frontier = [(kp_id, 0)]
    while frontier:
        current, depth = frontier.pop()
        if depth >= MAX_PREREQUISITE_DEPTH:
            continue
        for prerequisite in prereqs_by_dependent.get(current, set()):
            score, confidence = mastery.get(prerequisite, (None, 0.0))
            if prerequisite in valid_ids and (
                score is None or score < CORE_MASTERY or confidence < LOW_CONFIDENCE
            ):
                if prerequisite not in found:
                    found.add(prerequisite)
                    frontier.append((prerequisite, depth + 1))
    return found


def _descendant_unlock_values(
    direct_candidates: Dict[str, Dict[str, Any]],
    prereqs_by_dependent: Dict[str, Set[str]],
    relation_strengths: Dict[Tuple[str, str], float],
) -> Dict[str, float]:
    unlock: Dict[str, float] = defaultdict(float)
    for target_id, target in direct_candidates.items():
        frontier = [(target_id, 0, 1.0)]
        seen = {target_id}
        while frontier:
            current, depth, path_strength = frontier.pop(0)
            if depth >= MAX_PREREQUISITE_DEPTH:
                continue
            prerequisites = prereqs_by_dependent.get(current, set())
            if not prerequisites:
                continue
            total_strength = sum(
                max(0.05, relation_strengths.get((prerequisite, current), 1.0))
                for prerequisite in prerequisites
            )
            for prerequisite in prerequisites:
                if prerequisite in seen:
                    continue
                seen.add(prerequisite)
                share = (
                    max(0.05, relation_strengths.get((prerequisite, current), 1.0))
                    / total_strength
                )
                distance = depth + 1
                unlock[prerequisite] += (
                    target["direct_gain"]
                    * share
                    * path_strength
                    * (DISTANCE_DECAY ** (distance - 1))
                )
                frontier.append((prerequisite, distance, path_strength * share))
    return dict(unlock)


def _theme(meta: Dict[str, Any]) -> str:
    return (
        (meta.get("category_1") or "").strip()
        or (meta.get("domain") or "").strip()
        or (meta.get("chapter") or "").strip()
        or "综合基础"
    )


def _stage_type(role: str, cognitive_level: Optional[str]) -> str:
    if role == "prerequisite":
        return "foundation"
    if role == "verify":
        return "verify"
    if role == "strengthen" or "运用" in (cognitive_level or ""):
        return "transfer"
    return "core"


def _base_task_specs(node: Dict[str, Any]) -> List[Tuple[str, str, int]]:
    base_minutes = int(
        node.get("base_estimated_minutes") or node["estimated_minutes"]
    )
    if node["role"] == "verify":
        return [("checkpoint", "短测验证", base_minutes)]
    return [
        ("concept", "概念学习", max(8, round(base_minutes * 0.35))),
        ("practice", "针对练习", max(8, round(base_minutes * 0.45))),
        ("checkpoint", "掌握检查", max(8, round(base_minutes * 0.20))),
    ]


def _schedule_tasks(
    nodes: List[Dict[str, Any]],
    daily_minutes: int,
    horizon_days: int,
    start_date: date,
) -> List[Dict[str, Any]]:
    """Expand selected knowledge points into a chronological execution plan.

    Knowledge-point order decides which first-pass block enters the path first.
    Reinforcement is a separate scheduling layer: a due reinforcement block is
    inserted between later first-pass blocks instead of being appended directly
    to the originating knowledge point.
    """
    tasks: List[Dict[str, Any]] = []
    pending_reinforcement: List[Dict[str, Any]] = []
    day_offset = 0
    day_used = 0
    sequence = 1
    max_day_offset = max(0, horizon_days - 1)
    daily_capacity = max(1, daily_minutes)

    def advance_for(minutes: int) -> None:
        nonlocal day_offset, day_used
        if day_used and day_used + minutes > daily_capacity:
            if day_offset < max_day_offset:
                day_offset += 1
                day_used = 0

    def append_task(
        node: Dict[str, Any],
        task_type: str,
        label: str,
        minutes: int,
        *,
        first_base_task: bool = False,
        instruction: Optional[str] = None,
    ) -> None:
        nonlocal day_used, sequence
        advance_for(minutes)
        blocked_by_prerequisite = bool(node["prerequisite_kp_ids"])
        tasks.append(
            {
                "kp_id": node["kp_id"],
                "scheduled_date": start_date + timedelta(days=day_offset),
                "sequence": sequence,
                "task_type": task_type,
                "title": f"{label}：{node['name']}",
                "instruction": instruction or node["reason"]["summary"],
                "estimated_minutes": minutes,
                "status": (
                    "pending"
                    if first_base_task
                    and not blocked_by_prerequisite
                    and day_offset == 0
                    else "blocked"
                ),
            }
        )
        day_used += minutes
        sequence += 1

    def enqueue_reinforcement(
        node: Dict[str, Any], block_index: int, from_day: int
    ) -> None:
        blocks = node.get("reinforcement_blocks", [])
        if block_index >= len(blocks):
            return
        gap = REINFORCEMENT_GAP_DAYS[
            min(block_index, len(REINFORCEMENT_GAP_DAYS) - 1)
        ]
        pending_reinforcement.append(
            {
                "node": node,
                "block_index": block_index,
                "eligible_day": min(max_day_offset, from_day + gap),
            }
        )

    node_index = 0
    while node_index < len(nodes) or pending_reinforcement:
        due = [
            item
            for item in pending_reinforcement
            if item["eligible_day"] <= day_offset
        ]
        if due:
            due.sort(
                key=lambda item: (
                    item["eligible_day"],
                    -(
                        float(
                            item["node"]["reinforcement_blocks"][
                                item["block_index"]
                            ]["expected_gain"]
                        )
                        / max(
                            int(
                                item["node"]["reinforcement_blocks"][
                                    item["block_index"]
                                ]["estimated_minutes"]
                            ),
                            1,
                        )
                    ),
                    item["node"]["order_index"],
                    item["block_index"],
                )
            )
            item = due[0]
            pending_reinforcement.remove(item)
            node = item["node"]
            block_index = item["block_index"]
            block = node["reinforcement_blocks"][block_index]
            round_number = block_index + 1
            append_task(
                node,
                "reinforcement",
                f"第 {round_number} 轮强化至 {block['to_mastery']:.0f} 分",
                int(block["estimated_minutes"]),
                instruction=(
                    f"这是该知识点的第 {round_number} 轮间隔强化，"
                    f"目标掌握度由 {block['from_mastery']:.0f} 分提升至 "
                    f"{block['to_mastery']:.0f} 分。"
                ),
            )
            enqueue_reinforcement(node, block_index + 1, day_offset)
            continue

        if node_index < len(nodes):
            node = nodes[node_index]
            for task_index, (task_type, label, minutes) in enumerate(
                _base_task_specs(node)
            ):
                append_task(
                    node,
                    task_type,
                    label,
                    minutes,
                    first_base_task=task_index == 0,
                )
            enqueue_reinforcement(node, 0, day_offset)
            node_index += 1
            continue

        next_day = min(
            int(item["eligible_day"]) for item in pending_reinforcement
        )
        if next_day > day_offset:
            day_offset = next_day
            day_used = 0

    return tasks


def build_plan(
    *,
    scope_nodes: List[Dict[str, Any]],
    kp_meta: Dict[str, Dict[str, Any]],
    weights: Dict[str, float],
    weight_sources: Dict[str, str],
    prereqs_by_dependent: Dict[str, Set[str]],
    dependent_by_prereq: Dict[str, Set[str]],
    relation_strengths: Dict[Tuple[str, str], float],
    total_score: float,
    current_score: float,
    target_score: float,
    capacity_minutes: int,
    daily_minutes: int,
    horizon_days: int,
    start_date: date,
) -> Dict[str, Any]:
    valid_ids = {
        node["kp_id"]
        for node in scope_nodes
        if node.get("kp_id") in kp_meta
        and kp_meta[node["kp_id"]].get("subject") == kp_meta.get("__goal__", {}).get("subject")
    }
    mastery: Dict[str, Tuple[Optional[float], float]] = {
        node["kp_id"]: (
            None if node.get("mastery_score") is None else float(node["mastery_score"]),
            float(node.get("confidence") or 0.0),
        )
        for node in scope_nodes
        if node.get("kp_id") in valid_ids
    }
    evidence = {node["kp_id"]: node for node in scope_nodes if node.get("kp_id") in valid_ids}
    positive_weights = [weights.get(kp_id, 0.0) for kp_id in valid_ids]
    medium_cut = percentile(positive_weights, 0.50)
    high_cut = percentile(positive_weights, 0.75)

    excluded: List[Dict[str, Any]] = []
    direct: Dict[str, Dict[str, Any]] = {}
    verify: Dict[str, Dict[str, Any]] = {}
    for kp_id in sorted(valid_ids):
        node = evidence[kp_id]
        meta = kp_meta[kp_id]
        score, confidence = mastery.get(kp_id, (None, 0.0))
        attempts = int(node.get("attempt_count") or 0)
        weight = max(0.0, float(weights.get(kp_id, 0.0)))
        if score is not None and score >= STABLE_MASTERY and confidence >= STABLE_CONFIDENCE:
            excluded.append({"kp_id": kp_id, "reason": "stable_mastery"})
            continue
        relevant = weight > 0 or attempts > 0
        if not relevant:
            excluded.append({"kp_id": kp_id, "reason": "no_target_value_or_evidence"})
            continue
        role = role_for(score, confidence)
        effective = effective_mastery(score, confidence)
        target = target_mastery(weight, high_cut, medium_cut, meta.get("cognitive_level"))
        gap = max(0.0, target - effective)
        learn = learnability(meta.get("cognitive_level"), node)
        transfer = transfer_rate(weight_sources.get(kp_id, "empirical"), meta.get("cognitive_level"))
        raw_gain = total_score * weight * gap
        direct_gain = raw_gain * learn * transfer
        optimistic_gain = raw_gain * min(0.95, learn + 0.15) * min(0.95, transfer + 0.10)
        minutes = estimate_minutes(meta.get("cognitive_level"), gap, confidence, role)
        item = {
            "kp_id": kp_id,
            "role": role,
            "current_mastery": score,
            "effective_mastery": effective * 100,
            "target_mastery": target * 100,
            "confidence": confidence,
            "attempt_count": attempts,
            "exam_weight": weight,
            "weight_source": weight_sources.get(kp_id, "none"),
            "direct_gain": direct_gain,
            "optimistic_gain": optimistic_gain,
            "unlock_gain": 0.0,
            "information_value": 0.0,
            "estimated_minutes": minutes,
            "base_estimated_minutes": minutes,
            "base_target_mastery": target * 100,
            "learnability": learn,
            "transfer_rate": transfer,
            "reinforcement_blocks": [],
            "admission_reason": [
                *(["EXAM_WEIGHT"] if weight > 0 else []),
                *(["DIRECT_ASSESSMENT"] if attempts > 0 else []),
                *(
                    ["LOW_MASTERY"]
                    if score is not None and score < CORE_MASTERY
                    else ["LOW_CONFIDENCE"]
                    if role == "verify"
                    else ["MASTERY_GAP"]
                ),
            ],
        }
        if role == "verify":
            if weight > 0:
                # 验证任务只产生信息价值，不能在验证前承诺直接提分。
                item["direct_gain"] = 0.0
                item["optimistic_gain"] = 0.0
                item["information_value"] = total_score * weight * (1 - confidence) * 0.20
                verify[kp_id] = item
            else:
                excluded.append({"kp_id": kp_id, "reason": "low_value_verify"})
            continue
        if direct_gain < MIN_DIRECT_GAIN:
            excluded.append({"kp_id": kp_id, "reason": "direct_gain_below_threshold"})
            continue
        direct[kp_id] = item

    unlock_values = _descendant_unlock_values(
        direct, prereqs_by_dependent, relation_strengths
    )
    for kp_id, value in unlock_values.items():
        if kp_id in direct:
            direct[kp_id]["unlock_gain"] = value
    selected: Set[str] = set()
    selected_minutes = 0
    expected_gain = 0.0
    optimistic_gain = 0.0
    remaining = set(direct)
    deferred: List[Dict[str, Any]] = []
    insufficient_evidence_ids: Set[str] = set(verify)

    # 目标知识点即使自身证据充分，只要必要前置的掌握情况尚不清楚，
    # 也不能在首轮假定其前置薄弱并直接安排学习；统一留待首轮复测后重算。
    for target_id in sorted(tuple(remaining)):
        prerequisites = weak_prerequisite_closure(
            target_id, prereqs_by_dependent, mastery, valid_ids
        )
        uncertain_prerequisites = {
            kp_id
            for kp_id in prerequisites
            if mastery.get(kp_id, (None, 0.0))[0] is None
            or mastery.get(kp_id, (None, 0.0))[1] < LOW_CONFIDENCE
        }
        if not uncertain_prerequisites:
            continue
        insufficient_evidence_ids.update(uncertain_prerequisites)
        deferred.append(
            {
                "kp_id": target_id,
                "reason": "prerequisite_evidence_insufficient_next_round",
            }
        )
        remaining.remove(target_id)

    while remaining:
        bundles: List[Tuple[float, str, Set[str], int, float, float]] = []
        for target_id in remaining:
            prerequisites = weak_prerequisite_closure(
                target_id, prereqs_by_dependent, mastery, valid_ids
            ) - selected
            incremental_ids = {target_id, *prerequisites} - selected
            incremental_minutes = 0
            bundle_direct_gain = 0.0
            bundle_optimistic = 0.0
            for kp_id in incremental_ids:
                if kp_id in direct:
                    data = direct[kp_id]
                    bundle_direct_gain += data["direct_gain"]
                    bundle_optimistic += data["optimistic_gain"]
                    incremental_minutes += data["estimated_minutes"]
                else:
                    meta = kp_meta[kp_id]
                    score, confidence = mastery.get(kp_id, (None, 0.0))
                    effective = effective_mastery(score, confidence)
                    gap = max(0.0, 0.75 - effective)
                    incremental_minutes += estimate_minutes(
                        meta.get("cognitive_level"), gap, confidence, "prerequisite"
                    )
            # 一个增量包完成后，真正新增的“前沿”是目标节点本身。
            # 必要前置的 unlock_gain 已包含该目标收益，若再次逐个累加会让同一后继
            # 沿依赖链被重复计算，错误偏向很长的前置链。
            bundle_strategic_value = (
                bundle_direct_gain
                + UNLOCK_ALPHA * direct[target_id].get("unlock_gain", 0.0)
            )
            # 学习任务只使用“首轮直接提分 + 后继解锁价值”排序；
            # 诊断任务使用独立优先级，不与学习收益混合。
            # 路径预计提分仍只累计 direct_gain，避免将同一后继收益重复算分。
            utility = bundle_strategic_value / max(incremental_minutes, 1)
            bundles.append(
                (
                    utility,
                    target_id,
                    prerequisites,
                    incremental_minutes,
                    bundle_direct_gain,
                    bundle_optimistic,
                )
            )
        best = max(bundles, key=lambda item: (item[0], direct[item[1]]["direct_gain"], item[1]))
        utility, target_id, prerequisites, incremental_minutes, bundle_gain, bundle_optimistic = best
        if utility < MIN_GAIN_PER_MINUTE or bundle_gain <= 0:
            for kp_id in sorted(remaining):
                deferred.append({"kp_id": kp_id, "reason": "utility_below_threshold"})
            break
        if selected_minutes + incremental_minutes > capacity_minutes:
            deferred.append({"kp_id": target_id, "reason": "capacity_insufficient"})
            remaining.remove(target_id)
            continue
        for prerequisite in prerequisites:
            if prerequisite not in direct:
                score, confidence = mastery.get(prerequisite, (None, 0.0))
                meta = kp_meta[prerequisite]
                effective = effective_mastery(score, confidence)
                gap = max(0.0, 0.75 - effective)
                minutes = estimate_minutes(
                    meta.get("cognitive_level"), gap, confidence, "prerequisite"
                )
                direct[prerequisite] = {
                    "kp_id": prerequisite,
                    "role": "prerequisite",
                    "current_mastery": score,
                    "effective_mastery": effective * 100,
                    "target_mastery": 75.0,
                    "confidence": confidence,
                    "attempt_count": int(evidence.get(prerequisite, {}).get("attempt_count") or 0),
                    "exam_weight": weights.get(prerequisite, 0.0),
                    "weight_source": weight_sources.get(prerequisite, "none"),
                    "direct_gain": 0.0,
                    "optimistic_gain": 0.0,
                    "unlock_gain": unlock_values.get(prerequisite, direct[target_id]["direct_gain"]),
                    "information_value": 0.0,
                    "estimated_minutes": minutes,
                    "base_estimated_minutes": minutes,
                    "base_target_mastery": 75.0,
                    "learnability": 0.0,
                    "transfer_rate": 0.0,
                    "reinforcement_blocks": [],
                    "admission_reason": ["PREREQUISITE_FOR", target_id],
                }
            selected.add(prerequisite)
        selected.add(target_id)
        selected_minutes += incremental_minutes
        expected_gain += bundle_gain
        optimistic_gain += bundle_optimistic
        # 前置节点本身也可能是直接提分候选；一旦随增量包纳入，
        # 必须从剩余候选移除，避免收益和时间重复计算。
        remaining -= selected
        if expected_gain >= max(0.0, target_score - current_score):
            for kp_id in sorted(remaining):
                deferred.append({"kp_id": kp_id, "reason": "gain_target_reached"})
            break

    # 本版本只生成首轮学习闭环。低置信度知识点需要先通过本轮复测积累
    # 有效作答证据，后续强化也必须基于首轮结果重新计算，二者均不进入本轮。
    for kp_id in sorted(verify):
        deferred.append(
            {"kp_id": kp_id, "reason": "insufficient_evidence_next_round"}
        )

    first_pass_value: Dict[str, float] = {}
    utility_map: Dict[str, float] = {}
    for kp_id in selected:
        item = direct[kp_id]
        strategic_value = (
            float(item["direct_gain"])
            + UNLOCK_ALPHA * float(item.get("unlock_gain", 0.0))
        )
        first_pass_value[kp_id] = strategic_value
        utility_map[kp_id] = strategic_value / max(
            int(item.get("base_estimated_minutes") or item["estimated_minutes"]),
            1,
        )
    order, stage_by_kp, stage_labels, cycles = assign_secondary_category_stages(
        selected,
        direct,
        kp_meta,
        dependent_by_prereq,
        utility_map,
        first_pass_value,
    )

    nodes: List[Dict[str, Any]] = []
    for order_index, kp_id in enumerate(order, start=1):
        item = direct[kp_id]
        meta = kp_meta[kp_id]
        stage_type = _stage_type(item["role"], meta.get("cognitive_level"))
        knowledge_theme = _theme(meta)
        category_1 = (meta.get("category_1") or "").strip()
        category_2 = (meta.get("category_2") or "").strip()
        stage_index = stage_by_kp[kp_id]
        stage_theme = stage_labels[stage_index]
        strategic_value = first_pass_value[kp_id]
        reason_summary = (
            "自身分值不高，但属于已选核心考点的必要前置"
            if item["role"] == "prerequisite"
            else "属于高价值但低置信度考点，先验证再决定是否补学"
            if item["role"] == "verify"
            else "存在明确作答薄弱证据，且对当前目标有直接提分价值"
        )
        node_item = {
            key: value
            for key, value in item.items()
            if key != "reinforcement_blocks"
        }
        nodes.append(
            {
                **node_item,
                "name": meta["display_name"],
                "order_index": order_index,
                "stage_index": stage_index,
                "stage_type": stage_type,
                "stage_theme": stage_theme,
                "priority": utility_map[kp_id],
                "expected_gain": item["direct_gain"],
                "prerequisite_kp_ids": sorted(
                    prereqs_by_dependent.get(kp_id, set()) & selected
                ),
                "reason": {
                    "summary": reason_summary,
                    "admission_reason": item["admission_reason"],
                    "stage_theme": stage_theme,
                    "stage_basis": "most_specific_category_marginal_value_and_prerequisite",
                    "knowledge_theme": knowledge_theme,
                    "category_1": category_1,
                    "category_2": category_2,
                    "effective_mastery": round(item["effective_mastery"], 1),
                    "base_target_mastery": round(item["base_target_mastery"], 1),
                    "direct_gain": round(item["direct_gain"], 2),
                    "optimistic_gain": round(item["optimistic_gain"], 2),
                    "base_direct_gain": round(item["direct_gain"], 2),
                    "unlock_gain": round(item.get("unlock_gain", 0.0), 2),
                    "information_value": round(item.get("information_value", 0.0), 2),
                    "information_value_explanation": (
                        "用于衡量补测后减少认知不确定性的价值，仅参与排期，不计入预计提分"
                        if item.get("information_value", 0.0) > 0
                        else ""
                    ),
                    "strategic_value": round(strategic_value, 2),
                    "marginal_value": round(utility_map[kp_id], 4),
                    "weight_source": item["weight_source"],
                    "learnability": round(float(item.get("learnability") or 0.0), 4),
                    "transfer_rate": round(float(item.get("transfer_rate") or 0.0), 4),
                    "recent_correct_streak": int(
                        evidence.get(kp_id, {}).get("recent_correct_streak") or 0
                    ),
                    "recent_wrong_streak": int(
                        evidence.get(kp_id, {}).get("recent_wrong_streak") or 0
                    ),
                },
            }
        )

    # 单一事实来源：路径提分必须严格等于各知识点提分之和。
    # 选择阶段的累计变量只用于提前停止规划，最终展示与持久化统一从节点回算，
    # 避免后续新增前置或验证逻辑时出现顶部与知识点卡片无法对账。
    expected_gain = sum(float(node["expected_gain"]) for node in nodes)
    optimistic_gain = sum(
        float(direct[node["kp_id"]]["optimistic_gain"]) for node in nodes
    )

    tasks = _schedule_tasks(nodes, daily_minutes, horizon_days, start_date)
    first_round_completion_date = (
        max(task["scheduled_date"] for task in tasks).isoformat()
        if tasks
        else None
    )
    first_round_planned_days = (
        (date.fromisoformat(first_round_completion_date) - start_date).days + 1
        if first_round_completion_date
        else 0
    )

    score_gap = max(0.0, target_score - current_score)
    expected_score = min(total_score, current_score + expected_gain)
    optimistic_score = min(total_score, current_score + optimistic_gain)
    feasibility = (
        "maintain"
        if score_gap <= 0
        else "reachable"
        if expected_gain >= score_gap
        else "tight"
        if optimistic_gain >= score_gap
        else "insufficient"
    )
    excluded_reason_counts: Dict[str, int] = defaultdict(int)
    for item in excluded:
        excluded_reason_counts[item["reason"]] += 1
    warnings: List[str] = []
    if cycles:
        warnings.append(f"检测到 {len(cycles)} 组循环依赖，已按同一学习单元处理")
    if feasibility == "insufficient" and selected_minutes < capacity_minutes:
        no_value_count = excluded_reason_counts.get(
            "no_target_value_or_evidence", 0
        )
        warnings.append(
            f"当前有 {len(insufficient_evidence_ids)} 个目标相关或必要前置知识点缺少充分掌握证据，"
            f"另有 {no_value_count} 个知识点缺少目标权重或有效作答数据；"
            "均不计入本轮预计提分，完成首轮复测后再进入下一轮规划"
        )
    if not nodes:
        warnings.append("当前没有满足目标价值与证据门槛的知识点，不会用低价值内容填充时间")
    return {
        "nodes": nodes,
        "tasks": tasks,
        "summary": {
            "current_score": round(current_score, 1),
            "target_score": round(target_score, 1),
            "score_gap": round(score_gap, 1),
            "expected_gain": round(expected_gain, 1),
            "expected_gain_conservative": round(expected_gain, 1),
            "expected_gain_optimistic": round(optimistic_gain, 1),
            "planning_round": 1,
            "planning_scope": "first_pass",
            "first_round_expected_gain_conservative": round(expected_gain, 1),
            "first_round_expected_gain_optimistic": round(optimistic_gain, 1),
            "first_round_completion_date": first_round_completion_date,
            "first_round_planned_days": first_round_planned_days,
            "insufficient_mastery_evidence_count": len(insufficient_evidence_ids),
            "next_round_requires_reassessment": True,
            "expected_score_range": [round(expected_score, 1), round(optimistic_score, 1)],
            "target_feasibility": feasibility,
            "capacity_minutes": capacity_minutes,
            "total_minutes": selected_minutes,
            "unused_minutes": max(0, capacity_minutes - selected_minutes),
            "daily_study_minutes": daily_minutes,
            "horizon_days": horizon_days,
            "knowledge_count": len(nodes),
            "task_count": len(tasks),
            "deferred_count": len(deferred),
            "deferred_nodes": deferred,
            "excluded_count": len(excluded),
            "excluded_reason_counts": dict(excluded_reason_counts),
            "warnings": warnings,
        },
    }
