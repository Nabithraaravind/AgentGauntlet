"""Inline SVG charts for a self-contained report.

The report does not load Plotly or a CDN. One HTML file stays readable offline.

Example:
    from agentgauntlet.reporting.charts import reliability_svg

    reliability_svg({1: 1.0, 5: 0.4})
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape


def reliability_svg(pass_hat: dict[int, float]) -> str:
    """Draw pass^k against k."""
    points = [(str(k), pass_hat[k]) for k in sorted(pass_hat)]
    return _bars("reliability", points)


def failure_svg(failures: dict[str, int]) -> str:
    """Draw one bar per failure tag."""
    points = [(name, float(count)) for name, count in sorted(failures.items())]
    return _bars("failures", points)


def pareto_svg(points: Sequence[tuple[str, float, float]]) -> str:
    """Draw cost on the horizontal axis and pass@1 on the vertical axis."""
    if not points:
        return _empty("pareto")
    width = 640
    height = 200
    max_cost = max(point[1] for point in points) or 1.0
    dots: list[str] = []
    for name, cost, success in points:
        x = 40 + (width - 80) * (cost / max_cost)
        y = height - 30 - (height - 50) * min(max(success, 0.0), 1.0)
        label = escape(name)
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5"><title>{label}</title></circle>')
        dots.append(f'<text x="{x + 8:.1f}" y="{y:.1f}" font-size="12">{label}</text>')
    return _wrap("pareto", "".join(dots))


def _bars(chart: str, points: Sequence[tuple[str, float]]) -> str:
    if not points:
        return _empty(chart)
    width = 640
    height = 200
    slot = (width - 40) / len(points)
    peak = max(value for _name, value in points) or 1.0
    parts: list[str] = []
    for index, (name, value) in enumerate(points):
        bar_height = (height - 50) * (value / peak)
        x = 30 + index * slot
        y = height - 30 - bar_height
        label = escape(name)
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{slot * 0.6:.1f}" height="{bar_height:.1f}"/>'
        )
        parts.append(f'<text x="{x:.1f}" y="{height - 12}" font-size="12">{label}</text>')
    return _wrap(chart, "".join(parts))


def _empty(chart: str) -> str:
    return _wrap(chart, "")


def _wrap(chart: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" data-chart="{chart}" '
        f'width="640" height="200">{body}</svg>'
    )
