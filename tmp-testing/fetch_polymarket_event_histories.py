#!/usr/bin/env python3

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
CLOB_BASE_URL = "https://clob.polymarket.com"


def fetch_json(url: str) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "WhaleSwarm/0.1 event history fetcher",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_json_list(value: str) -> list[Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON list, got {value!r}")
    return parsed


def fetch_event(slug: str) -> dict[str, Any]:
    return fetch_json(f"{GAMMA_BASE_URL}/events/slug/{slug}")


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


def fetch_all_event_trades(
    event_id: int,
    page_size: int = 1000,
    max_offset: int = 10000,
) -> list[dict[str, Any]]:
    all_trades = []
    offset = 0

    while offset <= max_offset:
        query = urlencode(
            {
                "eventId": event_id,
                "limit": page_size,
                "offset": offset,
            }
        )
        try:
            page = fetch_json(f"{GAMMA_BASE_URL.replace('gamma-api', 'data-api')}/trades?{query}")
        except HTTPError as exc:
            if exc.code == 400:
                break
            raise
        if not page:
            break
        all_trades.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    return all_trades


def delta_stats(history: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = sorted(int(point["t"]) for point in history)
    if len(timestamps) < 2:
        return {
            "points": len(timestamps),
            "first_timestamp": timestamps[0] if timestamps else None,
            "last_timestamp": timestamps[-1] if timestamps else None,
            "min_delta_seconds": None,
            "median_delta_seconds": None,
            "max_delta_seconds": None,
        }

    deltas = [b - a for a, b in zip(timestamps, timestamps[1:])]
    return {
        "points": len(timestamps),
        "first_timestamp": timestamps[0],
        "last_timestamp": timestamps[-1],
        "min_delta_seconds": min(deltas),
        "median_delta_seconds": int(statistics.median(deltas)),
        "max_delta_seconds": max(deltas),
    }


def iso_utc(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch one Polymarket event and summarize the observed price-history frequency."
    )
    parser.add_argument(
        "event_slug",
        help="Gamma event slug, for example fed-decision-in-may-2025",
    )
    parser.add_argument(
        "--fidelity",
        type=int,
        default=60,
        help="Requested CLOB history fidelity in minutes. Default: 60.",
    )
    parser.add_argument(
        "--output-dir",
        default="tmp-testing/polymarket-output",
        help="Directory where the fetched JSON artifact will be written.",
    )
    args = parser.parse_args()

    event = fetch_event(args.event_slug)
    event_id = int(event["id"])
    event_trades = fetch_all_event_trades(event_id)

    markets_payload = []
    for market in event.get("markets", []):
        outcomes = parse_json_list(market["outcomes"])
        token_ids = parse_json_list(market["clobTokenIds"])
        yes_token_id = token_ids[0]
        yes_history = fetch_price_history(yes_token_id, args.fidelity)
        stats = delta_stats(yes_history)

        markets_payload.append(
            {
                "market_id": market.get("id"),
                "market_slug": market.get("slug"),
                "question": market.get("question"),
                "group_item_title": market.get("groupItemTitle"),
                "yes_token_id": yes_token_id,
                "yes_history_stats": {
                    **stats,
                    "first_iso_utc": iso_utc(stats["first_timestamp"]),
                    "last_iso_utc": iso_utc(stats["last_timestamp"]),
                },
                "yes_history_preview": yes_history[:10],
            }
        )

    trade_stats = delta_stats([{"t": trade["timestamp"]} for trade in event_trades])
    output = {
        "event": {
            "id": event.get("id"),
            "slug": event.get("slug"),
            "title": event.get("title"),
            "startDate": event.get("startDate"),
            "endDate": event.get("endDate"),
            "volume": event.get("volume"),
            "market_count": len(event.get("markets", [])),
            "requested_fidelity_minutes": args.fidelity,
        },
        "event_trade_stats": {
            **trade_stats,
            "first_iso_utc": iso_utc(trade_stats["first_timestamp"]),
            "last_iso_utc": iso_utc(trade_stats["last_timestamp"]),
            "trade_count": len(event_trades),
        },
        "event_trades_preview": event_trades[:10],
        "markets": markets_payload,
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.event_slug}_histories_f{args.fidelity}.json"
    output_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Event: {event.get('title')} ({event.get('slug')})")
    print(f"Requested fidelity: {args.fidelity} minute(s)")
    print(f"Wrote JSON: {output_path}")
    print("")
    print(
        "Event trades: "
        f"{len(event_trades)} trades | "
        f"median delta {trade_stats['median_delta_seconds']}s | "
        f"min {trade_stats['min_delta_seconds']}s | "
        f"max {trade_stats['max_delta_seconds']}s"
    )
    print("")
    for market in markets_payload:
        stats = market["yes_history_stats"]
        label = market["group_item_title"] or market["question"]
        print(
            f"- {label}: "
            f"{stats['points']} points | "
            f"median delta {stats['median_delta_seconds']}s | "
            f"min {stats['min_delta_seconds']}s | "
            f"max {stats['max_delta_seconds']}s"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
