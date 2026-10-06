# State (updated Oct 6, 2026, end of Checkpoint C)

## Checkpoints
| Checkpoint | Scope | Status |
|---|---|---|
| A | Shell, ambient layer, Tonight static (sample) | DONE, reported |
| B | Live polling, drawer, ribbon, season scrolly, backend B1–B4 + B7 | DONE, reported, preview sent |
| C | Model page | DONE, reported (preview refreshed) |
| D | Tests green, cleanup, final preview | NEXT. Noel said "go ahead continuing the run" |

Commits on `hardwood-build` (pushed to origin): `d28e07a` (A+B), `6bee75c` (C). Base: main `76e5dd3`.
Preview (Vercel login required, SSO protection on): https://nba-predictor-git-hardwood-build-nubber.vercel.app/?sample=1
Last preview deployment: `dpl_2MFZPpJPsGZRsF3MZZqztL2vVD5d` (commit 6bee75c).

## Verified so far
- Tonight (`/?sample=1`): every acceptance number matches. Headline, board, 6 court rows matching the baseline,
  6 tickets with stamps, drawer deep link `#g0022600190`, ribbon. Replay hook ×10 gives +$117.01, 4–1, Final 6,
  ≤3 toasts, `.tn` at step 3. Every scene (before/failed/offseason/nobets/stale/feeddown/edges/final), the past night
  `&date=2026-11-16` and `&date=banana` all show 0 console/CSP errors. No overflow at 400 or 1440.
- Model (`/model?sample=1`): 6 chapters numbered 1–6, footer in ET, 0 errors, no overflow at 400/1440, all
  `[data-reveal]` get `.in`, one h1. The hero matches baseline `model-1440-claim-model.png`.
- `node --test tests/js/pure.test.mjs`: 5/5 pass.
- Python: `scripts/run_offline_tests.py` gives 263 tests and 4 failures, ALL old-dashboard tests (see D2).

## Checkpoint D: remaining steps (do in order)
1. **validate.mjs:** copy `handoff/test-results/validate.mjs` to `tests/e2e/validate.mjs`. Change ONLY `ADVANCE()` to
   `const ADVANCE = async (page, n, gap = 120) => { for (let i = 0; i < n; i++) { await page.evaluate(() => window.__sampleFeed.step()); await page.waitForTimeout(gap); } };`
   (`window.__sampleFeed` exists only with `?sample=1`). Run it from the scratchpad Playwright dir (see RUNBOOK) with
   `BASE=http://127.0.0.1:5057 OUT=<scratch dir>` and a timeout. Fix the build until green.
   Watch: T-13 (bstep__in top vs bcard top + 40 at 1440), M-3/M-4 (court offsetTop equal in both states), M-6 (no running
   animations in `.gfx`), G-3 (reduced motion: nothing running, no `.pre`, every `[data-reveal]` `.in`).
2. **Old dashboard tests:** rewrite them for the new pages.
   - `tests/test_dashboard_static.py`: no inline script/style, no `style=` in public HTML or JS template strings, same-origin
     resources, fonts self-hosted, module entry points `tonight.js`/`model.js`, live region on `.toasts`, innerHTML only
     with escaped strings (allowlist the files that use `esc()`), and no secrets.
   - `tests/test_dashboard_page.py`: `/` serves the new index.html, `/model` and `/model.html` serve model.html with the CSP
     headers, `/legacy` still works, `/sample/*.json` is served.
   - Leave `tests/test_frontend.py` alone if it still passes (it tests `/legacy`).
3. **XSS:** run `scripts/xss_harness.py 5058` (real API path with hostile strings) and load `/`, a drawer, `/model`,
   `/?date=2026-11-16` with a console listener. 0 `XSS-FIRED` logs allowed. See RUNBOOK.
4. **Reduced-motion pass:** the smoke script with `--reduced` on both pages. Check no `.pre`, stamps visible, and that M1
   still switches.
5. **Delete old dashboard files** once green: `public/static/{app.js,dashboard.css,style.css,favicon.svg?}` (check
   `templates/index.html`, which `/legacy` uses, before deleting anything it references) and
   `public/static/js/{charts,components,dom,drawer,explainers,games,keys,live,main,performance,teams,toast,topbar}.js`, plus the
   barlow font files and `OFL.txt`/`OFL-BarlowCondensed.txt` if nothing references them. Grep before each delete.
6. **Lighthouse** (optional if slow): accessibility ≥95, performance ≥85 on both pages.
7. Commit, push the branch, create a preview deployment (RUNBOOK), verify `/` and `/model` respond 200 with CSP, then
   report Checkpoint D to Noel with the preview link.

## Open questions for Noel (asked, not yet answered)
- Apply the `model_runs.training` migration (`supabase/migrations/20261006000100_model_runs_training.sql`) to live
  Supabase? Until then the live `/api/model` omits `training` and flags `migration_pending`, so chapter 2 shows its
  fallback and the nav shows the "pending a database update" note. Do NOT apply it without a yes.
- NBA logos are trademarks: get sign-off before anything goes public (previews are protected).
