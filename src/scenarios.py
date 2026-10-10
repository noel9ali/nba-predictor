"""Availability scenario blending for one game (phase 6).

For each team take up to MAX_SCENARIO_PLAYERS players with SCENARIO_P_LOW < p_play < SCENARIO_P_HIGH and the
largest impact (rating x expected minutes). Enumerate the 2^k present/absent combinations, score each with the
model, and blend with weights = product of p_play (present) or 1 - p_play (absent). The blended probability is
stored as home_win_prob; the scenario spread gives prob_range_low/high.

Pure functions: the caller supplies `score(overrides) -> home win probability`, where overrides maps player_id
to 1.0 (plays) or 0.0 (sits) on top of the base p_play map.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import pandas as pd

import config


@dataclass(frozen=True)
class Scenario:
    key: str
    weight: float
    overrides: dict
    home_win_prob: float | None = None
    label: str = ""


def uncertain_players(roster: pd.DataFrame, k: int | None = None) -> pd.DataFrame:
    """roster: player_id, p_play, rating, exp_min (and optionally name). Top k uncertain players by impact."""
    k = config.MAX_SCENARIO_PLAYERS if k is None else k
    if roster is None or roster.empty:
        return pd.DataFrame(columns=["player_id", "p_play", "impact"])
    r = roster.copy()
    # impact = |rating| x minutes; the minutes he would play if available when known (exp_min is already
    # multiplied by p_play), else exp_min.
    minutes_col = "min_if_play" if "min_if_play" in r else "exp_min"
    r["impact"] = r["rating"].astype(float).abs() * r[minutes_col].astype(float).clip(lower=0)
    mask = (r["p_play"] > config.SCENARIO_P_LOW) & (r["p_play"] < config.SCENARIO_P_HIGH)
    return r[mask].sort_values(["impact", "player_id"], ascending=[False, True]).head(k)


def enumerate_scenarios(players: pd.DataFrame, names: dict | None = None) -> list[Scenario]:
    """All present/absent combinations of the given uncertain players (both teams together)."""
    names = names or {}
    if players is None or players.empty:
        return [Scenario("base", 1.0, {}, label="as reported")]
    ids = [int(p) for p in players["player_id"]]
    probs = [float(p) for p in players["p_play"]]
    out = []
    for combo in itertools.product((1, 0), repeat=len(ids)):
        weight = 1.0
        for present, p in zip(combo, probs):
            weight *= p if present else (1.0 - p)
        key = "|".join(f"{pid}={present}" for pid, present in zip(ids, combo))
        label = ", ".join(f"{names.get(pid, pid)} {'plays' if present else 'out'}" for pid, present in zip(ids, combo))
        out.append(Scenario(key, weight, {pid: float(present) for pid, present in zip(ids, combo)}, label=label))
    total = sum(s.weight for s in out)
    return [Scenario(s.key, s.weight / total, s.overrides, label=s.label) for s in out]


def blend(scenarios: list[Scenario], score) -> tuple[float, float, float, list[Scenario]]:
    """Score every scenario; returns (blended prob, range low, range high, scored scenarios)."""
    scored = [Scenario(s.key, s.weight, s.overrides, float(score(s.overrides)), s.label) for s in scenarios]
    blended = sum(s.weight * s.home_win_prob for s in scored)
    live = [s.home_win_prob for s in scored if s.weight > 0]
    return float(blended), float(min(live)), float(max(live)), scored


def apply_gate(stake: float, prob_low: float, prob_high: float, *, gate: bool | None = None,
               action: str | None = None, threshold: float | None = None) -> tuple[float, str | None]:
    """Uncertainty gate (default off). Returns (stake, skip_reason)."""
    gate = config.AVAILABILITY_GATE if gate is None else gate
    action = config.AVAILABILITY_GATE_ACTION if action is None else action
    threshold = config.UNCERTAINTY_RANGE if threshold is None else threshold
    if not gate or stake <= 0 or (prob_high - prob_low) <= threshold:
        return stake, None
    if action == "skip":
        return 0.0, "availability_uncertain"
    if action == "halve":
        return stake / 2.0, None
    raise ValueError("AVAILABILITY_GATE_ACTION must be 'halve' or 'skip'")


def status_changed(before: dict, after: dict, key_players: list[int]) -> bool:
    """True when any key player's normalized status differs between two {player_id: status} maps
    (a missing entry means 'no report')."""
    return any(before.get(p) != after.get(p) for p in key_players)
