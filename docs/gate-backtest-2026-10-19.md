# Uncertainty gate, stake sizing and early-season caution: what can and cannot be backtested (Oct 19 2026)

No historical odds exist, so **profit was not measured**. What was measured: the candidate's own errors by game attribute,
and a clearly labelled stylized Kelly simulation. Scratch code is outside the repo; numbers below are the study's.

## Setup (3a)
Leaderboard test window (games from 2025-02-25, after the candidate's training data ends). For each of the 1,566 games with a
tip-60 report, the real code path (`availability_predict.GameAvailability` + `score_with_candidate`, candidate
`lr-calibrated-availability-v1` loaded with the repo loader, statuses from the archived newest-report-at-tip-60 rows, inferred
rosters) gave the scenario-blended probability, low/high range, scenario and key-player counts. Candidate on these games:
accuracy 70.2%, log loss 0.5826, Brier 0.1992 (production gradient boosting on the same games: Brier 0.2102).
Range: mean 0.037, median 0.011, 46% of games exactly 0, **25% above the gate threshold 0.06**, 39% above 0.03.

## Does anything predict larger error? (3b; Brier, bootstrap by game, 2,000 resamples)
"Excess" = observed Brier minus the Brier the model's own probabilities imply (mean p(1-p)); positive = worse than the
model claims. Slope = logistic recalibration slope (1 = calibrated, below 1 = overconfident).

| bucket | n | Brier | excess [95% CI] | slope [95% CI] |
|---|---|---|---|---|
| range < 0.01 | 774 | 0.188 | -0.009 [-0.020, +0.004] | 1.10 [0.91, 1.33] |
| range 0.01-0.03 | 182 | 0.202 | -0.007 [-0.027, +0.015] | 1.17 [0.80, 1.69] |
| range 0.03-0.06 | 218 | 0.215 | +0.012 [-0.011, +0.036] | 0.86 [0.58, 1.24] |
| **range > 0.06 (gate)** | 392 | 0.211 | +0.001 [-0.015, +0.019] | 0.98 [0.72, 1.29] |
| 0 uncertain key players | 936 | 0.192 | -0.008 [-0.019, +0.003] | 1.10 [0.92, 1.31] |
| 1 / 2+ uncertain key players | 418 / 212 | 0.207 / 0.215 | +0.003 / +0.008 (CIs +-0.015) | 0.99 / 0.87 (wide) |
| status change 06:00 -> tip-60 (shipped logic) | 1,090 | 0.197 | -0.005 [-0.015, +0.004] | 1.09 [0.95, 1.27] |
| no change | 476 | 0.204 | +0.002 [-0.013, +0.017] | 0.94 [0.73, 1.21] |
| report not written on game day | 140 | 0.219 | +0.016 [-0.013, +0.048] | 0.70 [0.37, 1.20] |
| first 21 days of 2024-25 / 2025-26 | 154 | 0.201 | -0.009 [-0.032, +0.017] | 1.13 [0.71, 1.73] |
| rest of window | 1,412 | 0.199 | -0.002 [-0.011, +0.006] | 1.03 [0.90, 1.18] |
| status changed after pricing (tip-60 -> tip-5) | 29 | 0.221 | +0.002 [-0.046, +0.056] | n/a |

* Wide-range games do have a higher raw Brier (0.211 vs 0.188), but that is the inherent uncertainty the range already
  reflects: the excess over what the model expects is ~0 and the calibration slope is 0.98. Regressing squared error on range
  gives +0.0165 per 0.06 of range [+0.0014, +0.0324], borderline; early season, status change and key-player count add
  nothing (all CIs straddle 0).
* The shipped status-change flag is true in 70% of games (a missing earlier entry counts as a change), so it cannot be a gate.
  The flag that matters in production (change AFTER pricing) fired in 29 of 1,566 games here: too few to say anything.
* "Game-day vs not": read as "was the newest report written on game day": 140 games, noisy, direction as expected, not significant.
* Calibration by probability bucket: every excess CI contains 0 (slopes are very noisy in 200-400-game buckets).
* Shrinkage (choose lambda, threshold and target on the earlier half 2025-02-25..2025-12-22, n=783; evaluate on the later half,
  n=783): best on the earlier half was a 10% pull to 0.5 when range > 0.04. On the later half: log loss +0.0003 [-0.0016, +0.0022],
  Brier +0.0002 [-0.0005, +0.0008]. Fixed alternatives (50% toward the gradient-boosting model, or 50% toward 0.5, above 0.06 or
  0.03) all made log loss worse or equal (pull to 0.5: +0.008 [+0.001, +0.015]). **Shrinking does not help.**

## Stylized Kelly simulation (3c) -- NOT real-market ROI
"Market" = the production gradient-boosting model (no availability) with a 4.5% proportional margin, optionally blended with
the candidate (k = share of the candidate in the market; k=0 is a market that knows no injury news). Bet the side with positive
edge after the margin, quarter-Kelly capped at 5%, max decimal odds 5, stakes sized on the start-of-night bankroll, 210 nights /
1,566 games, 2,000 bootstrap resamples of nights. k=0 produces absurd growth (a weak market vs a better model; ignore the levels);
the comparison between policies is what is read. Paired difference in log terminal wealth vs plain quarter-Kelly (negative = worse):

| policy | k=0.5 market | k=0.8 market |
|---|---|---|
| gate ON, halve if range > 0.06 (shipped option) | -0.09 [-0.37, +0.20] | +0.00 [-0.04, +0.04] |
| gate ON, skip if range > 0.06 | -0.20 [-0.77, +0.38] | +0.00 [-0.08, +0.09] |
| range-scaled stake | -0.16 [-0.52, +0.21] | -0.02 [-0.07, +0.04] |
| half stakes in the first 21 days | -0.20 [-0.37, -0.06] | -0.03 [-0.07, +0.01] |
| flat 1% of bankroll vs quarter-Kelly | -1.36 [-2.08, -0.66] | +0.16 [-0.06, +0.38] |

Drawdown (k=0.5, 95th percentile of max drawdown): quarter-Kelly 33%, gate-halve 28%, gate-skip 26%, range-scaled 26%, early-half 34%;
paths with a >=50% drawdown: 1, 0, 0, 0, 1 of 2,000; no path fell below 25% of the starting bankroll under any policy. So the gate
buys a few points of drawdown for a statistically indistinguishable (and, at k=0, clearly lower) growth; the early-season halving buys
no drawdown reduction at all. These are properties of the simulator, not of any real book.

## Recommendation (3d)
* **Gate: leave OFF.** The data give no sign that the candidate is miscalibrated or overconfident when the range is wide, so there
  is no calibration case for cutting stakes; the simulation shows it costs growth when the model has an edge. Its true rationale is
  "the market has the news we lack", which only real prices can test.
* **Early-season stake scaling: no evidence for it in these 154 early games; do not add an automatic multiplier.** The earlier tuning
  note found all models worse in the first 3 weeks, but here that is explained by probabilities nearer 0.5 (the model expects it).
  If extra caution is wanted for the first fortnight, make it a manual bankroll-level decision, not a code rule.
* **Shrink wide-range probabilities: no.** **Range-based multiplier: no.**
* **Data needed to validate on real prices** (from the new archive, `docs/odds-archive.md`): an opening snapshot at pricing and a near-close
  snapshot for each game. With the closing call on, CLV by range bucket is by far the cheapest test (assuming a per-game CLV spread of
  ~0.015, ~35-150 games per bucket resolve +-0.005): about 600 games (half a season) puts ~150 in the range > 0.06 bucket. The real
  question, whether wide-range games are priced better by the market than by us (Brier of model vs close by range bucket), needs ~2,400
  games (two seasons) for a 0.002 gap, ~400 for 0.005. Realised ROI needs thousands of bets and is not a near-term target.
  `scripts/market_vs_model.py` computes the pieces; add a range column from `prediction_availability_inputs` to split by bucket.
