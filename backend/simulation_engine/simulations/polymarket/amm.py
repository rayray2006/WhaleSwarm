"""Constant-product AMM for binary prediction markets.

Implements the mint-and-swap / split-swap-and-burn mechanism described in
the Convergence PRD section 9.4.  The invariant ``reserve_a * reserve_b = k``
is maintained after every operation.

All trades are capped at 2 % of ``min(reserve_a, reserve_b)`` to prevent
a single agent from drastically moving the price.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# Maximum fraction of the smaller reserve that a single trade may consume.
MAX_TRADE_FRACTION = 0.02


@dataclass(frozen=True)
class TradeResult:
    """Immutable result returned by ``quote_buy`` and ``quote_sell``."""

    shares_out: float
    effective_price: float
    cost_usd: float
    new_reserve_a: float
    new_reserve_b: float


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _max_trade_usd(reserve_a: float, reserve_b: float) -> float:
    """Return the maximum allowed trade size in USD (2 % cap)."""
    return MAX_TRADE_FRACTION * min(reserve_a, reserve_b)


def _validate_reserves(reserve_a: float, reserve_b: float) -> None:
    if reserve_a <= 0 or reserve_b <= 0:
        raise ValueError(
            f"Reserves must be positive: reserve_a={reserve_a}, reserve_b={reserve_b}"
        )


# ------------------------------------------------------------------
# Price queries
# ------------------------------------------------------------------

def get_price(reserve_a: float, reserve_b: float) -> tuple[float, float]:
    """Return ``(price_a, price_b)`` where ``price_a + price_b == 1.0``.

    In a constant-product AMM the price of outcome A (YES) is
    ``reserve_b / (reserve_a + reserve_b)`` because buying A removes it
    from the pool, making it scarcer, and its price is proportional to
    the *other* reserve.
    """
    _validate_reserves(reserve_a, reserve_b)
    total = reserve_a + reserve_b
    price_a = reserve_b / total
    price_b = reserve_a / total
    return (price_a, price_b)


# ------------------------------------------------------------------
# Buying shares (mint-and-swap)
# ------------------------------------------------------------------

def quote_buy(
    reserve_a: float,
    reserve_b: float,
    outcome: str,
    amount_usd: float,
) -> TradeResult:
    """Quote a buy of *amount_usd* worth of *outcome* shares.

    Mechanism (buying YES / outcome A):

    1. **Mint** ``minted = amount_usd`` complete sets (one A share + one B
       share per dollar).
    2. **Swap** the unwanted B shares into the pool:
       ``new_reserve_b = reserve_b + minted``
    3. The AMM invariant gives back A shares:
       ``new_reserve_a = k / new_reserve_b``
       ``swapped_a_out = reserve_a - new_reserve_a``
    4. Total shares received: ``shares_out = minted + swapped_a_out``

    Mirror for NO (outcome B).

    Raises ``ValueError`` if *amount_usd* exceeds the 2 % cap.
    """
    _validate_reserves(reserve_a, reserve_b)

    if amount_usd <= 0:
        raise ValueError("amount_usd must be positive")

    cap = _max_trade_usd(reserve_a, reserve_b)
    if amount_usd > cap:
        raise ValueError(
            f"Trade size ${amount_usd:.4f} exceeds 2% cap of ${cap:.4f}"
        )

    k = reserve_a * reserve_b
    minted = amount_usd
    outcome_upper = outcome.upper()

    if outcome_upper in ("A", "YES"):
        # Add unwanted B to pool, get back A.
        new_rb = reserve_b + minted
        new_ra = k / new_rb
        swapped_out = reserve_a - new_ra
        shares_out = minted + swapped_out
        new_reserve_a = new_ra
        new_reserve_b = new_rb
    elif outcome_upper in ("B", "NO"):
        # Add unwanted A to pool, get back B.
        new_ra = reserve_a + minted
        new_rb = k / new_ra
        swapped_out = reserve_b - new_rb
        shares_out = minted + swapped_out
        new_reserve_a = new_ra
        new_reserve_b = new_rb
    else:
        raise ValueError(f"outcome must be 'YES'/'A' or 'NO'/'B', got '{outcome}'")

    effective_price = amount_usd / shares_out if shares_out > 0 else 0.0

    return TradeResult(
        shares_out=shares_out,
        effective_price=effective_price,
        cost_usd=amount_usd,
        new_reserve_a=new_reserve_a,
        new_reserve_b=new_reserve_b,
    )


# ------------------------------------------------------------------
# Selling shares (split-swap-and-burn)
# ------------------------------------------------------------------

def quote_sell(
    reserve_a: float,
    reserve_b: float,
    outcome: str,
    shares: float,
) -> TradeResult:
    """Quote a sell of *shares* of *outcome*.

    Mechanism (selling YES / outcome A):

    The seller wants to convert A-shares back to USD.  They need to
    acquire matching B-shares so that pairs can be burned for $1 each.

    Let ``S`` = shares to sell, ``x`` = number of A-shares swapped into
    the pool to obtain B-shares.  After the swap the agent has
    ``S - x`` A-shares and ``x * reserve_b / (reserve_a + x)`` B-shares
    (from the AMM).  They burn pairs, so:

        ``S - x = x * R_b / (R_a + x)``

    Rearranging:

        ``(S - x)(R_a + x) = x * R_b``
        ``S*R_a + S*x - x*R_a - x^2 = x*R_b``
        ``x^2 + x*(R_a + R_b - S) - S*R_a = 0``

    When selling outcome A, R_other = R_b (the other outcome's reserve),
    and the constant term uses R_a (the reserve of the outcome being sold).

    Actually, let's re-derive more carefully for selling A-shares:
    - We have S shares of A.  We swap x of them into the pool.
    - Pool goes from (R_a, R_b) to (R_a + x, k/(R_a + x)).
    - B-shares received = R_b - k/(R_a + x).
    - We need B-shares received = S - x (to pair and burn).
    - R_b - k/(R_a + x) = S - x
    - R_b*(R_a + x) - k = (S - x)*(R_a + x)
    - R_b*R_a + R_b*x - R_a*R_b = S*R_a + S*x - x*R_a - x^2
    - R_b*x = S*R_a + S*x - x*R_a - x^2
    - x^2 + x*(R_a - S - R_b) + S*R_a  ... wait, let me use the standard form.

    Rearranging to standard quadratic ``ax^2 + bx + c = 0``:

        x^2 + x*(R_a + R_b - S) - S*R_b = 0    (for selling A)

    where:
        a = 1
        b = R_a + R_b - S
        c = -S * R_b

    Solving: x = (-b + sqrt(b^2 - 4*a*c)) / (2*a)

    USD out = S - x  (number of complete sets burned).

    Mirror for selling B: swap x B-shares into pool.
        x^2 + x*(R_a + R_b - S) - S*R_a = 0

    Raises ``ValueError`` if *shares* would exceed the 2 % cap in
    effective USD terms, or if the sell is not feasible.
    """
    _validate_reserves(reserve_a, reserve_b)

    if shares <= 0:
        raise ValueError("shares must be positive")

    outcome_upper = outcome.upper()

    if outcome_upper in ("A", "YES"):
        # Selling A-shares: swap some A into pool to get B.
        r_same = reserve_a    # reserve of outcome being sold
        r_other = reserve_b   # reserve of the other outcome
    elif outcome_upper in ("B", "NO"):
        # Selling B-shares: swap some B into pool to get A.
        r_same = reserve_b
        r_other = reserve_a
    else:
        raise ValueError(f"outcome must be 'YES'/'A' or 'NO'/'B', got '{outcome}'")

    # Quadratic: x^2 + x*(r_same + r_other - S) - S*r_other = 0
    a = 1.0
    b = r_same + r_other - shares
    c = -shares * r_other

    discriminant = b * b - 4.0 * a * c
    if discriminant < 0:
        raise ValueError("Sell not feasible: negative discriminant")

    x = (-b + math.sqrt(discriminant)) / (2.0 * a)

    if x < 0 or x > shares:
        raise ValueError(
            f"Sell not feasible: swap amount x={x:.6f} out of range [0, {shares:.6f}]"
        )

    usd_out = shares - x

    if usd_out <= 0:
        raise ValueError("Sell yields zero or negative USD")

    # Enforce 2% cap on the effective USD amount.
    cap = _max_trade_usd(reserve_a, reserve_b)
    if usd_out > cap:
        raise ValueError(
            f"Sell value ${usd_out:.4f} exceeds 2% cap of ${cap:.4f}"
        )

    # Compute new reserves after the swap of x shares into the pool.
    k = reserve_a * reserve_b
    if outcome_upper in ("A", "YES"):
        new_reserve_a = reserve_a + x
        new_reserve_b = k / new_reserve_a
    else:
        new_reserve_b = reserve_b + x
        new_reserve_a = k / new_reserve_b

    effective_price = usd_out / shares if shares > 0 else 0.0

    return TradeResult(
        shares_out=shares,
        effective_price=effective_price,
        cost_usd=usd_out,
        new_reserve_a=new_reserve_a,
        new_reserve_b=new_reserve_b,
    )


# ------------------------------------------------------------------
# Anchor to real-world price
# ------------------------------------------------------------------

def anchor_to_real_price(
    reserve_a: float,
    reserve_b: float,
    real_price_yes: float,
) -> tuple[float, float]:
    """Reset reserves to match *real_price_yes*, preserving ``k``.

    Given ``k = reserve_a * reserve_b`` and the desired
    ``price_yes = reserve_b / (reserve_a + reserve_b) = p``:

        new_reserve_b = sqrt(k * p / (1 - p))
        new_reserve_a = k / new_reserve_b

    Returns ``(new_reserve_a, new_reserve_b)``.

    Raises ``ValueError`` if *real_price_yes* is not in ``(0, 1)``.
    """
    _validate_reserves(reserve_a, reserve_b)

    if real_price_yes <= 0.0 or real_price_yes >= 1.0:
        raise ValueError(
            f"real_price_yes must be in (0, 1), got {real_price_yes}"
        )

    k = reserve_a * reserve_b
    p = real_price_yes

    new_reserve_b = math.sqrt(k * p / (1.0 - p))
    new_reserve_a = k / new_reserve_b

    return (new_reserve_a, new_reserve_b)
