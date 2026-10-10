"""Factor contributions for a logistic game model ("why the pick", drawer option B).

Each factor's contribution is its coefficient times its standardized deviation from the league average
(the scaler's training mean), in logit space, converted to probability points with the local slope
p(1 - p) at the stored probability. Contributions are then reconciled so that

    base rate (home win rate) + sum(contributions) + other == stored probability

with any remainder (rounding, the isotonic calibration step, interactions) in an explicit `other` row.
Availability contributions can be split across the players responsible ("Jokić out: -4.2 pts").
"""

from __future__ import annotations

import numpy as np

FACTOR_GROUPS = {
    "ELO_DIFF": ("base", "Elo difference"), "HOME_ELO": ("base", "Home Elo"), "AWAY_ELO": ("base", "Away Elo"),
    "rest_diff": ("rest", "Rest difference"),
}
for _side, _label in (("HOME", "Home"), ("AWAY", "Away")):
    for _stat, _name in (("PTS", "points"), ("FG_PCT", "FG%"), ("REB", "rebounds"), ("AST", "assists"),
                         ("TOV", "turnovers"), ("STOCKS", "steals+blocks")):
        FACTOR_GROUPS[f"{_side}_roll_{_stat}"] = ("form", f"{_label} recent {_name}")


def factor_group(feature: str) -> tuple[str, str]:
    if feature in FACTOR_GROUPS:
        return FACTOR_GROUPS[feature]
    name = feature.split(":", 1)[-1]
    if any(t in name for t in ("rest_days", "is_b2b", "games_last_7")):
        return "rest", name.replace("_", " ")
    return "availability", name.replace("_", " ")


def linear_coefficients(model) -> np.ndarray:
    """Coefficients of a LogisticRegression, or the mean over CalibratedClassifierCV's fitted folds."""
    if hasattr(model, "coef_"):
        return np.asarray(model.coef_).ravel()
    folds = getattr(model, "calibrated_classifiers_", None)
    if folds:
        coefs = []
        for fold in folds:
            est = getattr(fold, "estimator", None) or getattr(fold, "base_estimator", None)
            coefs.append(np.asarray(est.coef_).ravel())
        return np.mean(coefs, axis=0)
    raise TypeError("model has no linear coefficients")


def contributions(coef: np.ndarray, z: np.ndarray, features: list[str], prob: float, base_rate: float,
                  *, availability_split: list[tuple[str, float]] | None = None) -> list[dict]:
    """Rows for prediction_factors (prob_points are percentage points). z = standardized feature values.
    availability_split: [(label, weight)] to divide the availability group's total across named players."""
    slope = prob * (1.0 - prob)
    raw = {f: float(c * zz * slope * 100.0) for f, c, zz in zip(features, coef, z)}
    rows = []
    avail_total = 0.0
    for f, pts in raw.items():
        group, label = factor_group(f)
        if group == "availability" and availability_split:
            avail_total += pts
            continue
        rows.append({"factor_key": f, "label": label, "group": group, "prob_points": pts})
    if availability_split:
        total_w = sum(abs(w) for _l, w in availability_split) or 1.0
        for i, (label, w) in enumerate(availability_split):
            pts = avail_total * abs(w) / total_w
            rows.append({"factor_key": f"availability:{i}", "label": f"{label}: {pts:+.1f} pts",
                         "group": "availability", "prob_points": pts})
    rows = [dict(r, prob_points=round(r["prob_points"], 2)) for r in rows]
    target = round((prob - base_rate) * 100.0, 2)
    other = round(target - sum(r["prob_points"] for r in rows), 2)
    rows.sort(key=lambda r: -abs(r["prob_points"]))
    rows.append({"factor_key": "other", "label": "Other (calibration and rounding)", "group": "base",
                 "prob_points": other})
    for i, r in enumerate(rows):
        r["sort_order"] = i
    return rows


def explain(model, scaler, x_row: np.ndarray, features: list[str], prob: float, base_rate: float, **kw) -> list[dict]:
    z = scaler.transform(np.asarray(x_row, dtype=float).reshape(1, -1))[0]
    return contributions(linear_coefficients(model), z, features, prob, base_rate, **kw)
