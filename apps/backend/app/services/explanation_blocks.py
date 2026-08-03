"""AI 知识讲解的受控图文内容块校验。

大模型只能输出语义化图示参数，不能输出任意 HTML / SVG。前端根据这里
保留下来的白名单字段绘制可信 SVG，从而兼顾数学准确性、可编辑性与安全性。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional


ALLOWED_VISUAL_TYPES = {
    "geometry",
    "number_line",
    "coordinate_plane",
    "function_plot",
    "bar_chart",
    "line_chart",
}
ALLOWED_COLORS = {
    "teal",
    "blue",
    "orange",
    "red",
    "green",
    "purple",
    "gray",
}

MAX_BLOCKS = 30
MAX_VISUALS = 8
MAX_MARKDOWN_LENGTH = 20_000


def _text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _number(
    value: Any,
    default: float = 0,
    minimum: float = -1000,
    maximum: float = 1000,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(minimum, min(maximum, number))


def _integer(
    value: Any,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    return int(round(_number(value, default, minimum, maximum)))


def _color(value: Any, default: str = "teal") -> str:
    color = _text(value, 20).lower()
    return color if color in ALLOWED_COLORS else default


def _point(value: Any, *, coordinate: bool = False) -> Optional[Dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    minimum, maximum = (-1000, 1000) if coordinate else (0, 100)
    point = {
        "x": _number(value.get("x"), 0, minimum, maximum),
        "y": _number(value.get("y"), 0, minimum, maximum),
    }
    if value.get("id") is not None:
        point["id"] = _text(value.get("id"), 30)
    if value.get("label") is not None:
        point["label"] = _text(value.get("label"), 60)
    if value.get("color") is not None:
        point["color"] = _color(value.get("color"))
    return point


def _points(
    values: Any,
    *,
    limit: int,
    coordinate: bool = False,
) -> List[Dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [
        point
        for point in (
            _point(item, coordinate=coordinate)
            for item in values[:limit]
        )
        if point is not None
    ]


def _normalize_geometry(spec: Dict[str, Any]) -> Dict[str, Any]:
    points = _points(spec.get("points"), limit=30)
    ids = {point.get("id") for point in points if point.get("id")}

    segments: List[Dict[str, Any]] = []
    for value in (spec.get("segments") or [])[:40]:
        if not isinstance(value, dict):
            continue
        start = _text(value.get("from"), 30)
        end = _text(value.get("to"), 30)
        if start not in ids or end not in ids or start == end:
            continue
        segment: Dict[str, Any] = {
            "from": start,
            "to": end,
            "color": _color(value.get("color"), "gray"),
        }
        if value.get("label") is not None:
            segment["label"] = _text(value.get("label"), 60)
        if value.get("dashed") is not None:
            segment["dashed"] = bool(value.get("dashed"))
        segments.append(segment)

    polygons: List[Dict[str, Any]] = []
    for value in (spec.get("polygons") or [])[:10]:
        if not isinstance(value, dict):
            continue
        vertex_ids = [
            _text(item, 30)
            for item in (value.get("points") or [])[:12]
            if _text(item, 30) in ids
        ]
        if len(vertex_ids) < 3:
            continue
        polygon: Dict[str, Any] = {
            "points": vertex_ids,
            "color": _color(value.get("color"), "teal"),
        }
        if value.get("label") is not None:
            polygon["label"] = _text(value.get("label"), 60)
        polygons.append(polygon)

    circles: List[Dict[str, Any]] = []
    for value in (spec.get("circles") or [])[:10]:
        if not isinstance(value, dict):
            continue
        center = _text(value.get("center"), 30)
        if center not in ids:
            continue
        circle: Dict[str, Any] = {
            "center": center,
            "radius": _number(value.get("radius"), 15, 1, 50),
            "color": _color(value.get("color"), "teal"),
        }
        if value.get("label") is not None:
            circle["label"] = _text(value.get("label"), 60)
        circles.append(circle)

    return {
        "points": points,
        "segments": segments,
        "polygons": polygons,
        "circles": circles,
    }


def _normalize_number_line(spec: Dict[str, Any]) -> Dict[str, Any]:
    minimum = _number(spec.get("min"), -5, -100, 100)
    maximum = _number(spec.get("max"), 5, -100, 100)
    if maximum <= minimum:
        maximum = min(100, minimum + 10)
    step = _number(spec.get("step"), 1, 0.1, max(0.1, maximum - minimum))

    markers: List[Dict[str, Any]] = []
    for value in (spec.get("markers") or [])[:20]:
        if not isinstance(value, dict):
            continue
        marker: Dict[str, Any] = {
            "value": _number(value.get("value"), minimum, minimum, maximum),
            "color": _color(value.get("color")),
        }
        if value.get("label") is not None:
            marker["label"] = _text(value.get("label"), 60)
        markers.append(marker)

    ranges: List[Dict[str, Any]] = []
    for value in (spec.get("ranges") or [])[:8]:
        if not isinstance(value, dict):
            continue
        start = _number(value.get("from"), minimum, minimum, maximum)
        end = _number(value.get("to"), maximum, minimum, maximum)
        if end < start:
            start, end = end, start
        ranges.append({
            "from": start,
            "to": end,
            "color": _color(value.get("color"), "blue"),
            "label": _text(value.get("label"), 60),
        })

    return {
        "min": minimum,
        "max": maximum,
        "step": step,
        "markers": markers,
        "ranges": ranges,
    }


def _normalize_coordinate(spec: Dict[str, Any]) -> Dict[str, Any]:
    x_min = _number(spec.get("x_min"), -5, -100, 100)
    x_max = _number(spec.get("x_max"), 5, -100, 100)
    y_min = _number(spec.get("y_min"), -5, -100, 100)
    y_max = _number(spec.get("y_max"), 5, -100, 100)
    if x_max <= x_min:
        x_max = min(100, x_min + 10)
    if y_max <= y_min:
        y_max = min(100, y_min + 10)

    series: List[Dict[str, Any]] = []
    for value in (spec.get("series") or [])[:6]:
        if not isinstance(value, dict):
            continue
        points = _points(value.get("points"), limit=160, coordinate=True)
        points = [
            point for point in points
            if x_min <= point["x"] <= x_max and y_min <= point["y"] <= y_max
        ]
        if len(points) < 2:
            continue
        series.append({
            "label": _text(value.get("label"), 60),
            "color": _color(value.get("color"), "teal"),
            "points": points,
            "smooth": bool(value.get("smooth")),
        })

    return {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "x_label": _text(spec.get("x_label"), 30) or "x",
        "y_label": _text(spec.get("y_label"), 30) or "y",
        "grid": spec.get("grid") is not False,
        "points": [
            point
            for point in _points(spec.get("points"), limit=40, coordinate=True)
            if x_min <= point["x"] <= x_max and y_min <= point["y"] <= y_max
        ],
        "series": series,
    }


def _normalize_chart(spec: Dict[str, Any]) -> Dict[str, Any]:
    labels = [_text(item, 40) for item in (spec.get("labels") or [])[:12]]
    labels = [label for label in labels if label]
    series: List[Dict[str, Any]] = []
    for value in (spec.get("series") or [])[:4]:
        if not isinstance(value, dict):
            continue
        values = [
            _number(item, 0, -1_000_000, 1_000_000)
            for item in (value.get("values") or [])[:len(labels)]
        ]
        if len(values) != len(labels):
            continue
        series.append({
            "label": _text(value.get("label"), 60),
            "color": _color(value.get("color"), "teal"),
            "values": values,
        })
    return {
        "labels": labels,
        "series": series,
        "y_label": _text(spec.get("y_label"), 30),
    }


def normalize_visual_spec(
    visual_type: str,
    spec: Any,
) -> Optional[Dict[str, Any]]:
    if visual_type not in ALLOWED_VISUAL_TYPES or not isinstance(spec, dict):
        return None
    if visual_type == "geometry":
        normalized = _normalize_geometry(spec)
        return normalized if normalized["points"] else None
    if visual_type == "number_line":
        return _normalize_number_line(spec)
    if visual_type in {"coordinate_plane", "function_plot"}:
        normalized = _normalize_coordinate(spec)
        if visual_type == "function_plot" and not normalized["series"]:
            return None
        return normalized
    if visual_type in {"bar_chart", "line_chart"}:
        normalized = _normalize_chart(spec)
        return normalized if normalized["labels"] and normalized["series"] else None
    return None


def normalize_content_blocks(
    blocks: Any,
    fallback_content: str = "",
) -> List[Dict[str, Any]]:
    """过滤模型返回的内容块，只保留前端能够安全渲染的字段。"""
    normalized: List[Dict[str, Any]] = []
    visual_count = 0
    if isinstance(blocks, list):
        for value in blocks[:MAX_BLOCKS]:
            if not isinstance(value, dict):
                continue
            block_type = _text(value.get("type"), 20).lower()
            if block_type == "markdown":
                content = _text(value.get("content"), MAX_MARKDOWN_LENGTH)
                if content:
                    normalized.append({"type": "markdown", "content": content})
                continue
            if block_type not in {"visual", "diagram"} or visual_count >= MAX_VISUALS:
                continue
            visual_type = _text(
                value.get("visual_type") or value.get("diagram_type"),
                30,
            ).lower()
            spec = normalize_visual_spec(visual_type, value.get("spec"))
            if not spec:
                continue
            normalized.append({
                "type": "visual",
                "visual_type": visual_type,
                "title": _text(value.get("title"), 120),
                "caption": _text(value.get("caption"), 300),
                "alt": _text(value.get("alt"), 300)
                or _text(value.get("caption"), 300)
                or "数学图示",
                "spec": spec,
            })
            visual_count += 1

    fallback = _text(fallback_content, MAX_MARKDOWN_LENGTH)
    if not normalized and fallback:
        return [{"type": "markdown", "content": fallback}]
    if normalized and not any(block["type"] == "markdown" for block in normalized) and fallback:
        normalized.insert(0, {"type": "markdown", "content": fallback})
    return normalized


def markdown_from_blocks(
    blocks: Iterable[Dict[str, Any]],
    fallback_content: str = "",
) -> str:
    """为旧客户端保留纯 Markdown 正文。"""
    markdown = "\n\n".join(
        _text(block.get("content"), MAX_MARKDOWN_LENGTH)
        for block in blocks
        if block.get("type") == "markdown" and block.get("content")
    ).strip()
    return markdown or _text(fallback_content, MAX_MARKDOWN_LENGTH)
