"""Historical price replay feed for backtesting.

Loads a CSV of timestamped price observations and provides
point-in-time price lookups so the simulation can replay a
market's price history instead of relying solely on the internal AMM.

CSV format::

    timestamp,yes_price,no_price
    2024-01-15T10:00:00Z,0.62,0.38
    2024-01-15T11:00:00Z,0.64,0.36
    ...

The feed can also validate that documents injected into agent prompts
were published *before* the market was created, preventing look-ahead
bias in backtests.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Price observation
# ------------------------------------------------------------------

@dataclass(frozen=True, order=True)
class PriceObservation:
    """A single timestamped price point."""
    timestamp: datetime
    yes_price: float
    no_price: float


# ------------------------------------------------------------------
# PriceReplayFeed
# ------------------------------------------------------------------

class PriceReplayFeed:
    """Replay historical prices for a prediction market.

    Parameters
    ----------
    market_id:
        Identifier for the market (for logging / diagnostics).
    price_csv_path:
        Path to a CSV file with columns ``timestamp``, ``yes_price``,
        ``no_price``.
    """

    def __init__(self, market_id: str, price_csv_path: str | Path) -> None:
        self.market_id = market_id
        self.price_csv_path = Path(price_csv_path)
        self.observations: List[PriceObservation] = []
        self._timestamps: List[datetime] = []

        self._load_csv()

    # ----------------------------------------------------------------
    # Loading
    # ----------------------------------------------------------------

    def _load_csv(self) -> None:
        """Load and validate the price CSV."""
        if not self.price_csv_path.exists():
            raise FileNotFoundError(
                f"Price CSV not found: {self.price_csv_path}"
            )

        observations = []

        with open(self.price_csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)

            required_cols = {"timestamp", "yes_price", "no_price"}
            if reader.fieldnames is None:
                raise ValueError(f"CSV has no headers: {self.price_csv_path}")
            missing = required_cols - set(reader.fieldnames)
            if missing:
                raise ValueError(
                    f"CSV missing required columns: {missing}. "
                    f"Found: {reader.fieldnames}"
                )

            for row_num, row in enumerate(reader, start=2):
                try:
                    ts = _parse_timestamp(row["timestamp"])
                    yes_p = float(row["yes_price"])
                    no_p = float(row["no_price"])
                except (ValueError, KeyError) as e:
                    logger.warning(
                        "Skipping row %d in %s: %s",
                        row_num, self.price_csv_path, e,
                    )
                    continue

                # Basic validation
                if not (0.0 <= yes_p <= 1.0):
                    logger.warning(
                        "Row %d: yes_price=%.4f out of [0,1], clamping",
                        row_num, yes_p,
                    )
                    yes_p = max(0.0, min(1.0, yes_p))

                if not (0.0 <= no_p <= 1.0):
                    logger.warning(
                        "Row %d: no_price=%.4f out of [0,1], clamping",
                        row_num, no_p,
                    )
                    no_p = max(0.0, min(1.0, no_p))

                observations.append(PriceObservation(
                    timestamp=ts,
                    yes_price=yes_p,
                    no_price=no_p,
                ))

        # Sort by timestamp
        observations.sort(key=lambda o: o.timestamp)
        self.observations = observations
        self._timestamps = [o.timestamp for o in observations]

        logger.info(
            "Loaded %d price observations for market %s from %s",
            len(observations),
            self.market_id,
            self.price_csv_path,
        )

        if observations:
            logger.info(
                "  Time range: %s -> %s",
                observations[0].timestamp.isoformat(),
                observations[-1].timestamp.isoformat(),
            )

    # ----------------------------------------------------------------
    # Price queries
    # ----------------------------------------------------------------

    def get_price_at(
        self,
        simulated_time: datetime,
    ) -> Tuple[float, float]:
        """Return ``(yes_price, no_price)`` at the given time.

        Finds the observation with the closest timestamp to
        ``simulated_time``.  If ``simulated_time`` is before the first
        observation, returns the first price.  If after the last,
        returns the last price.

        Parameters
        ----------
        simulated_time:
            The point in simulated time to query.

        Returns
        -------
        Tuple[float, float]
            ``(yes_price, no_price)``
        """
        if not self.observations:
            raise ValueError(
                f"No price data loaded for market {self.market_id}"
            )

        # Make timezone-aware if needed
        if simulated_time.tzinfo is None:
            simulated_time = simulated_time.replace(tzinfo=timezone.utc)

        # Binary search for the closest timestamp
        idx = self._find_closest_index(simulated_time)
        obs = self.observations[idx]

        return (obs.yes_price, obs.no_price)

    def get_price_at_round(
        self,
        round_num: int,
        total_rounds: int,
    ) -> Tuple[float, float]:
        """Map a simulation round to a timestamp and return prices.

        Linearly interpolates the round number into the time range
        of the loaded observations.  This is useful when the simulation
        does not track wall-clock time but uses discrete rounds.

        Parameters
        ----------
        round_num:
            Current round (0-indexed).
        total_rounds:
            Total number of rounds in the simulation.

        Returns
        -------
        Tuple[float, float]
            ``(yes_price, no_price)``
        """
        if not self.observations:
            raise ValueError(
                f"No price data loaded for market {self.market_id}"
            )

        if total_rounds <= 1:
            idx = 0
        else:
            frac = round_num / (total_rounds - 1)
            frac = max(0.0, min(1.0, frac))
            idx = int(frac * (len(self.observations) - 1))

        obs = self.observations[idx]
        return (obs.yes_price, obs.no_price)

    def _find_closest_index(self, target: datetime) -> int:
        """Binary search for the observation closest to ``target``."""
        if not self._timestamps:
            return 0

        # Ensure target is tz-aware
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)

        lo, hi = 0, len(self._timestamps) - 1

        # Edge cases
        if target <= self._timestamps[lo]:
            return lo
        if target >= self._timestamps[hi]:
            return hi

        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self._timestamps[mid] <= target:
                lo = mid
            else:
                hi = mid

        # Return whichever is closer
        delta_lo = abs((target - self._timestamps[lo]).total_seconds())
        delta_hi = abs((target - self._timestamps[hi]).total_seconds())
        return lo if delta_lo <= delta_hi else hi

    # ----------------------------------------------------------------
    # Document validation for backtests
    # ----------------------------------------------------------------

    @staticmethod
    def validate_documents_for_backtest(
        docs: List[Dict],
        market_created_at: datetime,
    ) -> Tuple[List[Dict], List[Dict]]:
        """Filter documents to prevent look-ahead bias.

        Splits documents into ``(valid, rejected)`` based on their
        publication date relative to the market creation date.

        Parameters
        ----------
        docs:
            List of document dicts, each optionally containing a
            ``published_at`` or ``date`` key with an ISO timestamp.
        market_created_at:
            The datetime when the market was created.  Documents
            published after this date are rejected.

        Returns
        -------
        Tuple[List[Dict], List[Dict]]
            ``(valid_docs, rejected_docs)``
        """
        if market_created_at.tzinfo is None:
            market_created_at = market_created_at.replace(tzinfo=timezone.utc)

        valid = []
        rejected = []

        for doc in docs:
            # Try to extract a publication date
            date_str = doc.get("published_at") or doc.get("date") or doc.get("timestamp")
            if not date_str:
                # No date -> assume it's valid (conservative approach)
                valid.append(doc)
                continue

            try:
                pub_date = _parse_timestamp(str(date_str))
            except ValueError:
                # Can't parse -> assume valid
                valid.append(doc)
                continue

            if pub_date <= market_created_at:
                valid.append(doc)
            else:
                rejected.append(doc)
                logger.warning(
                    "Rejected document (look-ahead): published=%s, "
                    "market_created=%s, title=%s",
                    pub_date.isoformat(),
                    market_created_at.isoformat(),
                    doc.get("title", "?")[:60],
                )

        logger.info(
            "Document validation: %d valid, %d rejected (look-ahead)",
            len(valid), len(rejected),
        )
        return valid, rejected

    # ----------------------------------------------------------------
    # Utility
    # ----------------------------------------------------------------

    @property
    def time_range(self) -> Optional[Tuple[datetime, datetime]]:
        """Return ``(first_timestamp, last_timestamp)`` or None."""
        if not self.observations:
            return None
        return (self.observations[0].timestamp, self.observations[-1].timestamp)

    @property
    def num_observations(self) -> int:
        return len(self.observations)

    def __repr__(self) -> str:
        return (
            f"PriceReplayFeed(market_id={self.market_id!r}, "
            f"observations={len(self.observations)})"
        )


# ------------------------------------------------------------------
# Timestamp parsing helper
# ------------------------------------------------------------------

def _parse_timestamp(ts_str: str) -> datetime:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime.

    Handles common variants:
    - ``2024-01-15T10:00:00Z``
    - ``2024-01-15T10:00:00+00:00``
    - ``2024-01-15 10:00:00``
    - ``2024-01-15``
    - Unix timestamp as string: ``1705312800``
    """
    ts_str = ts_str.strip()

    # Try unix timestamp
    try:
        unix_ts = float(ts_str)
        if unix_ts > 1_000_000_000:  # Looks like seconds since epoch
            return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    except ValueError:
        pass

    # Normalize common patterns
    ts_str = ts_str.replace("Z", "+00:00")

    # Try ISO parse (Python 3.7+)
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    # Try date-only
    try:
        dt = datetime.strptime(ts_str, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    raise ValueError(f"Cannot parse timestamp: {ts_str!r}")
