# Model tuning and re-evaluation, Oct 19, 2026

Source: offline tuning run by a subagent (105 jobs, finished 13:02 ET). The figures below are the subagent's;
they were spot-checked against `data/model_leaderboard.csv` (reproduced production GB log loss 0.6073 vs 0.6075 in
the CSV; v1 0.5835 vs 0.5834) but not independently re-run. Detailed tables, calibration and coefficients stay in the
job's scratch dir (`out\analysis.md`, deleted with the job). Nothing was published; no repo, Supabase or model file
was touched.

## Recommendation
**Keep `lr-calibrated-availability-v1` as the live model for the Oct 20 opener.** No tuned variant, ensemble or tree
model is distinguishable from it on the leaderboard split or on live-like scoring.

- Leaderboard split (n=1,596): tuned logistic (C=0.03) with availability vs v1: Brier -0.00003 [-0.0010, +0.0009],
  log loss +0.0004 [-0.0029, +0.0032]. Noise.
- Tip-60 live-like: CV-best tuned logistic vs v1: Brier -0.00001 [-0.0016, +0.0016]. Noise.
- Walk-forward pooled (4,910 games): inner-CV-best `lr` (C=0.01, baseline+rest+availability) beats v1 by 0.00098 Brier
  [-0.00185, -0.00011] and 0.0029 log loss [-0.0054, -0.0005]. Borderline and tiny (~0.5% relative); it would not
  survive a multiple-comparison correction and is no reason to swap a model the day before it goes live.
- Tree models and the ensemble: tuned gradient boosting, random forest and xgboost are all worse than plain logistic on
  walk-forward (pooled log loss 0.6087-0.6117 vs 0.6056-0.6069). Ensemble of best logistic + GB vs v1: noise.
- Solid: every availability model beats production `gradient-boosting-gridsearch` by ~0.009 Brier and ~0.02 log loss
  with CIs excluding zero everywhere. Production GB is no better than the legacy logistic. The availability features
  carry the gain, not the algorithm.
- Optional after the opener: a plain uncalibrated `LogisticRegression(C~0.01-0.03)` on the avail or avail+rest set.
  Its extreme-prediction share is 1.8% vs 5.95% for v1's isotonic step; v1's tails are not visibly harmful (0.0-0.1 bin
  predicted 0.063 vs actual 0.080; 0.9-1.0 bin predicted 0.920 vs actual 0.911).

## Leaderboard split (train before 2025-02-25, test n=1,596)
| model | acc | log loss | Brier | AUC | ECE | extreme |
|---|---|---|---|---|---|---|
| lr_iso avail+rest (tuned) | .6861 | .5832 | .1999 | .7528 | .0196 | 2.9% |
| **v1 (repro, live)** | .6823 | .5835 | .1998 | .7529 | .0172 | 6.0% |
| lr avail (tuned, C=.03) | .6855 | .5839 | .1998 | .7527 | .0222 | 1.8% |
| lr avail+rest (tuned, C=.01) | .6867 | .5842 | .2000 | .7521 | .0193 | 1.8% |
| ENS(lr+gb) avail | .6880 | .5859 | .2003 | .7529 | .0216 | 0.1% |
| rf avail | .6880 | .5876 | .2009 | .7517 | .0200 | 0.8% |
| xgb avail | .6898 | .5881 | .2012 | .7500 | .0185 | 0 |
| gb avail (tuned) | .6861 | .5903 | .2019 | .7501 | .0241 | 0 |
| lr baseline (tuned) | .6792 | .6047 | .2084 | .7297 | .0247 | 0.8% |
| **production GB (repro)** | .6811 | .6073 | .2093 | .7296 | .0365 | 0 |
| legacy calibrated logistic (repro) | .6798 | .6320 | .2089 | .7296 | .0305 | 4.0% |

## Walk-forward by season, pooled 2022-23 to 2025-26 (n=4,910)
| model | acc | log loss | Brier | AUC | ECE |
|---|---|---|---|---|---|
| lr avail+rest (tuned) | .6668 | .6056 | .2094 | .7232 | .0111 |
| lr avail (tuned) | .6625 | .6069 | .2100 | .7212 | .0141 |
| ENS(lr+gb) avail+rest | .6678 | .6071 | .2099 | .7227 | .0182 |
| **v1 (repro, live)** | .6633 | .6085 | .2104 | .7205 | .0115 |
| rf avail | .6668 | .6087 | .2106 | .7206 | .0141 |
| xgb avail | .6658 | .6113 | .2116 | .7182 | .0163 |
| gb avail (tuned) | .6705 | .6117 | .2117 | .7189 | .0221 |
| **production GB (repro)** | .6473 | .6262 | .2182 | .6971 | .0150 |

