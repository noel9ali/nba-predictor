# State (updated Oct 6, 2026, end of Checkpoint D)

## In progress: `/api/live-scores` (branch `live-scores`, Oct 7, 2026)
Worktree `C:\Users\noel9\Desktop\nba-predictor\.claude\worktrees\live-scores`, off main `b8fe54d`. Noel approved building it.
- Upstream: `todaysScoreboard_00.json`. `cdn.nba.com` answers 403 (Akamai) from the laptop; the S3 origin
  `nba-prod-us-east-1-mediaops-stats.s3.amazonaws.com/NBA/liveData/scoreboard/…` answers 200 with the same JSON. The proxy tries the CDN,
  then the origin, and remembers which one worked. The feed's `scoreboard.gameDate` rolls over in the ET morning.
- Code: `src/live_scores.py` (fetch, mapping, 15 s single-flight cache; not in vercel.json excludeFiles) + the route in `app.py`.
- Behaviour: `?date=` validated (400 otherwise); default today ET. Today/yesterday ask the feed; a date the feed isn't on answers from
  `predictions` (finals with scores, postponed/void as postponed, `source:"slate"`) or `games:[]`, never an error (a DB failure there
  also gives `games:[]`). Upstream down: last good snapshot with `stale:true`; nothing cached and the date is today: 503
  `{"error":"live_scores_unavailable"}` (no-store). Failures are cached for the 15 s window too. Clock: "Q3 4:40", "Half", "OT 1:30",
  "2OT 0:05", "Final", "Final/OT"; an unparseable clock gives the period only. The envelope has no `migration_pending` (contract).
- `scripts/xss_harness.py` now patches `LIVE_SCOREBOARD` with a fake upstream whose status/clock text is hostile (stays offline).
- Results (Oct 7): `run_offline_tests.py` 284 OK (+17 live-scores tests); JS 5/5; e2e `validate.mjs` 39/39; XSS harness 0 fired
  with the live layer merged (ticket 1 "Live · Q3", ticket 2 "Final"), all 6 drawers, a past night, /model; no CSP errors.
  Real feed via local Flask: CDN 403 → origin 200 in 1.8 s cold, 0.08 s cached; LAL@GSW mapped to "Q4 4:15".
- Steps: [x] module + route  [x] tests  [x] offline suite, xss harness, e2e  [x] push + preview check
- Preview (Vercel login required): https://nba-predictor-git-live-scores-nubber.vercel.app (deployment `nba-predictor-deue8k4pb-nubber`,
  commit `75e4ccf`). Checked Oct 7 04:35 UTC: `?date=2026-10-06` 200 with the live feed (`source:"nba-origin"`, so Vercel pdx1 is
  refused by cdn.nba.com too and the origin fallback is what makes it work; LAL@GSW "Q4 0:44"); default date 200 `games:[]` from
  the slate; `?date=2026-02-30` 400 no-store; CSP + security headers on all; repeat hit served by the CDN (`x-vercel-cache: STALE`,
  age 17). Vercel shows browsers `cache-control: public` because its CDN consumes s-maxage/stale-while-revalidate.
- NEXT: Noel's go-ahead to merge `live-scores` into main and deploy production. Nothing merged or deployed to production.

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

## Findings to raise with Noel (in the D report)
- `/api/live-scores`: approved and being built on branch `live-scores` (see the top of this file).
- The `model_runs.training` migration still needs his yes/no (the file is in supabase/migrations).
- NBA logo trademark sign-off before anything goes public.
- Merging to main / production deploy: only on his explicit approval.

## If Noel asks for more
Follow-ups that aren't built: a date picker for Past nights (ruling 10), B5 factor build (optional), `/api/live-scores` (above).
