# Learned play probabilities vs the hand-set status table (offline study, Oct 19 2026)

Proposal only: `config.P_PLAY_SOURCE` defaults to `"status_table"` (today's behaviour). Code: `src/pplay.py`,
`scripts/fit_pplay_mapping.py`, fitted mapping `data/pplay/pplay_mapping_v1.json`, tests `tests/test_pplay.py`.

## Data
Every game with an archived report at or before tip minus 60 minutes (8,038 games, 2019-20 to 2025-26), every rostered
player (same roster rule as `historical_rows`) plus every matched player on the team's newest report: 267,275 roster rows
(287k including listed non-roster players). Label: a `player_games` row with minutes > 0. Features are all known at
tip-60 (status, reason text, EWMA minutes, appearances in the team's previous 10 games, rest, home, report age,
persistence, the team's and player's earlier questionable-play rate, previous-game status). Splits are time ordered.

## What actually happens (share who played; hand table in brackets)
| status | n | played | hand |
|---|---|---|---|
| out | 58,083 | 0.2% | 0.00 |
| doubtful | 1,589 | 2.3% | 0.05 |
| questionable | 10,759 | 49.1% (46.7-51.5% by season) | 0.50 |
| probable | 4,233 | 90.4% | 0.90 |
| available | 3,819 | 76.3% | 1.00 |
| **not on the report (rostered)** | 208,810 | **74.7%** | **1.00** |

* By reason: questionable G League 18.9%, questionable injury/illness 51.7%, injury management 59%; "available" with a
  G League reason 40.5%, with an injury 90.5%; "out" G League 0.7% (every other "out" reason is under 1.2%, most under 0.5%).
* Questionable by base minutes: <5 min 28%, 15-22 min 49%, 30+ min 58%. Questionable by prior game: after "questionable"
  52%, after "out" 56%, unlisted 42%.
* The 15-minute-slot era (from 2025-12-21): questionable 51.7% vs 48.8% before. Not distinguishable.
* **The hand table's one real error is the unlisted 1.0.** Unlisted rostered players with 22+ base minutes play 95-98%, but
  those with 6-15 play 42-56%, and an unlisted player with >=15 base minutes who has played 0 of the team's last 10 games
  plays **6%** (1 of 10: 63%, 5 of 10: 81%, 10 of 10: 98%). Unlisted players with >=15 base minutes DNP 10.4% overall.
  Status and reason matter less than that; the hand table's questionable/probable/doubtful/out values are close.

## Player-level accuracy (time ordered; train before the test window)
Roster rows, leaderboard window (games from 2025-02-25, n=53,435) / 2025-26 (n=41,148), log loss / Brier. The hand table is
clipped to [0.005, 0.995] for log loss (unclipped it is 1.77); Brier is unaffected.

| model | LB log loss | LB Brier | 2025-26 log loss | 2025-26 Brier |
|---|---|---|---|---|
| hand-set table | 1.034 | 0.1980 | 1.067 | 0.2036 |
| status rates re-estimated on train | 0.465 | 0.1543 | 0.472 | 0.1572 |
| status x base-minutes table | 0.372 | 0.1214 | 0.381 | 0.1244 |
| **committed table** (`pplay.py`: + appearances, reason group) | 0.303 | 0.0973 | 0.305 | 0.0978 |
| learned logistic regression (C chosen inside train) | 0.278 | 0.0879 | 0.275 | 0.0867 |
| learned HistGradientBoosting (small, regularized) | 0.257 | 0.0814 | 0.253 | 0.0797 |

On the listed players alone (13,109 / 9,724 rows) the hand table is already decent (log loss 0.207, Brier 0.060 vs the
gradient-boosting model 0.153 / 0.050); on questionable players alone the hand 0.5 scores 0.6931 / 0.2500 (a coin flip
by construction) vs 0.635 / 0.222 for the boosted model. Calibration: the hand table's "1.0" bucket (32,242 rows in
2025-26) observed 75.2%; the learned models are within about a percentage point in every decile.

## Game level (what matters)
Production candidate recipe (logistic regression trained on realized absences, C tuned inside each training window),
scored with tip-60 report features built with each p_play source. A = current hand table. Brier difference vs A with a
paired bootstrap by game (2,000 resamples); negative = learned is better.

| variant | leaderboard split (n=1,566) | walk-forward 2022-26 pooled (n=4,801) |
|---|---|---|
| B learned (boosted) for everyone | -0.0011 [-0.0025, +0.0003] | -0.0008 [-0.0014, -0.0002] |
| B learned (logistic regression) | -0.0009 [-0.0021, +0.0003] | -0.0006 [-0.0012, -0.0001] |
| B learned (the committed table) | -0.0009 [-0.0020, +0.0002] | -0.0004 [-0.0009, +0.0001] |
| C learned for listed players only | -0.0000 [-0.0004, +0.0004] | -0.0003 [-0.0005, -0.0001] |
| D hand for listed + learned for unlisted | -0.0011 [-0.0023, +0.0002] | -0.0005 [-0.0011, +0.0001] |
| F candidate also TRAINED on learned-p features | -0.0007 [-0.0022, +0.0008] | -0.0006 [-0.0013, +0.0001] |

Log loss moves by -0.002 to -0.003 on the boosted version (pooled CI [-0.0034, -0.0006]); accuracy does not move
(-0.0002, CI includes zero). Per walk-forward season the Brier gain is -0.0006, -0.0006, -0.0008, -0.0012 and each
interval includes zero. The first three weeks of each season (602 games): -0.0006 [-0.0028, +0.0018], no gain.
Training on learned-p features adds nothing over scoring with them. For scale: the whole availability block is worth
0.007-0.010 Brier; this is under a tenth of that (0.4% relative).

The gain is almost entirely the unlisted rule (C is ~0, D is about B): stale-minutes players who are not on the report.

## Verdict
**A real improvement at player level (log loss 1.03 -> 0.26-0.30), a negligible one at game level (Brier -0.0004 to
-0.0011, borderline in pooled data and inside the noise per season, and nothing early in the season). Not worth adopting
for the Oct 20 opener.** The change would also move the scenario machinery: unlisted players with p_play between 0.1 and 0.9
would start entering `scenarios.uncertain_players`, which changes the probability ranges and therefore any gate
thresholds; and `current_rosters()` brings offseason signings with no log for the team (the code falls back to the hand
table for them, but the start of a season is exactly where "appearances in the last 10 games" refers to last season).

What adopting would require: (1) set `P_PLAY_SOURCE = "learned_table"` and ship `data/pplay/pplay_mapping_v1.json`;
(2) re-run `scripts/evaluate_availability.py` style evaluation on features built with it and compare ranges and the
gate share (about 25% of games have range > 0.06 today); (3) decide whether to retrain the candidate on learned-p
features (no gain here, so probably not, but then the manifest/feature-set version must still name the p_play source);
(4) refit the mapping at least once a quarter with `scripts/fit_pplay_mapping.py` as reports accumulate (the committed file
is fitted on all data through 2026-04-12, so its own score on that data is not an out-of-sample number: the tables above come
from time-ordered refits); (5) hold the learned unlisted rule back for the first ~10 team games of a season.
