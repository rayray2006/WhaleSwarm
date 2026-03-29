"""Volume tracker for real-vs-simulated Polymarket volume comparison.

Tracks gross volume (distance, not displacement) on both the real
Polymarket and the simulated AMM.  Used to decide whether real market
updates are significant enough to apply to the simulation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Minimum real-world volume (USD) that always triggers an update.
ABSOLUTE_VOLUME_THRESHOLD = 10_000.0

# Real volume must be at least this fraction of simulated volume to trigger.
RELATIVE_VOLUME_FRACTION = 1.0 / 8.0


@dataclass
class VolumeTracker:
    """Track cumulative volumes to decide when to anchor to real prices."""

    last_anchor_round: int = -1
    last_real_cumulative_volume: float = 0.0
    simulated_volume_since_anchor: float = 0.0

    def add_simulated_volume(self, amount_usd: float) -> None:
        """Record a simulated trade's absolute cost."""
        self.simulated_volume_since_anchor += abs(amount_usd)

    def should_anchor(self, real_cumulative_volume: float) -> bool:
        """Decide whether the real volume delta is large enough to anchor.

        Returns True if:
        - This is the first anchor (no prior data), OR
        - Real volume delta >= simulated_volume / 8, OR
        - Real volume delta >= $10,000
        """
        if self.last_anchor_round < 0:
            return True

        real_delta = real_cumulative_volume - self.last_real_cumulative_volume
        if real_delta < 0:
            real_delta = 0.0

        if real_delta >= ABSOLUTE_VOLUME_THRESHOLD:
            logger.info(
                "Volume threshold met (absolute): real delta $%.0f >= $%.0f",
                real_delta, ABSOLUTE_VOLUME_THRESHOLD,
            )
            return True

        if self.simulated_volume_since_anchor > 0:
            threshold = self.simulated_volume_since_anchor * RELATIVE_VOLUME_FRACTION
            if real_delta >= threshold:
                logger.info(
                    "Volume threshold met (relative): real delta $%.0f >= $%.0f "
                    "(1/8 of simulated $%.0f)",
                    real_delta, threshold, self.simulated_volume_since_anchor,
                )
                return True

        return False

    def reset(self, round_num: int, real_cumulative_volume: float) -> None:
        """Reset tracking after an anchor has been applied."""
        self.last_anchor_round = round_num
        self.last_real_cumulative_volume = real_cumulative_volume
        self.simulated_volume_since_anchor = 0.0
