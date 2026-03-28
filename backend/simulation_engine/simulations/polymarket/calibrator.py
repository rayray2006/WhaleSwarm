"""Bet-size calibration using empirical CDFs from Polymarket trade data.

Extension A of the Convergence PRD.  Instead of using a fixed fraction
of the agent's balance, we draw bet sizes from empirical cumulative
distribution functions (CDFs) built from real Polymarket trades,
bucketed by market cohort, wealth tier, and position direction.

When a CDF is unavailable or has fewer than 10 observed bettors the
calibrator falls back to a simple heuristic that scales with conviction.
"""

from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Wealth buckets
# ------------------------------------------------------------------

WEALTH_BUCKETS: List[Tuple[str, float, float]] = [
    ("nano",         0.0,      50.0),
    ("retail_small", 50.0,     250.0),
    ("retail_mid",   250.0,    1_000.0),
    ("retail_large", 1_000.0,  5_000.0),
    ("semi_pro",     5_000.0,  25_000.0),
    ("whale",        25_000.0, float("inf")),
]


def _get_wealth_bucket(balance: float) -> str:
    """Return the wealth-bucket label for a given USD balance."""
    for label, lo, hi in WEALTH_BUCKETS:
        if lo <= balance < hi:
            return label
    return "whale"  # fallback for edge cases


# ------------------------------------------------------------------
# Market cohort classification
# ------------------------------------------------------------------

CATEGORY_MAP: Dict[str, str] = {
    "politics":  "politics",
    "election":  "politics",
    "vote":      "politics",
    "president": "politics",
    "congress":  "politics",
    "sports":    "sports",
    "nfl":       "sports",
    "nba":       "sports",
    "soccer":    "sports",
    "football":  "sports",
    "baseball":  "sports",
    "crypto":    "crypto",
    "bitcoin":   "crypto",
    "ethereum":  "crypto",
    "btc":       "crypto",
    "eth":       "crypto",
    "defi":      "crypto",
    "nft":       "crypto",
    "science":   "science",
    "climate":   "science",
    "space":     "science",
    "nasa":      "science",
    "ai":        "science",
    "culture":   "culture",
    "oscar":     "culture",
    "grammy":    "culture",
    "movie":     "culture",
    "music":     "culture",
    "celebrity": "culture",
}

DURATION_TIERS: List[Tuple[str, int, int]] = [
    ("flash",  0,  3),
    ("short",  3,  14),
    ("medium", 14, 60),
    ("long",   60, 999_999),
]

LIQUIDITY_TIERS: List[Tuple[str, float, float]] = [
    ("thin",   0.0,       50_000.0),
    ("normal", 50_000.0,  500_000.0),
    ("deep",   500_000.0, float("inf")),
]


def classify_market_cohort(
    category: str,
    duration_days: int,
    total_volume: float,
) -> str:
    """Return a cohort key like ``politics:medium:normal``.

    Parameters
    ----------
    category:
        Free-text category string.  Matched against :data:`CATEGORY_MAP`
        keywords; defaults to ``"other"`` if nothing matches.
    duration_days:
        Calendar days from market creation to expected resolution.
    total_volume:
        Cumulative USD volume traded on the market so far.
    """
    # Category
    cat_lower = category.lower()
    matched_cat = "other"
    for keyword, cat_label in CATEGORY_MAP.items():
        if keyword in cat_lower:
            matched_cat = cat_label
            break

    # Duration
    dur_label = "long"
    for label, lo, hi in DURATION_TIERS:
        if lo <= duration_days < hi:
            dur_label = label
            break

    # Liquidity
    liq_label = "deep"
    for label, lo, hi in LIQUIDITY_TIERS:
        if lo <= total_volume < hi:
            liq_label = label
            break

    return f"{matched_cat}:{dur_label}:{liq_label}"


# ------------------------------------------------------------------
# BetSizeCDF
# ------------------------------------------------------------------

@dataclass
class BetSizeCDF:
    """Empirical CDF of bet sizes for one (cohort, bucket, position) slice.

    ``sorted_bet_sizes`` is a sorted list of observed bet sizes in USD.
    Sampling at a given quantile does linear interpolation between the
    two nearest observations.
    """

    market_cohort: str
    wealth_bucket: str
    position: str  # "YES" or "NO"
    sorted_bet_sizes: List[float] = field(default_factory=list)
    n_bettors: int = 0

    def sample_at_quantile(self, quantile: float) -> float:
        """Return the bet size at the given quantile (0.0 -- 1.0).

        Uses linear interpolation between adjacent observations.
        Returns 0.0 if no data.
        """
        if not self.sorted_bet_sizes:
            return 0.0

        quantile = max(0.0, min(1.0, quantile))
        n = len(self.sorted_bet_sizes)

        if n == 1:
            return self.sorted_bet_sizes[0]

        # Map quantile to a floating-point index in [0, n-1].
        idx = quantile * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo

        return self.sorted_bet_sizes[lo] + frac * (
            self.sorted_bet_sizes[hi] - self.sorted_bet_sizes[lo]
        )


