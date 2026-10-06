# State (updated Oct 6, 2026, end of Checkpoint D)

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
- **`/api/live-scores` does not exist on any branch** (it's in the contract and design docs, and the old frontend called it too). On the live
  site, scores only update from the slate's own status, and while games are live the "Live scores are down" banner appears after 5 minutes.
  Building it (a cached proxy to the NBA scoreboard) is a new backend item; it needs his OK.
- The `model_runs.training` migration still needs his yes/no (the file is in supabase/migrations).
- NBA logo trademark sign-off before anything goes public.
- Merging to main / production deploy: only on his explicit approval.

## If Noel asks for more
Follow-ups that aren't built: a date picker for Past nights (ruling 10), B5 factor build (optional), `/api/live-scores` (above).
