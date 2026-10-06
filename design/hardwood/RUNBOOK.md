# Runbook

Paths:
- WT = `C:\Users\noel9\Desktop\nba-predictor.worktrees\hardwood-build` (Git Bash: `/c/Users/noel9/Desktop/nba-predictor.worktrees/hardwood-build`)
- PY = `C:\Users\noel9\Desktop\nba-predictor\venv\Scripts\python.exe` (the venv lives in the main checkout; pytest is absent, so use unittest)
- PW = the Playwright scratch dir `C:\Users\noel9\AppData\Local\Temp\claude\C--Users-noel9-Desktop-nba-predictor\5a9fe043-166e-4831-8206-d75713553329\scratchpad\pw`
  (`npm i playwright` and `npx playwright install chromium` are done there). If it's gone, recreate it in your own scratchpad:
  `npm init -y && npm i playwright@1 && npx playwright install chromium`, then re-create `smoke.mjs` and `shots.mjs` (below).

## Local server (offline DB)
```
cd WT; SUPABASE_URL=http://127.0.0.1:9 SUPABASE_SECRET_KEY=offline FLASK_PORT=5057 PY app.py   # run in background
```
Sample pages: `http://127.0.0.1:5057/?sample=1`, `…&scene=replay|before|failed|offseason|nobets|stale|feeddown|edges|final`,
`…&date=2026-11-16`, `/model?sample=1`.

## Checks
- `node PW/smoke.mjs "<url>" <width> <out.png|-> [--reduced] [--full] [--through] [--scroll=<sel>] [--eval=<js expr>]`:
  prints overflow plus console/CSP errors and saves a screenshot. `--through` scrolls the page first so reveals fire.
- `node PW/shots.mjs "<url>" <width> <prefix> "<sel>:<frac>" …`: takes viewport shots at elements.
- Replay check: `--eval="(async()=>{for(let i=0;i<10;i++){await window.__sampleFeed.step();await new Promise(r=>setTimeout(r,150))}await new Promise(r=>setTimeout(r,400));return document.querySelector('[data-testid=settled]').textContent})()"` should give `+$117.01`.
  Read the DOM only after a frame; renders are rAF-coalesced.
- Unit tests: `cd WT && node --test tests/js/pure.test.mjs` (passing the directory doesn't work on Windows).
- Python: `cd WT && PY scripts/run_offline_tests.py` (whole suite, network blocked), or `PY -m unittest tests.test_api_v2 tests.test_sample_data tests.test_security`.
- Sample data: `cd WT && PY scripts/build_sample_data.py`. It must regenerate identical content. Git shows CRLF noise because autocrlf=true;
  compare with `git diff --ignore-cr-at-eol`.
- Acceptance suite: see STATE.md D1 (`tests/e2e/validate.mjs`, `BASE=http://127.0.0.1:5057`). Run it from PW so `playwright` resolves, and use a timeout.
- XSS: `cd WT && PY scripts/xss_harness.py 5058` (background), then open `http://127.0.0.1:5058/` (and a drawer, `/model`,
  `/?date=2026-11-16`) with a console listener. Any `XSS-FIRED-n` log is a failure.

## Git and preview
- Commit on `hardwood-build` only, ending messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  `git push origin hardwood-build`.
- Preview: Vercel connector `create_deployment` with teamId `team_ZZVozzenFJ4lE1J2JnMTJOH7`, requestBody
  `{"name":"nba-predictor","project":"prj_3vfO80gx4wYbA2rXpmOQJ27CwhM3","gitSource":{"type":"github","org":"noel9ali","repo":"nba-predictor","ref":"hardwood-build","sha":"<full sha>"}}`
  (no target, so it's a preview). Poll `get_deployment` until READY (~30 s), then check with `web_fetch_vercel_url` (protection bypass).
  Stable alias: https://nba-predictor-git-hardwood-build-nubber.vercel.app
- NEVER use target production, `--prod`, or push to main.