# ------------------------------------------------------------------
# BetSizeCalibrator
# ------------------------------------------------------------------

MIN_BET_USD = 1.0
MAX_BALANCE_FRACTION = 0.95
MIN_CDF_BETTORS = 10


class BetSizeCalibrator:
    """Look up an empirically calibrated bet size for an agent.

    Parameters
    ----------
    cdf_store:
        Dict mapping CDF keys (``"cohort:bucket:position"``) to
        :class:`BetSizeCDF` instances.
    """

    def __init__(self, cdf_store: Optional[Dict[str, BetSizeCDF]] = None) -> None:
        self.cdf_store: Dict[str, BetSizeCDF] = cdf_store or {}

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def calibrate(
        self,
        agent_id: int,
        conviction: float,
        outcome: str,
        agent_balance: float,
        market_cohort: str,
    ) -> float:
        """Return a calibrated bet size in USD.

        Parameters
        ----------
        agent_id:
            Used only for logging / diagnostics.
        conviction:
            Float in ``[0, 1]`` representing the agent's confidence in its
            trade.  Maps directly to the CDF quantile: 0 = smallest historical
            bet, 1 = largest.
        outcome:
            ``"YES"`` or ``"NO"``.
        agent_balance:
            Current USD balance of the agent.
        market_cohort:
            Cohort key as returned by :func:`classify_market_cohort`.

        Returns
        -------
        float
            Suggested bet amount in USD, clamped to
            ``[MIN_BET_USD, 0.95 * agent_balance]``.
        """
        if agent_balance < MIN_BET_USD:
            return 0.0

        conviction = max(0.0, min(1.0, conviction))
        bucket = _get_wealth_bucket(agent_balance)
        position = outcome.upper()
        cdf_key = f"{market_cohort}:{bucket}:{position}"

        cdf = self.cdf_store.get(cdf_key)

        if cdf is not None and cdf.n_bettors >= MIN_CDF_BETTORS:
            amount = cdf.sample_at_quantile(conviction)
            logger.debug(
                "agent=%s cdf_key=%s quantile=%.3f -> $%.2f",
                agent_id, cdf_key, conviction, amount,
            )
        else:
            amount = self._heuristic_fallback(conviction, agent_balance)
            logger.debug(
                "agent=%s cdf_key=%s FALLBACK conviction=%.3f -> $%.2f",
                agent_id, cdf_key, conviction, amount,
            )

        # Cap at 95% of balance.
        cap = agent_balance * MAX_BALANCE_FRACTION
        amount = min(amount, cap)

        # Enforce minimum.
        amount = max(amount, MIN_BET_USD)

        # Final sanity: can't bet more than balance.
        amount = min(amount, agent_balance)

        return round(amount, 2)

    # ----------------------------------------------------------------
    # Heuristic fallback
    # ----------------------------------------------------------------

    @staticmethod
    def _heuristic_fallback(conviction: float, balance: float) -> float:
        """Simple heuristic when CDF data is unavailable.

        ``base = balance * 0.02`` (2 % of bankroll).
        Scale factor ranges from 0.5 (conviction=0) to 5.0 (conviction=1).
        """
        base = balance * 0.02
        scale = 0.5 + conviction * 4.5
        return base * scale

    # ----------------------------------------------------------------
    # Wealth bucket helper (exposed for tests)
    # ----------------------------------------------------------------

    @staticmethod
    def _get_wealth_bucket(balance: float) -> str:
        return _get_wealth_bucket(balance)


# ------------------------------------------------------------------
# CDF loader
# ------------------------------------------------------------------

def load_cdfs_from_json(path: str | Path) -> Dict[str, BetSizeCDF]:
    """Load a CDF store from a JSON file.

    Expected JSON structure::

        {
            "<cohort>:<bucket>:<position>": {
                "market_cohort": "...",
                "wealth_bucket": "...",
                "position": "YES"|"NO",
                "sorted_bet_sizes": [1.0, 2.5, ...],
                "n_bettors": 42
            },
            ...
        }

    Returns
    -------
    Dict[str, BetSizeCDF]
    """
    path = Path(path)
    if not path.exists():
        logger.warning("CDF file not found: %s -- using empty store", path)
        return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    store: Dict[str, BetSizeCDF] = {}
    for key, entry in raw.items():
        sizes = sorted(entry.get("sorted_bet_sizes", []))
        store[key] = BetSizeCDF(
            market_cohort=entry.get("market_cohort", ""),
            wealth_bucket=entry.get("wealth_bucket", ""),
            position=entry.get("position", "YES"),
            sorted_bet_sizes=sizes,
            n_bettors=entry.get("n_bettors", len(sizes)),
        )

    logger.info("Loaded %d CDF entries from %s", len(store), path)
    return store
