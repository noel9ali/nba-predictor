# State (updated Oct 7, 2026, after the live-scores + model release)

## Release Oct 7, 2026: DONE
- Merged to main (`8b86839`) after sonnet `/security-review` of both branches (no confirmed findings) and a Playwright-CLI check
  (7 checks, 1440 + 400 px). Production deployment `dpl_9SciBvJPCh6byYm9HPPudMh4xK9v` (READY, https://nba-predictor-tau.vercel.app);
  prod re-check passed, no runtime errors. Pushes to main do NOT auto-deploy: create the production deployment from the main SHA.
- Model: gradient boosting is the default production model; retrained Oct 7 (log loss 0.6075, #1 of 6), artifacts committed in
  `9e0e647`. Old `.pkl` files and Noel's earlier uncommitted retrain files are in `data/pre_gb_backup/` (untracked).
- Production is behind Vercel login for all deployments (project SSO protection "all"), pending the logo sign-off.

## `/api/live-scores` (shipped)
- Upstream `todaysScoreboard_00.json`: `cdn.nba.com` answers 403 (Akamai) from the laptop and from Vercel; the S3 origin
  `nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/liveData/scoreboard/…` serves the same JSON. The proxy tries the CDN, then
  the origin, and remembers which answered. The origin is undocumented, so watch for `stale:true` / 503s if it moves.
- Code: `src/live_scores.py` (fetch, mapping, 15 s single-flight cache) + the route in `app.py`; tests in `tests/test_api_v2.py`.
- Behaviour: `?date=` validated (400); today/yesterday from the feed; other dates from `predictions` or `games:[]`; upstream down →
  last good snapshot `stale:true`, or 503 when nothing is cached. No `migration_pending` in this envelope (contract).

## Checkpoints
| Checkpoint | Scope | Status |
|---|---|---|
| A | Shell, ambient layer, Tonight static (sample) | DONE, reported |
| B | Live polling, drawer, ribbon, season scrolly, backend B1–B4 + B7 | DONE, reported, preview sent |
| C | Model page | DONE, reported |
| D | Tests green, cleanup, final preview | DONE. Report sent to Noel with the preview link |

Branch `hardwood-build` (pushed): `d28e07a` A+B, `6bee75c` C, `bbdc0ec` docs, then the D commit (see `git log`).
Preview (Vercel login required): https://nba-predictor-git-hardwood-build-nubber.vercel.app/?sample=1

## Checkpoint D results
- `tests/e2e/validate.mjs` (handoff suite; ADVANCE uses `window.__sampleFeed.step()`; check 6b amended per ruling 8 to
  "layout equal, visual lift 3–5px"): **39/39 PASS** at 400/768/1440.
- Python `scripts/run_offline_tests.py`: **267 OK**. `test_dashboard_static.py` and `test_dashboard_page.py` were rewritten for the new
  pages, and `test_security.py` static paths updated.
- `node --test tests/js/pure.test.mjs`: 5/5.
- XSS harness (`scripts/xss_harness.py 5058` plus a browser visit to /, all 6 drawers, a past night and /model): **0 payloads fired**; hostile text
  renders as text.
- Reduced motion: no `.pre`, all stamps visible, 0 running animations; the hero still switches and ch2 is static `split`.
- Lighthouse (local, sample mode):

  | Page | Desktop | Mobile |
  |---|---|---|
  | Tonight | perf 97, a11y 100 | perf ~77, a11y 100 |
  | Model | perf 99, a11y 100 | perf 86, a11y 100 |

  The specs require Tonight desktop and Model mobile+desktop, and both are met. The rest of Tonight's mobile score is font-swap re-wrap under throttling.
  Layout-shift fixes: `#tonight.loading` reserves the courts, grid and h1; the kicker min-height; the loading board shows real labels; `.top__r`
  min-height on phones; the hero court slot reserved; `modulepreload` links for the module graph.
- Old dashboard files deleted (`dashboard.css`, `favicon.svg`, 13 old js modules, barlow fonts). `/legacy` still uses `static/app.js`
  and `static/style.css`; KEEP both.

## Gate M: v2 schema ON (Oct 7, 2026)
- `NBA_SCHEMA_V2=true` in Vercel production + preview (redeployed `dpl_7domr23jUbVDkbtLWqYyicA1yUsx`) and the laptop `.env`.
  `model_runs` holds the Oct 7 GB run (published with `--publish-only`). `/api/model` now shows gradient boosting, the training
  block and the leaderboard (`migration_pending:false`); `/api/game/<id>` works again (it had filtered the text `game_id` with an int).
- Rollback: set both Vercel vars to `false`, redeploy production from the main SHA, remove the `.env` line.
- Settled 2025-26 rows predate v2, so their v2-only fields (tip time, book grid, bankroll at bet, scores) stay null; new nights
  fill them. `gate_m_backup` schema holds the pre-migration copy of the tables.

## Visual audit fixes: DEPLOYED (Oct 10, 2026)
- `fix/hardwood-audit` (35 of 35 findings from `design/hardwood/audit/AUDIT-2026-10-07.md`) merged to main as `0638bc4`
  after a sonnet security review (PASS) and 291/291 offline Python tests. Production deployment
  `dpl_6fNLWt2Aguvfho4NzC9nJtfCdnB8` (from the main SHA, READY, aliased). Report: `design/hardwood/audit/FIXES-2026-10-07.md`.

## Diagnostic fixes: DEPLOYED (Oct 25, 2026)
- PR #7 merged to main as `ce2fb81`; production `dpl_2GND8VRE4TSufXHckew8nSm98VrB` (READY, aliased). 544 offline tests, security review clean.
- Cause of Oct 22-25 missed runs: laptop on battery with wake timers off on battery (RTCWAKE DC=0), then Modern Standby has no network.
  Wake timers on battery are now enabled locally; still plug in on game days. See `scheduler/README_scheduler.md` ("Power").
- Predict-time rest days and rolling form now use the team's real recent games (`features.role_form`, `features.rest_days_before`,
  rest capped at 7, same cap in training). The old per-role lookup gave ~190 rest days early season and the 69-92% "edges".
- Live model is gradient boosting again (`NBA_PRODUCTION_MODEL` removed from the local `.env`; check the Vercel env too). The
  selected model is refit on all completed games after holdout evaluation; each prediction stores `model_name`. Checked Oct 25:
  the Vercel project does not set `NBA_PRODUCTION_MODEL` (only `NBA_SCHEMA_V2`, `FLASK_SECRET_KEY`, `SUPABASE_*`).
- Finished games only in collect/Elo/features (in-progress rows were read as home losses); neutral-site games get a home row.
- Odds: started games and reversed home/away pairs are never used; the next game of a repeated pair wins.
- Bets: `MIN_EDGE` 3% and `NIGHTLY_STAKE_CAP` 15% of bankroll per slate date (first come, first served). Audit columns
  (edge, implied_prob, bookmaker, tip_time_utc, bankroll_at_bet, predicted_at) are now written.
- Settlement writes final scores; the 193 settled rows were backfilled from `games` on Oct 25.
- Reporting: results settled late are pushed/emailed per date; the morning stage lists games that finished with no pick (ntfy +
  email) and flags a morning run that starts after 10:00 ("morning run late" in `workflow_log.notes`).
- Lost for good: Oct 22 and Oct 24 (no picks), most of Oct 20-21 and Oct 25.

## Open items for Noel
- NBA logo trademark sign-off before production goes public.
- The Task Scheduler history log is on (enabled from an admin shell, Oct 25), so the next skipped run can be diagnosed from
  Event Viewer > Task Scheduler > Operational. The registered `NBA-Predictor-Daily` task description still says "SMS"
  (re-register to refresh it).
- If 6 AM must be dependable, move the scheduler to an always-on host.
- Still open from the pipeline audit: no season-start Elo reversion check at predict time beyond `revert_stale_ratings`, silent
  failures in `odds.py`/`scheduler\run_daily.bat`. Supabase tables `team_availability_features`, `player_minutes_projection`,
  `injury_snapshots` 404 in production until the player-data migrations are applied.

## If Noel asks for more
Follow-ups that aren't built: a date picker for Past nights (ruling 10), B5 factor build (optional).
