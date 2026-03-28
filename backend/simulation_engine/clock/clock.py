"""Simulation clock with time acceleration.

Converts real elapsed time into simulated time so that, for example,
1 minute of real time can represent 1 hour in the simulation.
"""

from datetime import datetime, timedelta


class Clock:
    """Manages the mapping between real wall-clock time and simulated time.

    Args:
        time_acceleration: Speedup factor.  A value of 60 means that every
            1 real minute corresponds to 1 simulated hour (60 simulated
            minutes).
    """

    def __init__(self, time_acceleration: int = 60) -> None:
        if time_acceleration <= 0:
            raise ValueError("time_acceleration must be a positive integer")
        self.time_acceleration = time_acceleration

    def time_transfer(self, now: datetime, start: datetime) -> datetime:
        """Convert real elapsed time to simulated time.

        Given the real *now* and the real *start* of the simulation, compute
        how much simulated time has passed and return the corresponding
        simulated timestamp (anchored at *start*).

        Args:
            now: Current real wall-clock time.
            start: Real wall-clock time when the simulation began.

        Returns:
            A ``datetime`` representing the current simulated time.
        """
        real_elapsed: timedelta = now - start
        real_seconds = real_elapsed.total_seconds()
        simulated_seconds = real_seconds * self.time_acceleration
        return start + timedelta(seconds=simulated_seconds)

    def real_to_simulated_delta(self, real_delta: timedelta) -> timedelta:
        """Convert a real-time duration to simulated-time duration."""
        return timedelta(seconds=real_delta.total_seconds() * self.time_acceleration)

    def simulated_to_real_delta(self, simulated_delta: timedelta) -> timedelta:
        """Convert a simulated-time duration to real-time duration."""
        return timedelta(seconds=simulated_delta.total_seconds() / self.time_acceleration)
