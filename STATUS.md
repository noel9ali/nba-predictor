# STATUS — Mon Oct 19, 2026 (eve of opening night)

## Now live (all verified Oct 19)
- **Supabase** `aopkwfeocvgkzejxjruw`: `beta_flag` (live bankroll row $1,000, 174 predictions + 23 bankroll rows flagged beta) and
  `predict_availability` (= supabase/migrations/20261012000500: predictions.prob_range_low/high + status_changed_after_pred,
  3 empty prediction_* tables, skip_reason check). Nothing else from the Oct 12 set is applied; player data stays in the
  local sqlite mirror (`NBA_PLAYER_STORE` defaults to local).
- **Production checkout** `C:\Users\noel9\Desktop\nba-predictor`: local `main` fast-forwarded to branch `worktree-status-oct19`
  (not pushed to GitHub main). `.env` now has `NBA_PRODUCTION_MODEL=lr-calibrated-availability-v1`
  (delete that line to go back to the gradient-boosting model; it never needs a restart).
- **Vercel**: production deploy of the same SHA (see Deploys below).
- **Scheduler**
  - `NBA-Predictor-Daily` 06:00 ET -> `run_daily.bat` -> `daily_workflow.py --stage morning` (collect, settle yesterday,
    features, results SMS; workflow_log kind `morning`). It no longer predicts.
  - `NBA-Predictor-Predict` (new) every 15 min 10:05-22:05 -> `daily_workflow.py --stage predict`: injury snapshot, then
    prices each game that tips within 75 min and has no prediction, i.e. 60-75 min before tip (workflow_log kind
    `predict`, picks SMS). A tick with nothing to price is silent and cheap: no SMS, no log row, no odds request, no
    Elo/games table reads. Never prices a started game. Odds API capped at 12 calls/day (`data\odds_budget.json`).
  - `NBA-Predictor-Injury-Snapshot` every 30 min 11:00-23:00 (unchanged).

## Why the schedule changed
Tomorrow's slate is BOS@DET 3:00 PM, PHI@NYK 7:00 PM, OKC@SAS 9:30 PM ET. Teams submit injury reports during the day (the
Oct 19 11:15 AM report lists all three games as "NOT YET SUBMITTED"), so a 06:00 prediction would treat unreported players
as available, and one evening run would miss the 3 PM game. Each game is now priced 60-75 min before its tip (the
timing the model was evaluated at: report from tip minus 60 min).

## API budget (per day, 49 ticks)
NBA ScoreboardV3 49 calls; injury PDFs on the NBA CDN 0-3 per snapshot (stops at the first slot already on disk, 0.4 s
apart; ~75 snapshots a day incl. the injury task); Odds API 0 on quiet ticks, 1 credit per priced tick (typically 3-6 a
game day, hard cap 12/day vs 500/month); Supabase 2 small reads per quiet tick, full Elo/games read only when pricing;
Twilio 1 SMS per priced tick. `nba_api` schedule/player lookups are cached 24 h.

## What the model now does
Candidate `lr-calibrated-availability-v1` (calibrated logistic regression: Elo, rolling form, rest + 6 player-availability
features from ratings x minutes x injury status) replaces the gradient-boosting pick/probability. Holdout (1,596 games from
2025-02-25): Brier 0.1998 vs 0.2094, log loss 0.5834 vs 0.6075, AUC 0.753 vs 0.729, ECE 0.016 vs 0.035. Uncertain players
are blended over present/absent scenarios and stored with a probability range; the availability gate stays off.
Rosters for the projection now come from today's `CommonAllPlayers` (not last season's last 20 games).

## Verification done
- Offline suite: 431 tests OK. `scripts/check_availability_ready.py` (read-only, works on copies): candidate verifies,
  rosters for 30/30 teams, ratings for 687 players, 30/30 teams project, end-to-end score ok. Its only FAIL is "0 injury
  rows" - expected until teams submit (reports so far hold only NOT YET SUBMITTED entries).
- Contract/API: earlier checks OK; redeploy checked below.

## Known limits (be aware)
- Injury inputs only exist once teams submit; a game priced with no entries is a "full-strength roster" prediction.
- The 06:00 pipeline still retrains the models each morning (`model.py`) and prints "configured production model
  unavailable, falling back to leaderboard best" because the env var names the candidate: harmless.
- Games that tip within 2 h of the scheduler gap (or before 10:00 ET) are not priced; the 10:00 start covers noon tips.

## Tuesday checklist (Oct 20)
- [ ] ~06:30 workflow_log: `morning` row, status success, SMS received (results only; says picks follow later)
- [ ] ~14:00-14:15 BOS@DET prediction row (tip 3:00 PM), `model_name = lr-calibrated-availability-v1`, prob_range_low/high set
- [ ] ~18:00-18:15 PHI@NYK (7:00 PM); ~20:15-20:30 OKC@SAS (9:30 PM); each with a picks SMS; `book_odds` rows for each
- [ ] 3 predictions total for the slate; no `skip_reason` unless an odds gap
- [ ] `injury_snapshot.log` shows rows with matched players once teams submit
- [ ] If anything fails: `logs\workflow.log`; to fall back, delete `NBA_PRODUCTION_MODEL` from `.env`

## Model tuning (done, offline; see docs/model-tuning-2026-10-19.md)
Keep `lr-calibrated-availability-v1` live. Tuned logistic, GB, RF, xgboost and an ensemble are all within noise of it
(walk-forward: tuned lr 0.0010 Brier better, borderline); all availability models beat the production GB by ~0.009 Brier.
At 06:00 the availability gain shrinks by ~0.005 Brier vs tip-60, which is why games are priced 60-75 min before tip.
Do not use the isolated `home_star_out`/`away_star_out` columns as what-if levers (collinear; wrong sign alone).

## Open
- Dashboard (`/api/injuries`) still shows `migration_pending` (migration 0100 intentionally not applied).
