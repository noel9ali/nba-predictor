# Hardwood Tickets build: progress log (resume from here)

Branch `hardwood-build`, worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\hardwood-build` (off main 76e5dd3).
Handoff (read-only, untracked on main): `C:\Users\noel9\Desktop\nba-predictor\handoff\`.
Plan: `C:\Users\noel9\.claude\plans\pasted-content-id-8723-act-as-virtual-gosling.md` (approved).
Python: `C:\Users\noel9\Desktop\nba-predictor\venv\Scripts\python.exe` (venv lives in main checkout; pytest absent → use `-m unittest`).
Playwright: installed in the session scratchpad `scratchpad/pw` (not in repo).
Rules: no commits to main, no merge/push main, no `vercel deploy --prod`, no live Supabase writes/migrations, never print .env. Ask Noel first.
Noel asked (Oct 6): be token-frugal, lean subagent briefs, keep this log current.

## Checkpoints
- A. Shell + ambient + Tonight (static, sample) → screenshots 400/1440 → STOP for Noel.
- B. Live polling, drawer, ribbon, season scrolly, backend B1–B4/B7 (B2 migration file only).
- C. Model page → screenshots.
- D. validate.mjs (BASE=http://127.0.0.1:5057) + Python tests green → Vercel PREVIEW link.

## Done
- Phase 1 backbone (lead): `public/static/css/{fonts,tokens,base,components,ambient,tonight}.css`,
  `public/static/js/{gate,format,reveal,ambient,board,api,shell,state,court,logo}.js`, `public/index.html`,
  fonts + 30 logos copied to `public/static/{fonts,logos}`.
- S1 (sample data): B1–B4 stubs in `scripts/build_sample_data.py` (`stub_model_extras`, `featured_pick`,
  `settled_featured_game`), contract `tests/contract_shapes.py` (Maybe(), FEATURED_PICK), replay files rebuilt
  per live-feed.md §3.8 (end of night +117.01, bets 4–1). `tests.test_sample_data` + `tests.test_api_v2` green.
  Regenerate: `python scripts/build_sample_data.py`. LF endings vs autocrlf → git status noisy, content fine.
- Lead: `tonight.js`, `tonight/glance.js`, `tonight/ribbon.js`, placeholder `tonight/season.js` (board only).

- S2 done: `tonight/tickets.js`, `tonight/toolbar.js` (+ ticket CSS at end of components.css).
- S3 done: `tonight/drawer.js`, `tonight/toasts.js` (+ drawer/toast CSS at end of tonight.css).
- B7 done: Flask `/model` + `/model.html` route in app.py; vercel.json rewrite + header blocks.
- Lead: shared `calibration-chart.js` written (not yet wired).
- CHECKPOINT A reached (Oct 6): Tonight sample mode renders, numbers match spec, 0 console/CSP errors, no
  overflow at 400/1440, drawer deep link works. Screens: scratchpad `pw/A-tonight-{400,1440}.png`, `A-drawer-1440.png`.
  Waiting for Noel's OK before phase 3.

- Phase 3 (Oct 6, after Noel's OK): full `tonight/season.js` (board, bankroll scrolly w/ ruling-9 label
  collision fix, W/L, calibration card + facts) done and verified: replay hook ×10 → +$117.01, 4–1, Final 6,
  ≤3 toasts, step 3 `.tn`. All sample scenes + past night + invalid date: 0 errors.
- Backend B1–B4 delegated to a subagent (app.py /api/model extras, elo consts + parity test, training w/
  defensive read + migration FILE only, /api/featured-pick, tests in test_api_v2).
- Preview deploy: `npx vercel deploy` → "Not authorized" (CLI login expired). Needs Noel: `! npx vercel login`
  or OK to push branch `hardwood-build` (git integration makes a preview). `.vercel/project.json` copied into worktree.

## How to run locally
- Server: `cd worktree; SUPABASE_URL=http://127.0.0.1:9 SUPABASE_SECRET_KEY=offline FLASK_PORT=5057 <venv python> app.py`
- Smoke: `node scratchpad/pw/smoke.mjs "<url>" <width> <out.png|-> [--reduced] [--full] [--through] [--scroll=sel] [--eval=js]`

## Next
1. Phase 3: full `tonight/season.js` (replace placeholder) (bankroll scrolly, W/L, calibration card via shared `calibration-chart.js`);
   backend B7 (/model route + vercel.json), B1, B3 (constants in app.py + parity test vs src/elo.py), B4
   (/api/featured-pick), B2 (src/model*.py + migration file only, app.py reads defensively).
3. Model page (model.html, model.js, model/*.js).
4. Tests: node --test units, replace old dashboard static tests, tests/e2e/validate.mjs (ADVANCE → `window.__sampleFeed.step()`).
5. Remove old dashboard files in public/static (app.js, dashboard.css, style.css, js/{charts,components,dom,explainers,games,keys,live,main,performance,teams,toast,topbar}.js, barlow fonts) after green.

## Decisions / notes
- Sample hook `window.__sampleFeed.step()` (sample mode only) steps live-replay-1..6.
- Calibration card shows 68.1% (ruling 6). Featured pick sample pinned to 0195 (SAC).
- B3 constants must live in app.py: vercel.json excludeFiles drops src/elo.py from the function.
- B2 needs `model_runs.training jsonb` → migration file only; ask Noel before applying.
