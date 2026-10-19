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
  - `NBA-Predictor-Predict` (new) every 30 min 10:00-22:00 -> `daily_workflow.py --stage predict`: injury snapshot, then
    prices each game that tips within 120 min and has no prediction (workflow_log kind `predict`, picks SMS). A run with
    nothing to price is silent (no SMS, no log row, no odds request). Never prices a started game.
  - `NBA-Predictor-Injury-Snapshot` every 30 min 11:00-23:00 (unchanged).

## Why the schedule changed
Tomorrow's slate is BOS@DET 3:00 PM, PHI@NYK 7:00 PM, OKC@SAS 9:30 PM ET. Teams submit injury reports during the day (the
Oct 19 11:15 AM report lists all three games as "NOT YET SUBMITTED"), so a 06:00 prediction would treat unreported players
as available, and one evening run would miss the 3 PM game. Each game is now priced ~1.5-2 h before its tip.

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
- [ ] ~13:00 BOS@DET prediction row (tip 3:00 PM), `model_name = lr-calibrated-availability-v1`, prob_range_low/high set
- [ ] ~17:00 PHI@NYK; ~19:30 OKC@SAS; each with a picks SMS; `book_odds` rows for each
- [ ] 3 predictions total for the slate; no `skip_reason` unless an odds gap
- [ ] `injury_snapshot.log` shows rows with matched players once teams submit
- [ ] If anything fails: `logs\workflow.log`; to fall back, delete `NBA_PRODUCTION_MODEL` from `.env`

## Open
- Model tuning / re-evaluation is running offline (scratch dir, nothing published); results in the job report.
- Dashboard (`/api/injuries`) still shows `migration_pending` (migration 0100 intentionally not applied).
