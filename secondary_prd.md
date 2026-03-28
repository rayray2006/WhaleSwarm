# SECONDARY PRD — Polymarket Realism Extensions

**Version:** 1.0
**Date:** 2026-03-28
**Depends on:** `PRD.md` (the base system)

**Purpose:** Describes two extensions to the base MiroShark system that make its Polymarket simulation more realistic and, over time, more predictive. This document specifies exactly what to change in the base system to implement each extension.

---

## Table of Contents

1. [Extension Overview](#1-extension-overview)
2. [Integration Assessment: Do They Work Together?](#2-integration-assessment-do-they-work-together)
3. [Extension A: Empirical Bet-Size Calibration](#3-extension-a-empirical-bet-size-calibration)
4. [Extension B: Agent Persistence and Market-Selection Evolution](#4-extension-b-agent-persistence-and-market-selection-evolution)
5. [Combined System: How A and B Compose](#5-combined-system-how-a-and-b-compose)
6. [Polymarket Data Pipeline (Shared Prerequisite)](#6-polymarket-data-pipeline-shared-prerequisite)
7. [Changes to Existing Codebase (Extension A)](#7-changes-to-existing-codebase-extension-a)
8. [Changes to Existing Codebase (Extension B)](#8-changes-to-existing-codebase-extension-b)
9. [Changes for Combined A+B Mode](#9-changes-for-combined-ab-mode)
10. [Backtesting Mode and the Future-Leakage Problem](#10-backtesting-mode-and-the-future-leakage-problem)
11. [New File Structure](#11-new-file-structure)

---

## 1. Extension Overview

### Extension A: Empirical Bet-Size Calibration

**Problem:** In the base system, Polymarket agents choose bet sizes via LLM reasoning (the prompt says "small edge = $10-30, medium = $30-80, large = $80-200"). These are arbitrary guidelines that don't reflect how real people bet. The resulting distribution of bet sizes looks nothing like real Polymarket data.

**Solution:** Decouple *conviction* from *bet size*. The LLM outputs what direction to bet (YES/NO) and how confident it is (0-1 scale). A separate calibration layer maps this conviction to a dollar amount sampled from the empirical distribution of real Polymarket bettors with similar wallet sizes, on similar markets.

### Extension B: Agent Persistence and Market-Selection Evolution

**Problem:** In the base system, every simulation starts fresh — new agents, $1,000 each, no history. There is no mechanism for good predictors to accumulate influence over bad ones.

**Solution:** Agents persist across a series of similar markets. After each market resolves:
- Every agent keeps their wallet balance
- Agents who hit $0 are killed and replaced with fresh $1,000 agents
- The total money supply grows by $1,000 per killed agent per round
- Top 1% agents (by wallet) get upgraded to a better LLM model
- Condensed performance signatures carry over (not raw memory)

Additionally, this extension enables a **backtesting mode** where historical resolved markets are simulated using time-appropriate data, and the resulting agent population is deployed on live markets.

---

## 2. Integration Assessment: Do They Work Together?

**Verdict: Yes, they compose cleanly and are better together than apart.**

Here's why: Extension A solves "how much does this agent bet?" Extension B solves "which agents survive?" The integration point is the **wealth bucket**.

Without Extension B, Extension A is static — agents are always in the same wealth bucket because every agent starts at $1,000 and wallets don't persist. The calibration CDF never changes across markets.

With both extensions, agents *migrate between wealth buckets* as they accumulate or lose capital. An agent who starts retail-small and wins 5 markets in a row graduates to retail-large, and their bet sizes shift to match the empirical distribution of real retail-large bettors. This creates a natural feedback loop:

```
good predictions → more money → higher wealth bucket → larger bets (calibrated to real whales)
                                                     → better model (top 1% upgrade)
                                                     → more social influence (bigger $ mentioned in posts)
```

This is realistic: in real Polymarket, successful bettors accumulate capital and their behavior patterns shift to match other high-balance traders.

**The one tension:** Extension B's "top 1% get better models" is a selection pressure toward better predictions. Extension A's bet-size calibration pegs behavior to *average* real bettors in each bucket. If the evolved agents are significantly more skilled than average real bettors, the calibrated bet sizes might be too conservative for them. This is probably fine — conservatism in bet sizing is a feature, not a bug. But it's worth noting.

**Recommendation:** Implement both. Extension A is simpler and can be deployed first. Extension B can be layered on afterward. The combined system is more powerful than either alone.

---

## 3. Extension A: Empirical Bet-Size Calibration

### 3.1 Conceptual Model

```
                          BASE SYSTEM (current)
┌─────────┐     ┌─────────────────┐     ┌──────────┐
│  Agent   │────▶│  LLM decides    │────▶│ buy_shares│
│  sees    │     │  direction AND  │     │ ($47.50) │
│  market  │     │  bet size       │     │          │
└─────────┘     └─────────────────┘     └──────────┘

                       WITH EXTENSION A
┌─────────┐     ┌─────────────────┐     ┌──────────────┐     ┌──────────┐
│  Agent   │────▶│  LLM decides    │────▶│ Calibration  │────▶│ buy_shares│
│  sees    │     │  direction AND  │     │ Layer maps   │     │ ($23.00) │
│  market  │     │  conviction     │     │ conviction   │     │          │
│          │     │  (0.73)         │     │ to real $    │     │          │
└─────────┘     └─────────────────┘     └──────────────┘     └──────────┘
                                               │
                                        ┌──────┴──────┐
                                        │ Empirical   │
                                        │ CDF from    │
                                        │ real bettors│
                                        │ in similar  │
                                        │ markets     │
                                        └─────────────┘
```

### 3.2 What the LLM Outputs (New)

Currently `buy_shares(market_id, outcome, amount_usd)` has the LLM choose `amount_usd` directly.

New tool signature:

```python
async def buy_shares(self, market_id: int, outcome: str, conviction: float):
    """Buy shares in a prediction market outcome.

    Args:
        market_id: The market to trade in.
        outcome: The outcome to buy (e.g. 'YES' or 'NO').
        conviction: How confident you are, from 0.0 (barely worth trading)
                    to 1.0 (absolutely certain). This determines your bet
                    size — higher conviction means larger position.
    """
```

Conviction is a relative ranking signal, not an absolute probability. The prompt explains this:

```
When you call buy_shares, set your conviction from 0.0 to 1.0:
- 0.1-0.3: Slight edge, worth a small position
- 0.3-0.6: Moderate conviction, clear mispricing
- 0.6-0.8: Strong conviction, significant edge
- 0.8-1.0: Near-certain, very large mispricing

Your conviction determines how much you bet. Higher conviction = bigger bet.
```

Similarly, `sell_shares` can optionally take a conviction parameter, but for sells it's simpler to keep the existing interface (sell N shares) since the decision is "how many of my shares to sell" which the LLM can reason about directly. Alternatively, keep `sell_shares` as-is (the LLM decides how many shares), since sell behavior is less important for distribution matching than buy behavior.

### 3.3 Wealth Buckets

Agents are assigned to a wealth bucket based on their current Polymarket balance (cash + position value):

```python
WEALTH_BUCKETS = [
    ("nano",         0,       50),    # near-zero, barely participating
    ("retail_small", 50,      250),   # casual bettors
    ("retail_mid",   250,     1_000), # regular retail
    ("retail_large", 1_000,   5_000), # serious retail
    ("semi_pro",     5_000,   25_000),# high-volume retail / small pros
    ("whale",        25_000,  None),  # whales
]
```

These bucket boundaries should be calibrated from actual Polymarket wallet distribution data. The specific numbers above are illustrative.

### 3.4 Market Similarity for CDF Selection

Each market gets tagged with a **market cohort** key: `(category, duration_tier, liquidity_tier)`.

```python
CATEGORY_MAP = {
    # from Polymarket API tags / manual mapping
    "politics": "politics",
    "foreign_policy": "politics",
    "elections": "politics",
    "sports": "sports",
    "basketball": "sports",
    "football": "sports",
    "crypto": "crypto",
    "defi": "crypto",
    "science": "science",
    "entertainment": "culture",
    ...
}

DURATION_TIERS = {
    "flash":  (0, 3),       # resolves in ≤3 days
    "short":  (3, 14),      # 3-14 days
    "medium": (14, 60),     # 2 weeks to 2 months
    "long":   (60, None),   # 2+ months
}

LIQUIDITY_TIERS = {
    "thin":   (0, 50_000),         # under $50k total volume
    "normal": (50_000, 500_000),   # $50k-$500k
    "deep":   (500_000, None),     # $500k+
}
```

A market cohort like `("politics", "medium", "normal")` selects the set of historical markets whose bettor data we use. If the exact cohort has too few data points (<50 bettors), fall back to broader cohort: first drop liquidity tier, then drop duration tier.

### 3.5 Empirical CDF Construction (Offline, One-Time)

For each `(market_cohort, wealth_bucket)` pair, build the empirical CDF of bet sizes:

```python
@dataclass
class BetSizeCDF:
    market_cohort: str        # e.g. "politics:medium:normal"
    wealth_bucket: str        # e.g. "retail_mid"
    position: str             # "YES" or "NO" (separate CDFs)
    sorted_bet_sizes: List[float]  # ascending order
    n_bettors: int            # sample size for confidence

    def sample_at_quantile(self, quantile: float) -> float:
        """Return the bet size at the given quantile (0-1)."""
        idx = int(quantile * (len(self.sorted_bet_sizes) - 1))
        return self.sorted_bet_sizes[idx]
```

This is built from historical Polymarket data (see §6).

### 3.6 The Calibration Layer (Runtime)

Inserted between the LLM's tool call and the platform's `buy_shares` handler:

```python
class BetSizeCalibrator:
    def __init__(self, cdf_store: Dict[str, BetSizeCDF]):
        self.cdf_store = cdf_store

    def calibrate(
        self,
        agent_id: int,
        conviction: float,           # 0-1 from LLM
        outcome: str,                # "YES" or "NO"
        agent_balance: float,        # current portfolio value
        market_cohort: str,          # e.g. "politics:medium:normal"
    ) -> float:
        """Map conviction to a real-dollar bet size."""

        # 1. Determine wealth bucket
        bucket = self._get_wealth_bucket(agent_balance)

        # 2. Look up CDF
        cdf_key = f"{market_cohort}:{bucket}:{outcome}"
        cdf = self.cdf_store.get(cdf_key)

        if cdf is None or cdf.n_bettors < 10:
            # Fallback: use broader cohort or simple heuristic
            return self._heuristic_fallback(conviction, agent_balance)

        # 3. Use conviction as quantile into the CDF
        #    conviction 0.0 → smallest bet in bucket
        #    conviction 1.0 → largest bet in bucket
        amount = cdf.sample_at_quantile(conviction)

        # 4. Sanity cap: never bet more than current balance
        amount = min(amount, agent_balance * 0.95)

        return max(1.0, amount)  # minimum $1 bet

    def _heuristic_fallback(self, conviction, balance):
        """When empirical data is unavailable, use a simple scaling."""
        # Similar to current system but conviction-weighted
        base = balance * 0.02  # 2% of portfolio as base
        return base * (0.5 + conviction * 4.5)  # 1% to 10% of portfolio

    def _get_wealth_bucket(self, balance):
        for name, low, high in WEALTH_BUCKETS:
            if high is None or balance < high:
                if balance >= low:
                    return name
        return "retail_mid"
```

### 3.7 Where the Calibration Layer Sits in the Call Chain

The calibration layer intercepts *after* the LLM chooses direction + conviction and *before* the platform executes the trade:

**Current flow:**
```
LLM tool call: buy_shares(market_id=1, outcome="YES", amount_usd=50)
  → PolymarketAction.buy_shares(market_id, outcome, amount_usd)
    → channel → PolymarketPlatform.buy_shares(agent_id, (market_id, outcome, amount_usd))
```

**New flow:**
```
LLM tool call: buy_shares(market_id=1, outcome="YES", conviction=0.73)
  → PolymarketAction.buy_shares(market_id, outcome, conviction)
    → BetSizeCalibrator.calibrate(agent_id, conviction, outcome, balance, cohort) → amount_usd
    → channel → PolymarketPlatform.buy_shares(agent_id, (market_id, outcome, amount_usd))
```

The calibration happens in `PolymarketAction.buy_shares()`, which has access to the calibrator instance. The platform side (`PolymarketPlatform.buy_shares`) stays unchanged — it still receives `amount_usd`.

### 3.8 Ordinal Matching (Batch Mode)

There's also a batch variant for when you want the *collective* distribution to match perfectly:

After all agents have submitted their convictions for a round, instead of calibrating individually, you can:

1. Collect all `(agent_id, conviction, outcome)` tuples for agents who chose to trade
2. Split by outcome (YES traders, NO traders)
3. Within each group, sort agents by conviction ascending
4. Sort the empirical bet sizes ascending
5. Map rank-for-rank: agent[i] gets bet_size[i]

This guarantees the distribution of bet sizes across all agents exactly matches the empirical distribution. The downside is it requires a synchronization point (all agents must decide before any execute), which changes the round execution flow from concurrent to two-phase.

**Recommendation:** Start with the per-agent quantile mapping (§3.6). It's simpler, works with concurrent execution, and produces approximately correct distributions. Move to batch ordinal matching later if the per-agent approximation isn't close enough.

---

## 4. Extension B: Agent Persistence and Market-Selection Evolution

### 4.1 The Multi-Market Simulation Loop

The base system runs a single simulation: one set of documents → one set of agents → one market → done. Extension B wraps this in an outer loop:

```
                        ┌─────────────────────────────────────────┐
                        │         MARKET SERIES CONTROLLER         │
                        │                                          │
                        │  For each market in series:              │
                        │    1. Seed new market question           │
                        │    2. Inject new documents (time-gated)  │
                        │    3. Run simulation (existing engine)   │
                        │    4. Resolve market (ground truth)      │
                        │    5. Settle portfolios                  │
                        │    6. Kill bankrupt agents               │
                        │    7. Spawn replacements ($1000 each)    │
                        │    8. Condense surviving agent memory    │
                        │    9. Upgrade/downgrade model tiers      │
                        │   10. Loop                               │
                        └─────────────────────────────────────────┘
```

### 4.2 Agent State That Persists

Between markets, each surviving agent carries:

```python
@dataclass
class PersistentAgentState:
    agent_id: int

    # Identity (immutable)
    name: str
    persona: str               # original persona from graph
    source_entity_uuid: str    # link to knowledge graph node

    # Wallet (mutable, the core selection signal)
    wallet_balance: float      # cash after market resolution
    total_pnl: float           # cumulative P&L across all markets
    markets_participated: int  # count

    # Performance signature (mutable, condensed)
    win_rate: float            # fraction of markets where PnL > 0
    avg_edge_captured: float   # average (payout - cost) / cost
    best_categories: List[str] # categories where they've performed best
    risk_profile: str          # derived from behavior: "contrarian_early", "momentum_follower", etc.

    # Model tier (mutable)
    model_tier: str            # "base" | "mid" | "top"

    # What does NOT persist
    # - Raw conversation memory (too large)
    # - Belief state positions (re-initialized from new documents)
    # - Platform-specific state (posts, followers — all reset)
    # - Trust graph (reset per market)
```

### 4.3 What Gets Re-Initialized Per Market

Each new market in the series gets:

1. **New documents** — fresh document set describing the new market's topic (e.g., new geopolitical briefing for a new foreign policy question)
2. **New knowledge graph** — rebuilt from new documents (the graph from the previous market is discarded)
3. **New agent profiles** — BUT only for replacement agents. Surviving agents keep their personas. The graph is only used to generate replacements.
4. **New belief states** — ALL agents, including survivors, get fresh beliefs from the new documents. No carryover of old positions.
5. **New social platform state** — Twitter/Reddit databases are wiped. Fresh feeds.
6. **New market** — new Polymarket question, fresh AMM, but each agent's starting balance is their carried-over wallet (not $1,000).

### 4.4 Market Resolution and Settlement

When a market resolves (either because backtesting data gives us ground truth, or because the real Polymarket market has resolved):

```python
async def resolve_and_settle(platform: PolymarketPlatform, winning_outcome: str):
    """Resolve market and settle all positions."""

    # 1. Mark market as resolved
    platform._execute_db_command(
        "UPDATE market SET resolved = 1, winning_outcome = ? WHERE market_id = ?",
        (winning_outcome, market_id), commit=True)

    # 2. For each agent with a position:
    for agent_id, outcome, shares in all_positions:
        if outcome == winning_outcome:
            # Winning shares pay out $1.00 each
            payout = shares * 1.0
        else:
            # Losing shares are worthless
            payout = 0.0

        # Credit payout to wallet
        platform._execute_db_command(
            "UPDATE portfolio SET balance = balance + ? WHERE user_id = ?",
            (payout, agent_id), commit=True)

    # 3. Clear all positions (market is over)
    platform._execute_db_command(
        "DELETE FROM position WHERE market_id = ?", (market_id,), commit=True)
```

### 4.5 Agent Kill/Replace Cycle

After settlement:

```python
def evolve_agent_pool(persistent_states: List[PersistentAgentState],
                      replacement_profiles: List[OasisAgentProfile]) -> List[PersistentAgentState]:
    """Kill bankrupt agents, spawn replacements, update model tiers."""

    surviving = []
    dead_count = 0

    for agent in persistent_states:
        if agent.wallet_balance <= 0:
            dead_count += 1
            continue  # killed
        surviving.append(agent)

    # Spawn replacements from fresh graph-derived profiles
    for i in range(dead_count):
        profile = replacement_profiles[i % len(replacement_profiles)]
        new_agent = PersistentAgentState(
            agent_id=max(a.agent_id for a in surviving) + 1 + i,
            name=profile.name,
            persona=profile.persona,
            source_entity_uuid=profile.source_entity_uuid,
            wallet_balance=1000.0,   # fresh money
            total_pnl=0.0,
            markets_participated=0,
            win_rate=0.0,
            avg_edge_captured=0.0,
            best_categories=[],
            risk_profile="unknown",
            model_tier="base",
        )
        surviving.append(new_agent)

    # Update model tiers based on wealth ranking
    surviving.sort(key=lambda a: a.wallet_balance, reverse=True)
    total = len(surviving)
    for i, agent in enumerate(surviving):
        percentile = i / total
        if percentile < 0.001:       # top 0.1%
            agent.model_tier = "top"
        elif percentile < 0.01:      # top 1%
            agent.model_tier = "mid"
        else:
            agent.model_tier = "base"

    return surviving
```

### 4.6 Model Tier Mapping

```python
MODEL_TIER_MAP = {
    "base": "gemini-2.5-flash-lite",      # 99% of agents — cheapest
    "mid":  "gemini-2.5-flash",            # 0.9% — moderate
    "top":  "gemini-2.5-pro",              # 0.1% — most capable
}

# Alternative (if using OpenRouter):
MODEL_TIER_MAP = {
    "base": "google/gemini-2.5-flash-lite",
    "mid":  "google/gemini-2.5-flash",
    "top":  "google/gemini-2.5-pro",
}
```

Each tier must be configured as a separate model backend in the CAMEL-AI `ModelManager`. When creating a `SocialAgent`, select the model based on `persistent_state.model_tier`.

### 4.7 Memory Condensation

When an agent transitions between markets, their full conversation memory is discarded. In its place, a **performance signature** is generated and injected into their system prompt for the next market:

```python
def condense_for_next_market(state: PersistentAgentState) -> str:
    """Generate a condensed prompt snippet describing this agent's track record."""
    return (
        f"# YOUR TRACK RECORD\n"
        f"You have participated in {state.markets_participated} prediction markets.\n"
        f"Win rate: {state.win_rate:.0%} | "
        f"Cumulative P&L: {'+'if state.total_pnl>=0 else ''}"
        f"${state.total_pnl:.0f} | "
        f"Current bankroll: ${state.wallet_balance:.0f}\n"
        f"Your strongest categories: {', '.join(state.best_categories) or 'still learning'}\n"
        f"Trading style: {state.risk_profile}\n"
        f"\nUse this history to calibrate your confidence. If you've been "
        f"wrong a lot recently, be more cautious. If you've been right, "
        f"trust your instincts — but don't get overconfident."
    )
```

This is appended to the system prompt alongside the persona, but **before** any new market-specific context. The agent's *identity* stays the same; only their *experience summary* carries over.

### 4.8 Money Supply Dynamics

Per round (per market series step):
- **Inflow**: $1,000 per killed agent (replacement money)
- **Outflow**: None (market is zero-sum between agents, the AMM is the counterparty)

Over time: total money grows, more money concentrates in winning agents, bet sizes increase. This is intentional — it mirrors real market dynamics where capital accumulates with skilled participants.

Track the total pool size to make sure it doesn't inflate to absurd levels. If after 50 markets the top agent has $200k and the average is $15k, that's fine — it means the evolution worked. If the *average* agent has $50k, that means nobody is getting killed (too few losers) and you should increase the initial aggressiveness or lower the kill threshold from $0 to, say, $50.

---

## 5. Combined System: How A and B Compose

When both extensions are active, the per-round flow within a single market looks like this:

```
1. Agent observes environment (portfolio + markets + social context)
2. LLM outputs: { position: "YES", conviction: 0.73 }           ← NEW (Extension A)
3. Calibrator looks up agent's wealth bucket                      ← Extension A uses Extension B's wallet
4. Calibrator samples from empirical CDF at conviction quantile   ← Extension A
5. Platform executes trade with calibrated amount_usd             ← Same as base system
6. Belief state updates                                           ← Same as base system
```

And between markets:

```
1. Market resolves, positions settle                              ← Extension B
2. Agents' wallets update (some grow, some shrink to 0)           ← Extension B
3. Bankrupt agents killed, replacements spawned with $1,000       ← Extension B
4. Model tiers reassigned based on new wallet ranking             ← Extension B
5. Agents' wealth buckets recalculated for next market            ← Extensions A+B INTERACTION POINT
6. New documents ingested, new graph built                        ← Base system
7. New beliefs initialized for all agents                         ← Base system
8. Performance signatures condensed and injected                  ← Extension B
9. CDF lookup tables may shift (agents in new buckets)            ← Extension A
10. Simulation begins on next market                              ← Base system
```

The interaction at step 5 is where the two extensions reinforce each other: an agent who won money in market N now sits in a higher wealth bucket for market N+1, so their calibrated bet sizes shift to match the behavior of real bettors with that much money.

---

## 6. Polymarket Data Pipeline (Shared Prerequisite)

Both extensions require historical Polymarket data. This is a one-time data engineering effort that produces static lookup tables.

### 6.1 Data Sources

- **Polymarket API** (`https://clob.polymarket.com/`) — market metadata, resolution data, current prices
- **Polygon blockchain** (via `polygonscan.com` or archive node) — on-chain trade history, wallet balances
- **Polymarket subgraph** (The Graph) — indexed trade events, position data

### 6.2 Data to Collect

For each resolved market:
```json
{
  "market_id": "0x...",
  "question": "Will...",
  "category": "politics",
  "subcategory": "foreign_policy",
  "created_at": "2025-01-15T...",
  "resolved_at": "2025-04-01T...",
  "winning_outcome": "YES",
  "total_volume": 1_250_000,
  "trades": [
    {
      "wallet": "0xabc...",
      "side": "buy",
      "outcome": "YES",
      "amount_usd": 150.00,
      "shares": 214.3,
      "price": 0.70,
      "timestamp": "2025-02-10T..."
    }
  ]
}
```

For each wallet that has traded:
```json
{
  "wallet": "0xabc...",
  "total_usdc_deposited": 5_000,
  "current_positions_value": 3_200,
  "markets_participated": 23,
  "categories": ["politics", "sports"],
  "win_rate": 0.61
}
```

### 6.3 Processing Pipeline

```python
def build_cdf_tables(markets: List[MarketData], wallets: List[WalletData]) -> Dict[str, BetSizeCDF]:
    """Build empirical CDFs for all (cohort, bucket, outcome) triples."""

    cdfs = {}

    for market in markets:
        cohort = classify_market_cohort(market)  # → "politics:medium:normal"

        for trade in market.trades:
            wallet = wallets[trade.wallet]
            bucket = classify_wealth_bucket(wallet.total_usdc_deposited)
            key = f"{cohort}:{bucket}:{trade.outcome}"

            if key not in cdfs:
                cdfs[key] = []
            cdfs[key].append(trade.amount_usd)

    # Sort and package
    result = {}
    for key, amounts in cdfs.items():
        amounts.sort()
        parts = key.split(":")
        result[key] = BetSizeCDF(
            market_cohort=":".join(parts[:3]),
            wealth_bucket=parts[3],
            position=parts[4],
            sorted_bet_sizes=amounts,
            n_bettors=len(amounts),
        )

    return result
```

### 6.4 Storage

CDFs are serialized to JSON and loaded at simulation startup:

```
backend/data/polymarket_cdfs/
├── cdfs.json                   # all CDFs, ~5-20MB
├── market_cohorts.json         # category/duration/liquidity classification rules
├── wallet_distributions.json   # wealth bucket boundary calibration
└── metadata.json               # data freshness, source markets, collection date
```

This data is **static** — it doesn't change during simulation. It's rebuilt periodically (monthly?) as more Polymarket data accumulates.

### 6.5 For Extension B: Historical Market Data for Backtesting

In addition to the CDFs, backtesting mode needs full historical price timeseries:

```
backend/data/polymarket_history/
├── markets/
│   ├── {market_id}.json        # full market data (question, outcomes, resolution)
│   └── ...
├── prices/
│   ├── {market_id}_prices.csv  # timestamp, yes_price, no_price (e.g., hourly)
│   └── ...
├── orderbooks/
│   ├── {market_id}_ob_{timestamp}.json  # order book snapshots (optional)
│   └── ...
└── documents/
    ├── {market_id}/
    │   ├── doc1.md             # time-gated documents for this market
    │   └── doc2.pdf            # (must be dated BEFORE market resolution)
    └── ...
```

---

## 7. Changes to Existing Codebase (Extension A)

### 7.1 `PolymarketAction.buy_shares` — Change Interface

**File:** `backend/wonderwall/simulations/polymarket/actions.py`

**Change:** Replace `amount_usd` parameter with `conviction` parameter.

```python
# BEFORE
async def buy_shares(self, market_id: int, outcome: str, amount_usd: float):
    return await self.perform_action(
        (market_id, outcome, amount_usd), "buy_shares")

# AFTER
async def buy_shares(self, market_id: int, outcome: str, conviction: float):
    """Buy shares in a prediction market outcome.

    Args:
        market_id: The ID of the market to trade in.
        outcome: The outcome to buy (e.g. 'YES' or 'NO').
        conviction: Your confidence level from 0.0 to 1.0.
            0.1-0.3 = slight edge, 0.3-0.6 = moderate,
            0.6-0.8 = strong, 0.8-1.0 = near-certain.
    """
    # Calibrate conviction to dollar amount
    conviction = max(0.0, min(1.0, float(conviction)))
    amount_usd = self._calibrator.calibrate(
        agent_id=self.agent_id,
        conviction=conviction,
        outcome=outcome,
        agent_balance=self._get_agent_balance(),
        market_cohort=self._market_cohort,
    )
    return await self.perform_action(
        (market_id, outcome, amount_usd), "buy_shares")
```

The calibrator is injected at `PolymarketAction` construction time. `_get_agent_balance()` calls `view_portfolio()` to get current balance (or caches it per round). `_market_cohort` is set when the market series begins.

### 7.2 `PolymarketPromptBuilder` — Update System Prompt

**File:** `backend/wonderwall/simulations/polymarket/prompts.py`

**Change:** Replace the bet-sizing guidance with conviction-based guidance.

Replace this section:
```
2. **buy_shares** when you believe a market is mispriced...
   - Small edge (5-10%): small bet ($10-30)
   - Medium edge (10-20%): moderate bet ($30-80)
   - Large edge (>20%): bigger bet ($80-200)
   - Never bet more than 20% of your cash on a single position.
```

With:
```
2. **buy_shares** when you believe a market is mispriced — the true
probability is HIGHER than the current price for YES (or LOWER for NO).
Set your conviction based on how confident you are:
   - 0.1-0.3: Slight edge, you think there's a small mispricing
   - 0.3-0.6: Moderate conviction, clear mispricing you'd bet on
   - 0.6-0.8: Strong conviction, significant edge based on evidence
   - 0.8-1.0: Near-certain, major mispricing

Your conviction determines your bet size automatically. Don't try to
game the conviction number — just express how confident you genuinely are.
```

### 7.3 `PolymarketPlatform.buy_shares` — No Change

The platform handler stays the same — it still receives `(market_id, outcome, amount_usd)`. The translation from conviction to dollars happens in the action layer before the message is sent over the channel.

### 7.4 New File: `BetSizeCalibrator`

**File:** `backend/wonderwall/simulations/polymarket/calibrator.py`

New module containing `BetSizeCalibrator` class (as specified in §3.6), `BetSizeCDF` dataclass, `WEALTH_BUCKETS` definition, CDF loading from JSON.

### 7.5 Sell-Side (Optional)

For `sell_shares`, keep the existing interface (num_shares as parameter). The LLM decides how many shares to sell directly. This is simpler because:
- Sell sizing is about managing an existing position, not opening one
- The "how much to sell" question is naturally bounded by how many shares you hold
- Empirical sell distribution data is harder to interpret (partial sells vs full exits)

If you later want calibrated sells too, the same conviction → quantile approach works: LLM outputs conviction-to-sell (0 = hold, 1 = dump everything), mapped to a fraction of position.

---

## 8. Changes to Existing Codebase (Extension B)

### 8.1 New: `MarketSeriesController`

**File:** `backend/app/services/market_series_controller.py`

This is the outer loop that manages agent persistence across markets. It does not replace `SimulationRunner` — it wraps it, calling `SimulationRunner.start_simulation()` for each market in the series.

```python
class MarketSeriesController:
    """Runs a sequence of markets with persistent agents."""

    def __init__(self, series_config: MarketSeriesConfig):
        self.config = series_config
        self.persistent_agents: List[PersistentAgentState] = []
        self.market_index: int = 0

    async def run_series(self):
        """Main loop: for each market in the series."""

        # Initialize agents from first market's graph
        self.persistent_agents = self._initial_agent_pool()

        for market_spec in self.config.markets:
            self.market_index += 1

            # 1. Build new graph from market-specific documents
            graph_id = await self._build_graph(market_spec.documents)

            # 2. Generate replacement profiles (for killed agents) from new graph
            replacement_profiles = await self._generate_replacement_profiles(graph_id)

            # 3. Create simulation with persistent wallets
            sim_id = await self._create_simulation(
                graph_id=graph_id,
                market_question=market_spec.question,
                initial_probability=market_spec.initial_probability,
                agent_states=self.persistent_agents,
            )

            # 4. Run simulation
            await SimulationRunner.start_simulation(sim_id, ...)
            await self._wait_for_completion(sim_id)

            # 5. Resolve market
            await self._resolve_market(sim_id, market_spec.winning_outcome)

            # 6. Read final wallet balances
            self._update_persistent_wallets(sim_id)

            # 7. Kill/replace/tier
            self.persistent_agents = evolve_agent_pool(
                self.persistent_agents, replacement_profiles)

            # 8. Condense memory for survivors
            for agent in self.persistent_agents:
                agent.markets_participated += 1
                # Update win_rate, avg_edge_captured, risk_profile, best_categories
                ...
```

### 8.2 `PolymarketPlatform` — Variable Initial Balances

**File:** `backend/wonderwall/simulations/polymarket/platform.py`

**Change:** `sign_up` must support per-agent initial balances instead of a single `self.initial_balance`.

```python
# BEFORE
async def sign_up(self, agent_id, user_message):
    result = await super().sign_up(agent_id, user_message)
    if result["success"]:
        self._execute_db_command(
            "INSERT INTO portfolio (user_id, balance) VALUES (?, ?)",
            (agent_id, self.initial_balance), commit=True)
    return result

# AFTER
async def sign_up(self, agent_id, user_message):
    result = await super().sign_up(agent_id, user_message)
    if result["success"]:
        # user_message now contains initial_balance as 4th element (if present)
        initial_balance = self.initial_balance
        if len(user_message) >= 4:
            initial_balance = float(user_message[3])
        self._execute_db_command(
            "INSERT INTO portfolio (user_id, balance) VALUES (?, ?)",
            (agent_id, initial_balance), commit=True)
    return result
```

### 8.3 `SocialAgent` — Model Tier Selection

**File:** `backend/wonderwall/social_agent/agent.py`

**Change:** At construction time, select model backend based on agent's `model_tier`.

```python
# In agent_generator or wherever agents are constructed for simulation:
def _select_model_for_tier(tier: str) -> BaseModelBackend:
    model_name = MODEL_TIER_MAP.get(tier, MODEL_TIER_MAP["base"])
    return ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI_COMPATIBLE_MODEL,
        model_type=model_name,
        model_config_dict={"base_url": Config.LLM_BASE_URL, ...},
    )
```

### 8.4 `OasisProfileGenerator` — Generate Replacement Profiles Only

**File:** `backend/app/services/oasis_profile_generator.py`

**Change:** Add a mode that only generates profiles for N replacement agents (not the full population). The generator picks random entities from the new graph that haven't been used by surviving agents.

```python
async def generate_replacement_profiles(
    self, graph_id: str, count: int,
    exclude_entity_uuids: Set[str],
) -> List[OasisAgentProfile]:
    """Generate profiles for replacement agents from a new graph,
    excluding entities already used by surviving agents."""
    ...
```

### 8.5 `PolymarketPromptBuilder` — Include Track Record

**File:** `backend/wonderwall/simulations/polymarket/prompts.py`

**Change:** Accept optional `track_record` string in `build_system_prompt()` and include it.

```python
def build_system_prompt(self, user_info) -> str:
    # ... existing code ...

    track_record = ""
    if user_info.profile and "other_info" in user_info.profile:
        other = user_info.profile["other_info"]
        if "track_record" in other and other["track_record"]:
            track_record = other["track_record"]

    return f"""\
# WHO YOU ARE
...
{track_record}
...
"""
```

### 8.6 New: Market Resolution Handler

**File:** `backend/wonderwall/simulations/polymarket/platform.py`

**Addition:** `resolve_market` method.

```python
async def resolve_market(self, agent_id, resolve_message):
    """Resolve a market and settle all positions."""
    market_id, winning_outcome = resolve_message
    ...  # as described in §4.4
```

### 8.7 New: `PersistentAgentState` and `MarketSeriesConfig`

**File:** `backend/app/models/persistent_agent.py`

Contains the `PersistentAgentState` dataclass (§4.2) and `MarketSeriesConfig`:

```python
@dataclass
class MarketSeriesConfig:
    series_id: str
    series_name: str
    market_cohort: str                     # e.g. "politics:long:normal"
    markets: List[MarketSpec]              # ordered list of markets
    initial_agent_count: int               # how many agents to start with
    kill_threshold: float = 0.0            # wallet below this → killed
    whale_threshold_percentile: float = 0.01  # top 1% get upgraded
    elite_threshold_percentile: float = 0.001 # top 0.1% get best model

@dataclass
class MarketSpec:
    question: str
    outcome_a: str = "YES"
    outcome_b: str = "NO"
    initial_probability: float = 0.5
    winning_outcome: Optional[str] = None  # for backtesting (known outcome)
    documents: List[str] = field(default_factory=list)  # file paths
    max_rounds: int = 40
```

### 8.8 Storage for Persistent State

```
backend/uploads/series/{series_id}/
├── series_config.json
├── persistent_agents.json          # current agent states (updated after each market)
├── history/
│   ├── market_001_results.json     # per-market results
│   ├── market_002_results.json
│   └── ...
└── markets/
    ├── market_001/                 # standard simulation directory
    ├── market_002/
    └── ...
```

---

## 9. Changes for Combined A+B Mode

When both extensions are active, the following additional integrations are needed:

### 9.1 Calibrator Receives Dynamic Wallets

The `BetSizeCalibrator` is initialized once per market series but queries agent balance per-round. As agents accumulate wealth across markets (Extension B), their wealth bucket shifts, and their calibrated bet sizes change accordingly. No code change needed — the calibrator already reads current balance each call.

### 9.2 New Agents Get Retail-Small CDFs

Replacement agents spawned with $1,000 automatically land in the `retail_mid` bucket. As they win or lose, they migrate. Fresh agents always start with the retail distribution, not the whale distribution.

### 9.3 Model Tier Affects Conviction Quality

Top-tier agents (better models) should produce better-calibrated convictions. This is implicit — a smarter model should have more accurate beliefs, leading to convictions that better match reality. Combined with higher wealth bucket (more money → larger calibrated bets), this means smart agents with track records make bigger, better bets. This is the desired behavior.

### 9.4 Configuration

When running combined mode, the `.env` or `MarketSeriesConfig` includes:

```python
# Extension A
BET_CALIBRATION_ENABLED = True
BET_CALIBRATION_CDF_PATH = "backend/data/polymarket_cdfs/cdfs.json"
BET_CALIBRATION_FALLBACK = "heuristic"  # "heuristic" or "legacy" (old prompt-guided)

# Extension B
AGENT_PERSISTENCE_ENABLED = True
MODEL_TIER_BASE = "google/gemini-2.5-flash-lite"
MODEL_TIER_MID = "google/gemini-2.5-flash"
MODEL_TIER_TOP = "google/gemini-2.5-pro"
KILL_THRESHOLD = 0.0
WHALE_PERCENTILE = 0.01
ELITE_PERCENTILE = 0.001
```

---

## 10. Backtesting Mode and the Future-Leakage Problem

### 10.1 Backtesting Architecture

Backtesting mode simulates historical markets as if they were live, using agents that see only information available at the time. The goal is to evolve an agent population on known-outcome markets, then deploy on a live market.

```
BACKTESTING                              LIVE DEPLOYMENT
┌─────────────────────────┐              ┌────────────────────────┐
│ Historical market 1     │              │ Live Polymarket market │
│ (docs from before res.) │              │ (real-time API data)   │
│ → simulate → resolve    │              │ → agents bet based on  │
│                         │              │   evolved population   │
│ Historical market 2     │              │                        │
│ → simulate → resolve    │──evolve──▶   │ Agents carry over with │
│                         │  agents      │ wallets + model tiers  │
│ Historical market N     │              │                        │
│ → simulate → resolve    │              │                        │
└─────────────────────────┘              └────────────────────────┘
```

### 10.2 Live Data Feed for Backtesting

During backtesting, the agents need to see "live" market prices, but these are replayed from historical data. The system needs a `PriceReplayFeed` that the `PolymarketEnvironment` reads from instead of querying the internal AMM.

**Key decision:** During backtesting, do agents trade on the **internal simulated AMM** or on the **historical real prices**?

**Recommended approach:** Agents see real historical prices in their observation, but their trades execute against the internal AMM. This way:
- The prices agents *observe* are realistic (real Polymarket data)
- The prices agents' *trades* affect are internal (their trades don't "move the real market")
- At resolution, positions settle based on the known outcome

The agents can "inspect the order book" by viewing historical order book snapshots at the current simulated timestamp.

```python
class PriceReplayFeed:
    """Replays historical Polymarket price data as if live."""

    def __init__(self, market_id: str, price_csv_path: str):
        self.prices = pd.read_csv(price_csv_path)  # timestamp, yes_price, no_price
        self.current_index = 0

    def get_price_at(self, simulated_time: datetime) -> Tuple[float, float]:
        """Return (yes_price, no_price) at the given simulated time."""
        # Find the closest historical timestamp <= simulated_time
        mask = self.prices['timestamp'] <= simulated_time.isoformat()
        if mask.any():
            row = self.prices[mask].iloc[-1]
            return row['yes_price'], row['no_price']
        return 0.5, 0.5  # default before any data
```

Inject these prices into the agent's observation prompt (in `PolymarketEnvironment.to_text_prompt()`), replacing or supplementing the internal AMM prices.

### 10.3 The Future-Leakage Problem

Three forms and their mitigations:

#### Form 1: Documents Containing Future Information

**Problem:** An article written after market resolution accidentally describes the outcome.

**Mitigation (strict, solvable):** Every document associated with a backtesting market must have a publication date. A hard filter rejects any document published after the market's creation date (conservative) or resolution date (loose).

```python
def validate_documents_for_backtest(docs: List[Document], market_created_at: datetime):
    """Reject documents published after market creation."""
    for doc in docs:
        if doc.published_at is None:
            raise ValueError(f"Document '{doc.name}' has no publication date — "
                             f"cannot use in backtesting without date metadata")
        if doc.published_at > market_created_at:
            raise ValueError(f"Document '{doc.name}' published {doc.published_at} "
                             f"is after market creation {market_created_at}")
```

**Practical challenge:** Many documents don't have clean publication dates. For web articles, extract from HTML metadata. For PDFs, use file metadata or require manual annotation.

#### Form 2: LLM Parametric Knowledge

**Problem:** The LLM was trained on data that includes the market's outcome. When it "reasons" about the question, it may be recalling the answer rather than reasoning.

**Mitigation (partial, not fully solvable):**

1. **Use markets that resolved after the model's training cutoff.** If using Gemini 2.5 Flash Lite (training cutoff ~early 2025), only backtest on markets that resolved after early 2025. This limits your historical corpus to the most recent few months.

2. **Test for leakage explicitly.** Run the same agents on a resolved market with NO documents (just the question). If they predict the outcome correctly at >70% rate, parametric leakage is likely present for that question. Flag and exclude those markets from backtesting.

3. **Use the backtesting results for relative ranking, not absolute calibration.** Even if all agents are "cheating" slightly via parametric knowledge, the *relative* ranking of agents (who does better than whom) is still meaningful, because all agents have access to the same parametric knowledge. The selection pressure still works.

#### Form 3: Graph NER Leakage

**Problem:** The LLM doing NER extraction subtly encodes future knowledge into entity summaries (e.g., writing "former CEO" when the person was current CEO at the time).

**Mitigation (partial):**

1. **Prompt the NER extractor with the simulation date.** Add to the NER system prompt: "The current date is {market_creation_date}. Describe entities as they would be known at this point in time, not as they may be known later."

2. **Review NER output for temporal anomalies.** After extraction, scan for keywords like "former", "late", "eventually", "would later" that suggest future knowledge.

### 10.4 Honest Assessment

**Forms 2 and 3 cannot be fully solved.** The practical approach is:

1. Accept that backtesting performance is an optimistic upper bound
2. Use backtesting for agent *selection* (relative ranking) rather than calibration (absolute prediction accuracy)
3. Validate on a small set of markets where you can confirm no leakage (e.g., questions about events that happened very recently and are unlikely to be in training data)
4. Track the gap between backtesting accuracy and live accuracy as a "leakage discount" and report it

---

## 11. New File Structure

Changes to the base system's file structure:

```
backend/
├── data/                                    # NEW: static data for calibration
│   └── polymarket_cdfs/
│       ├── cdfs.json                        # empirical bet-size CDFs
│       ├── market_cohorts.json              # cohort classification rules
│       ├── wallet_distributions.json        # wealth bucket boundaries
│       └── metadata.json                    # data freshness info
│   └── polymarket_history/                  # for backtesting
│       ├── markets/                         # resolved market data
│       ├── prices/                          # historical price CSVs
│       ├── orderbooks/                      # order book snapshots (optional)
│       └── documents/                       # time-gated document sets
│
├── app/
│   ├── models/
│   │   └── persistent_agent.py              # NEW: PersistentAgentState, MarketSeriesConfig
│   └── services/
│       └── market_series_controller.py      # NEW: outer loop for agent persistence
│
├── wonderwall/
│   └── simulations/
│       └── polymarket/
│           ├── calibrator.py                # NEW: BetSizeCalibrator, BetSizeCDF
│           ├── price_replay.py              # NEW: PriceReplayFeed for backtesting
│           ├── actions.py                   # MODIFIED: conviction instead of amount_usd
│           ├── prompts.py                   # MODIFIED: conviction guidance + track record
│           └── platform.py                  # MODIFIED: variable initial balances, resolve_market
│
├── scripts/
│   ├── collect_polymarket_data.py           # NEW: data collection from Polymarket API + chain
│   ├── build_cdf_tables.py                  # NEW: process raw data into CDFs
│   └── run_market_series.py                 # NEW: CLI for running multi-market evolution
│
└── uploads/
    └── series/                              # NEW: persistent state for market series
        └── {series_id}/
            ├── series_config.json
            ├── persistent_agents.json
            ├── history/
            └── markets/
```

---

*End of SECONDARY_PRD v1.0*