Per-season Brier (2022-23 / 2023-24 / 2024-25 / 2025-26): v1 .2239/.2094/.2059/.2024; tuned lr avail+rest
.2224/.2076/.2051/.2026; production GB .2300/.2147/.2168/.2114.

## Live-like scoring and the 06:00 variant
Models trained on realized-absence features (as production trains), scored with features from the archived injury
report at tip minus 60 minutes, or from the report available at 06:00 ET.

| walk-forward pooled, tip-60 subset (n=4,801) | acc | log loss | Brier |
|---|---|---|---|
| production GB (no availability) | .6488 | .6258 | .2180 |
| v1, realized absences (hindsight) | .6640 | .6073 | .2100 |
| v1, report at tip-60 | .6672 | .6069 | .2097 |
| v1, report at 06:00 | .6561 | .6181 | .2146 |
| tuned lr avail, tip-60 | .6715 | .6049 | .2091 |

- The availability gain holds with only pre-game information. The 06:00 report costs ~0.005 Brier against tip-60 but
  still beats no availability. This supports pricing games ~60-75 minutes before tip (the current schedule).
- v1 vs production GB under tip-60 reports: Brier -0.0110 [-0.0152, -0.0068] (leaderboard), -0.0083 [-0.0108, -0.0059]
  (walk-forward).
- Report features score slightly better than realized absences; unexplained, not verified.

## Sanity checks
- First 3 weeks of each season (615 games): every model is worse (production GB Brier 0.2228 vs 0.2176; v1 0.2174 vs
  0.2094; ECE 0.04-0.06). Availability still helps (tuned lr vs its baseline: Brier -0.0049 [-0.0085, -0.0014]
  realized, -0.0083 [-0.0133, -0.0032] with tip-60 reports). No model has a clear early-season edge over v1; smaller
  stakes in the first weeks look reasonable but were not tested.
- Coefficient signs: `rating_expected_diff` +0.363, `ELO_DIFF` +0.169, `minutes_lost_diff` -0.220, `value_out_diff`
  -0.032, but `home_star_out` +0.014 and `away_star_out` -0.050 (wrong sign in isolation; v1 shows the same). Cause:
  collinearity with the other availability features (r 0.5-0.7). Net behaviour is correct: home star out lowers the
  predicted home win probability from 0.571 to 0.498 on the test set (actual 0.471); away star out 0.534 -> 0.578
  (actual 0.531 -> 0.586). **Do not use the isolated star-out flags as a what-if lever** (flipping `home_star_out`
  alone moves p by +0.004).
- Calibration of v1 on the leaderboard split is good (ECE 0.017; 0.0115 walk-forward). Production GB has gaps of
  -0.074 (0.2-0.3 bin) and +0.046 (0.5-0.6 bin).

## Caveats
- One third of a season of test data: Brier standard error ~0.001; differences below that are noise. The bootstrap
  resamples games independently, so true uncertainty is somewhat wider.
- Injury-report coverage: tip-60 covers 1,566/1,596 (leaderboard) and 4,801/4,910 (walk-forward); the 06:00 subset is
  906/1,596 and 2,990/4,910 and not random, so metrics across subsets are not directly comparable.
- Feature leakage was not re-audited; the "rapm" training features use realized absences for the game itself (the
  train/serve mismatch above).
- The gradient-boosting grid was lighter than planned (24 combos x 4 tree counts); selected configs sit at the
  low-capacity end, so a bigger grid is unlikely to change the conclusion.
- Not verified: reproduced numbers line by line against the leaderboard CSV, and the report-vs-realized oddity.

## Reproduction
Scratch dir `C:\Users\noel9\.claude\jobs\7b5ff8e4\tmp\tuning` (deleted with the job): `code\run_jobs.py all` (resumable,
writes `out\jobs2\*.pkl`), `code\analyze.py` (writes `out\analysis.md/json`), `code\signcheck.py`. Tuned research
artifacts: `out\models_lb\*.joblib` (dicts of `fitted`, ordered `features`, `meta`); wired into nothing.
