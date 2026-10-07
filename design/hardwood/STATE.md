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

## Open items for Noel
- NBA logo trademark sign-off before production goes public.
- Pipeline risks (from the pipeline-engineer audit, not built): predict-time rest-days/rolling-stat mismatch with training,
  no season-start Elo reversion at predict time, silent failures in `collect.py`/`odds.py`/`scheduler\run_daily.bat`.

## If Noel asks for more
Follow-ups that aren't built: a date picker for Past nights (ruling 10), B5 factor build (optional).
