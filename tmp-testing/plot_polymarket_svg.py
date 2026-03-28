#!/usr/bin/env python3

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WIDTH = 1200
HEIGHT = 700
MARGIN_LEFT = 90
MARGIN_RIGHT = 40
MARGIN_TOP = 70
MARGIN_BOTTOM = 90


def read_series(csv_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        outcome_names = [name for name in reader.fieldnames if name not in ("timestamp", "iso_utc")]
        rows = []
        for row in reader:
            parsed = {
                "timestamp": int(row["timestamp"]),
                "iso_utc": row["iso_utc"],
            }
            for outcome in outcome_names:
                value = row[outcome]
                parsed[outcome] = float(value) if value not in ("", None) else None
            rows.append(parsed)
    return rows, outcome_names


def build_continuous_series(rows: list[dict[str, Any]], outcome_names: list[str]) -> dict[str, list[tuple[int, float]]]:
    series: dict[str, list[tuple[int, float]]] = {name: [] for name in outcome_names}
    last_seen: dict[str, float | None] = {name: None for name in outcome_names}

    for row in rows:
        timestamp = row["timestamp"]
        for outcome in outcome_names:
            if row[outcome] is not None:
                last_seen[outcome] = row[outcome]
            if last_seen[outcome] is not None:
                series[outcome].append((timestamp, last_seen[outcome]))
    return series


def scale_x(timestamp: int, min_ts: int, max_ts: int) -> float:
    plot_width = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    if max_ts == min_ts:
        return MARGIN_LEFT + plot_width / 2
    return MARGIN_LEFT + ((timestamp - min_ts) / (max_ts - min_ts)) * plot_width


def scale_y(price: float) -> float:
    plot_height = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
    return MARGIN_TOP + (1 - price) * plot_height


def make_polyline(points: list[tuple[int, float]], min_ts: int, max_ts: int) -> str:
    return " ".join(f"{scale_x(ts, min_ts, max_ts):.2f},{scale_y(price):.2f}" for ts, price in points)


def format_label(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%d")


def outcome_color(index: int) -> str:
    palette = ["#0f766e", "#b91c1c", "#1d4ed8", "#a16207"]
    return palette[index % len(palette)]


def render_svg(rows: list[dict[str, Any]], outcome_names: list[str], title: str) -> str:
    series = build_continuous_series(rows, outcome_names)
    timestamps = [row["timestamp"] for row in rows]
    min_ts = min(timestamps)
    max_ts = max(timestamps)
    plot_width = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    plot_height = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    x_ticks = 5
    y_ticks = [0.0, 0.25, 0.5, 0.75, 1.0]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        '<rect width="100%" height="100%" fill="#fffdf8" />',
        f'<text x="{MARGIN_LEFT}" y="36" font-family="Helvetica, Arial, sans-serif" font-size="28" font-weight="700" fill="#111827">{escape_xml(title)}</text>',
        f'<text x="{MARGIN_LEFT}" y="58" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#4b5563">Polymarket price history by outcome</text>',
        f'<rect x="{MARGIN_LEFT}" y="{MARGIN_TOP}" width="{plot_width}" height="{plot_height}" fill="#ffffff" stroke="#d1d5db" />',
    ]

    for price in y_ticks:
        y = scale_y(price)
        parts.append(
            f'<line x1="{MARGIN_LEFT}" y1="{y:.2f}" x2="{WIDTH - MARGIN_RIGHT}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{MARGIN_LEFT - 12}" y="{y + 5:.2f}" text-anchor="end" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#6b7280">{price:.2f}</text>'
        )

    for i in range(x_ticks + 1):
        ratio = i / x_ticks
        timestamp = int(min_ts + (max_ts - min_ts) * ratio)
        x = MARGIN_LEFT + ratio * plot_width
        parts.append(
            f'<line x1="{x:.2f}" y1="{MARGIN_TOP}" x2="{x:.2f}" y2="{HEIGHT - MARGIN_BOTTOM}" stroke="#f3f4f6" stroke-width="1" />'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{HEIGHT - MARGIN_BOTTOM + 24}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="12" fill="#6b7280">{format_label(timestamp)}</text>'
        )

    for index, outcome in enumerate(outcome_names):
        points = series[outcome]
        if not points:
            continue
        color = outcome_color(index)
        polyline = make_polyline(points, min_ts, max_ts)
        parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="3" points="{polyline}" />'
        )
        last_x = scale_x(points[-1][0], min_ts, max_ts)
        last_y = scale_y(points[-1][1])
        parts.append(f'<circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="4" fill="{color}" />')
        legend_x = MARGIN_LEFT + index * 220
        legend_y = HEIGHT - 28
        parts.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x + 28}" y2="{legend_y}" stroke="{color}" stroke-width="4" />')
        parts.append(
            f'<text x="{legend_x + 38}" y="{legend_y + 5}" font-family="Helvetica, Arial, sans-serif" font-size="14" fill="#111827">{escape_xml(outcome)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a simple SVG graph from a Polymarket CSV export.")
    parser.add_argument("csv_path", help="Path to the CSV created by fetch_polymarket_market_chart.py")
    parser.add_argument("--title", help="Optional chart title override")
    parser.add_argument("--output", help="Output SVG path")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    rows, outcome_names = read_series(csv_path)
    if not rows:
        raise SystemExit("CSV had no rows to plot.")

    title = args.title or csv_path.stem.replace("_prices", "").replace("-", " ")
    output_path = Path(args.output) if args.output else csv_path.with_suffix(".svg")
    svg = render_svg(rows, outcome_names, title)
    output_path.write_text(svg, encoding="utf-8")
    print(f"Wrote SVG: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
