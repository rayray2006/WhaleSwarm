#!/usr/bin/env python3

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse, urlencode
from urllib.request import Request, urlopen


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"
DEFAULT_FIDELITY_MINUTES = 60


def fetch_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "WhaleSwarm/0.1 chart fetcher",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def extract_slug(market_url: str) -> str:
    parsed = urlparse(market_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        raise ValueError(f"Could not extract a market slug from URL: {market_url}")
    return path_parts[-1]


def resolve_market_by_slug(slug: str) -> dict[str, Any]:
    return fetch_json(f"{GAMMA_BASE_URL}/markets/slug/{slug}")


def fetch_price_history(token_id: str, fidelity_minutes: int) -> list[dict[str, Any]]:
    query = urlencode(
        {
            "market": token_id,
            "interval": "max",
            "fidelity": fidelity_minutes,
        }
    )
    payload = fetch_json(f"{CLOB_BASE_URL}/prices-history?{query}")
    return payload.get("history", [])


def parse_json_list(value: str) -> list[Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected a JSON list, got: {value!r}")
    return parsed


def build_chart_rows(
    outcomes: list[str],
    histories_by_outcome: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    by_timestamp: dict[int, dict[str, Any]] = defaultdict(dict)

    for outcome in outcomes:
        for point in histories_by_outcome.get(outcome, []):
            timestamp = int(point["t"])
            by_timestamp[timestamp][outcome] = float(point["p"])

    rows = []
    for timestamp in sorted(by_timestamp):
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        row = {
            "timestamp": timestamp,
            "iso_utc": dt.isoformat(),
        }
        for outcome in outcomes:
            row[outcome] = by_timestamp[timestamp].get(outcome)
        rows.append(row)
    return rows


def write_combined_csv(
    output_path: Path,
    outcomes: list[str],
    chart_rows: list[dict[str, Any]],
) -> None:
    fieldnames = ["timestamp", "iso_utc", *outcomes]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(chart_rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch chartable price data for a Polymarket market URL."
    )
    parser.add_argument(
        "market_url",
        help="Full Polymarket market URL, for example https://polymarket.com/sports/nba/nba-dal-por-2026-03-27",
    )
    parser.add_argument(
        "--fidelity",
        type=int,
        default=DEFAULT_FIDELITY_MINUTES,
        help="Price history resolution in minutes. Default: 60.",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp-testing/polymarket-output",
        help="Directory where JSON and CSV outputs will be written.",
    )
    args = parser.parse_args()

    try:
        slug = extract_slug(args.market_url)
        market = resolve_market_by_slug(slug)
        outcomes = parse_json_list(market["outcomes"])
        token_ids = parse_json_list(market["clobTokenIds"])
    except Exception as exc:
        print(f"Failed to resolve market metadata: {exc}", file=sys.stderr)
        return 1

    if len(outcomes) != len(token_ids):
        print(
            f"Expected the same number of outcomes and token IDs, got {len(outcomes)} and {len(token_ids)}.",
            file=sys.stderr,
        )
        return 1

    histories_by_outcome: dict[str, list[dict[str, Any]]] = {}
    for outcome, token_id in zip(outcomes, token_ids):
        try:
            histories_by_outcome[outcome] = fetch_price_history(token_id, args.fidelity)
        except Exception as exc:
            print(f"Failed to fetch price history for {outcome} ({token_id}): {exc}", file=sys.stderr)
            return 1

    chart_rows = build_chart_rows(outcomes, histories_by_outcome)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{slug}.json"
    csv_path = output_dir / f"{slug}_prices.csv"

    market_snapshot = {
        "market": {
            "id": market.get("id"),
            "slug": market.get("slug"),
            "question": market.get("question"),
            "description": market.get("description"),
            "endDate": market.get("endDate"),
            "volume": market.get("volume"),
            "outcomes": outcomes,
            "token_ids": dict(zip(outcomes, token_ids)),
            "final_outcome_prices": market.get("outcomePrices"),
        },
        "price_history": histories_by_outcome,
    }
    json_path.write_text(json.dumps(market_snapshot, indent=2), encoding="utf-8")
    write_combined_csv(csv_path, outcomes, chart_rows)

    print(f"Resolved slug: {slug}")
    print(f"Question: {market.get('question')}")
    print(f"Outcomes: {', '.join(outcomes)}")
    print(f"Wrote JSON: {json_path}")
    print(f"Wrote CSV:  {csv_path}")
    print(f"Rows: {len(chart_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
