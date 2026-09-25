# Dashboard build: progress log

Brief: `..\agent-prompts\05-dashboard-build-agent.md` (the approved plan is in `C:\Users\noel9\.claude\plans\pasted-content-id-390e-you-re-building-goofy-castle.md`).
Branch `dashboard-build`, worktree `C:\Users\noel9\Desktop\nba-predictor.worktrees\dashboard-build`. Never merge to `main`, never `vercel deploy --prod`, never push `main` until Noel approves.

## How to resume
1. Read this file, then `design/DESIGN_STATE.md` and the approved canvas boards snapshotted in `design/canvas/` (Nav-Final, Nav-Pipeline, Games, Games-Controls, Games-Transitions, Edge-Hero, Edge-Cards, Edge-Page, Detail-A, Perf-Final). The live canvas is https://claude.ai/code/artifact/a702b1d5-c99f-4bf4-b134-aa7cb93049c2 (read with the Artifact tool).
2. Tests: `venv\Scripts\python scripts\run_offline_tests.py` (network blocked, pipeline spawn guard, dummy env; INC-1). Never run two suites in the same tree at once.
3. Venv: `py -3.12 -m venv venv` + `venv\Scripts\pip install -r requirements.txt`.

## Done
| Step | What | Commit |
|---|---|---|
| 0 | Worktree off main d4fd9b6; excludeFiles fix carried over | a944a26 |
| 0 | Canvas snapshot, this log, hardened offline runner | f11d560 |
| 1 | Read endpoints B5/B6 (`app.py`), `tests/test_api_v2.py`, `tests/contract_shapes.py` | 9845f02 |
| 4 | Sample season: `scripts/build_sample_data.py` → `public/sample/` (real API output over fake tables), `tests/test_sample_data.py` | 7bb3f6c |
| 2 | Serving B9: `/` → `public/index.html`, `/legacy`, `/sample/*`, vercel.json header rules, tests | c0cc115 |
| 3,5,6,7 | UI: shell, Games, drawer, Performance (`public/index.html`, `public/static/{dashboard.css,js/*,fonts/*}`) | aeb899c |

| 8,9 | A11y pass, `tests/test_dashboard_static.py`, `scripts/browser_check.mjs`, `scripts/xss_harness.py` | 827e9be |
| — | Box score: "Probability not recorded" bucket (30 real rows have NULL win probabilities) | 24d1d00 |
| 10 | Branch pushed; private preview deployed and smoke-tested | — |

Suite: 228/228 OK at 24d1d00, both `scripts/run_offline_tests.py` and `venv\Scripts\python -m unittest discover -s tests -v`.
Browser: headless Chrome (CDP) at 1440 and 375 on every sample scene, the XSS harness and the preview (real data): 0 CSP violations, 0 console errors, 0 horizontal overflow, 0 payloads fired; reduced motion drops the flash and cross-fade. Screenshots: `design/build-screens/` (local) and `design/build-screens/preview/` (preview), not committed.

## Preview (private)
- https://nba-predictor-5i4zle96n-nubber.vercel.app (target null = preview; anonymous → 302 SSO).
- Smoke: `/`, `/?sample=1`, static, all new APIs, `/legacy` → 200 with the 5 headers once each; 404 → 404; POST run-workflow → 403; no runtime errors.
- The CDN serves `public/index.html` at `/` (Vercel static Cache-Control), so the excludeFiles fallback isn't needed.

## Next — WAITING FOR NOEL'S REVIEW. Do nothing below until he approves.
After explicit approval: merge `dashboard-build` into `main` with `--no-ff`, run the suite on `main`, SEC-01 scan over `origin/main..main`, push `main`, `npx vercel deploy --prod`, repeat the smoke test on production. Production stays behind Vercel Authentication (his call).

## Local run
`SUPABASE_URL=http://127.0.0.1:9 SUPABASE_SECRET_KEY=local-dummy FLASK_PORT=5057 venv/Scripts/python app.py`, then `http://127.0.0.1:5057/?sample=1&scene=<live|nextup|sofar|final|nobets|before|failed|offseason|stale|feeddown|edges|early|replay>` (add `&view=local` for the Run now popover). The worktree has no dotenv file, so real data is checked on the Vercel preview.

## Decisions / deviations so far
- Pre-Gate M `record`/`l10` are null ("—"): `games` holds only home rows until the re-collect, so computed records would be wrong.
- `/api/slate` adds `offseason` and `last_slate_date`; `no_games` vs `before_predictions` uses "latest prediction within 7 days" until a schedule source exists.
- Pipeline pill shows "status unavailable" while `workflow_log` is missing (not a designed state).
- `/api/predictions` paginates in pandas (season ≤ 1,230 rows) instead of `select_page`.
- Sample mode adds `&scene=` to review every hero/page state.

## Open questions (for Noel)
- Resolved (Noel: "default to what you see best fit"): tonight's sample bets are now all quarter-Kelly capped at 5% (MIA $55.58, NYK $23.46, MIN $41.96, CLE $41.69, SAC $55.58; staked $218.27, final-night net +$47.52 → $1,159.19).
- `vercel curl` created a deployment-protection bypass token on the project while smoke testing; revoke it in Project Settings → Deployment Protection if you don't want it.
