"""Debug script: spin up a minimal simulation (2 agents, 3 rounds) locally.

NOTE: The real app is also temporarily limited to 2 entities + 0 background agents for testing.

Usage (from backend/):
    python scripts/debug_sim.py

Options:
    --rounds N          Number of rounds (default 3)
    --agents N          Number of polymarket agents (default 12)
    --peg               Enable real Polymarket price pegging
    --question TEXT     Market question (default: a harmless test question)
    --model TEXT        LLM model name override

The script creates a temp directory, writes synthetic profiles, runs the
simulation, and prints a summary.  It uses whatever LLM_API_KEY is in .env
(or the environment).  No Neo4j, no Flask, no full pipeline needed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile

# Ensure backend root is on path.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.config import Config
from simulation_engine.environment.make import create_environment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("debug_sim")


# ---------------------------------------------------------------------------
# Synthetic profile generator
# ---------------------------------------------------------------------------

PERSONAS = [
    ("alice_trades", "Alice", "Cautious value investor. Rarely overtrades."),
    ("bob_yolo", "Bob", "High-risk speculator. Goes big or goes home."),
    ("carol_hedge", "Carol", "Hedger. Always takes the opposite side of the crowd."),
    ("dave_news", "Dave", "News junkie. Trades on headlines immediately."),
    ("eve_quant", "Eve", "Quantitative analyst. Relies on statistics over intuition."),
    ("frank_herd", "Frank", "Herd follower. Copies whatever the market does."),
    ("grace_esg", "Grace", "ESG-focused investor. Prefers ethical outcomes."),
    ("hank_bear", "Hank", "Perma-bear. Always bets NO."),
    ("iris_bull", "Iris", "Perma-bull. Always bets YES."),
    ("jack_flip", "Jack", "Contrarian. Fades consensus positions."),
    ("kate_arb", "Kate", "Arbitrageur. Looks for mispricings."),
    ("leo_lazy", "Leo", "Passive investor. Holds and rarely trades."),
    ("mia_macro", "Mia", "Macro trader. Focuses on big-picture trends."),
    ("ned_tech", "Ned", "Tech analyst. Applies technical chart patterns."),
    ("ona_fund", "Ona", "Fund manager. Diversifies across outcomes."),
    ("pete_degen", "Pete", "Degen gambler. Max leverage on everything."),
]


def _make_profiles(n: int) -> list[dict]:
    profiles = []
    for i in range(n):
        uname, name, bio = PERSONAS[i % len(PERSONAS)]
        profiles.append({
            "user_name": f"{uname}_{i}",
            "name": f"{name} {i}",
            "description": bio,
            "bio": bio,
            "activity_level": 0.8,
            "profile": {
                "user_name": f"{uname}_{i}",
                "risk_tolerance": "medium",
            },
        })
    return profiles


# ---------------------------------------------------------------------------
# Simulation config
# ---------------------------------------------------------------------------

def _make_sim_config(
    question: str,
    n_agents: int,
    n_rounds: int,
    model: str | None,
) -> dict:
    return {
        "simulation_requirement": question,
        "platform": {
            "initial_balance": 1000.0,
            "recsys": "random",
        },
        "events": {
            "market_question": question,
            "market_outcome_a": "YES",
            "market_outcome_b": "NO",
            "market_initial_probability": 0.5,
            "initial_posts": [
                f"Big news: the outcome of '{question}' is highly uncertain!",
                "Market is live. What's your edge?",
            ],
        },
        "time": {
            "minutes_per_round": 30,
            "total_simulation_hours": 2,
            "agents_per_hour": n_agents,
            "peak_multiplier": 1.0,
            "off_peak_multiplier": 1.0,
        },
        "agents": {},
        "max_rounds": n_rounds,
    }


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def _print_summary(sim_dir: str) -> None:
    actions_path = os.path.join(sim_dir, "actions.jsonl")
    if not os.path.exists(actions_path):
        print("\n[no actions.jsonl found]")
        return

    trades: list[dict] = []
    whale_trades: list[dict] = []
    round_ends: list[dict] = []
    divergences: list[dict] = []

    with open(actions_path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = rec.get("type")
            if t == "agent_action" and rec.get("action") in ("buy_shares", "sell_shares"):
                trades.append(rec)
            elif t == "whale_trade":
                whale_trades.append(rec)
            elif t == "round_end":
                round_ends.append(rec)
            elif t == "divergence":
                divergences.append(rec)

    print("\n" + "=" * 60)
    print("SIMULATION SUMMARY")
    print("=" * 60)
    print(f"  Rounds completed : {len(round_ends)}")
    print(f"  Agent trades     : {len(trades)}")
    print(f"  Whale peg trades : {len(whale_trades)}")
    print(f"  Divergence logs  : {len(divergences)}")

    if divergences:
        print("\nDivergence (internal vs real price):")
        for d in divergences:
            print(
                f"  Round {d.get('_round', '?'):>2}: "
                f"internal={d.get('internal_price', '?'):.4f}  "
                f"real={d.get('real_price', '?'):.4f}  "
                f"gap={d.get('gap', '?'):.4f}"
            )

    if whale_trades:
        print("\nWhale peg trades:")
        for w in whale_trades:
            print(
                f"  Round {w.get('round', '?'):>2}: "
                f"{w.get('side', '?')} ${w.get('amount_usd', 0):.2f}  "
                f"price {w.get('price_before', '?'):.4f} → {w.get('price_after', '?'):.4f} "
                f"(target {w.get('target_price', '?'):.4f})"
            )

    # Read polymarket DB for leaderboard.
    import sqlite3
    db_path = os.path.join(sim_dir, "polymarket.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT u.user_name, p.balance FROM portfolio p "
                "JOIN user u ON p.user_id = u.user_id "
                "WHERE p.user_id >= 0 "
                "ORDER BY p.balance DESC"
            ).fetchall()
            if rows:
                print("\nFinal balances (cash only):")
                for r in rows[:10]:
                    print(f"  {r['user_name']:<25} ${r['balance']:.2f}")

            # Final market price.
            mkt = conn.execute(
                "SELECT question, reserve_a, reserve_b FROM market ORDER BY market_id LIMIT 1"
            ).fetchone()
            if mkt:
                ra, rb = mkt["reserve_a"], mkt["reserve_b"]
                price_yes = rb / (ra + rb)
                print(f"\nFinal market price: YES={price_yes:.4f}  NO={1-price_yes:.4f}")
                print(f"  Question: {mkt['question'][:80]}")

        finally:
            conn.close()

    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run a minimal debug simulation")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--agents", type=int, default=10)
    parser.add_argument("--peg", action="store_true", help="Enable real Polymarket price pegging")
    parser.add_argument(
        "--question",
        default="Will the S&P 500 close higher than today by end of month?",
    )
    parser.add_argument("--model", default=None, help="Override LLM model name")
    args = parser.parse_args()

    config = Config.from_env()
    config.default_max_rounds = args.rounds
    config.polymarket_anchoring_enabled = args.peg

    if args.model:
        config.llm_model_name = args.model
        config.smart_model_name = args.model

    profiles = _make_profiles(args.agents)

    with tempfile.TemporaryDirectory(prefix="whaleswarm_debug_") as sim_dir:
        logger.info("Debug sim dir: %s", sim_dir)

        # Write profiles (all platforms share the same agents in debug mode).
        for platform in ("polymarket", "twitter", "reddit"):
            path = os.path.join(sim_dir, f"{platform}_profiles.json")
            with open(path, "w") as f:
                json.dump(profiles, f)

        # Write sim config.
        sim_cfg = _make_sim_config(args.question, args.agents, args.rounds, args.model)
        cfg_path = os.path.join(sim_dir, "simulation_config.json")
        with open(cfg_path, "w") as f:
            json.dump(sim_cfg, f, indent=2)

        logger.info(
            "Starting debug sim: %d agents, %d rounds, peg=%s",
            args.agents, args.rounds, args.peg,
        )

        env = create_environment(sim_cfg, sim_dir, config)
        asyncio.run(env.run())

        _print_summary(sim_dir)


if __name__ == "__main__":
    main()
