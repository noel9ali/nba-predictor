"""Market-agnostic betting math: implied probability, edge, Kelly fraction and stake sizing.

Nothing here knows about games, teams or players, so the same functions size moneyline bets now and player
props later. The current rule is unchanged: bet only when the edge is above 0, quarter Kelly, at most 5% of
the bankroll, no bets above MAX_DECIMAL_ODDS.

`exposure_left` is the hook for props: the caller passes how much more it may stake on the same entity or
market group (for example a per-game exposure cap across a game bet and correlated props). Unused for now.
"""

from __future__ import annotations

import config


def american_to_decimal(american: float) -> float:
    american = float(american)
    if american == 0:
        raise ValueError("american odds cannot be 0")
    return american / 100.0 + 1.0 if american > 0 else 100.0 / abs(american) + 1.0


def implied_prob(american: float) -> float:
    """Implied probability of an American price (vig included)."""
    american = float(american)
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def edge(prob: float, price: float) -> float:
    """Model probability minus the price's implied probability."""
    return float(prob) - implied_prob(price)


def kelly_fraction(prob: float, price: float) -> float:
    """Full-Kelly fraction of the bankroll (0 when the bet has no positive expectation)."""
    d = american_to_decimal(price)
    k = (float(prob) * d - 1.0) / (d - 1.0)
    return max(0.0, k)


def stake(bankroll: float, prob: float, price: float, *, fraction: float | None = None, cap: float | None = None,
          exposure_left: float | None = None, max_decimal_odds: float | None = None) -> float:
    """Stake for one selection: fraction x Kelly x bankroll, capped at cap x bankroll and at exposure_left.
    Returns 0 when the edge is not positive or the price is longer than max_decimal_odds."""
    fraction = config.KELLY_FRACTION if fraction is None else fraction
    cap = config.KELLY_CAP if cap is None else cap
    max_decimal_odds = config.MAX_DECIMAL_ODDS if max_decimal_odds is None else max_decimal_odds
    if american_to_decimal(price) > max_decimal_odds:
        return 0.0
    if edge(prob, price) <= 0:
        return 0.0
    k = kelly_fraction(prob, price)
    if k <= 0:
        return 0.0
    amount = min(k * fraction * bankroll, bankroll * cap)
    if exposure_left is not None:
        amount = min(amount, max(0.0, float(exposure_left)))
    return float(amount)
