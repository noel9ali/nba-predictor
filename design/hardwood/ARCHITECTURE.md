# Architecture (what exists, who calls what)

## Pages
- `public/index.html`: Tonight, also Past nights via `?date=`. Static shell with ambient SVG, header, ribbon, three sections, drawer and
  toasts mounts. Entry: `static/js/tonight.js`.
- `public/model.html`: The model. Hero `.claim` plus six `section.chapter#ch1..ch6` (hidden until rendered) and
  `[data-body]` / `[data-lede]` slots. Entry: `static/js/model.js`.
- Both load `gate.js` (classic, blocking; sets `html.js` when IntersectionObserver exists and motion isn't reduced).
- CSS order: fonts, tokens, base, components, tonight|model, ambient.

## Shared modules (`public/static/js/`)
| File | Exports / role |
|---|---|
| `format.js` | `fmt` (money/pct/pts/odds/time/date/payout/until), `esc`, `pct1`, `fmtDate`, `wl`, `seasonOf`, `dateET`, word helpers, constants (KELLY_FRACTION, MAX_STAKE, FEATURE_COUNT=16, ELO_DEFAULTS, TEAM_COLORS, MODEL_LABELS), `teamParts`. Node-safe. |
| `api.js` | `api.{slate, liveScores(date,pollIndex), gameDetail, performance(season), model, featuredPick, workflowStatus}`. Sample mode reads `/sample/<name>.json`. `SCENES` maps scenes to slate suffix, live files and clock. `onEnvelope(fn)` (shell uses it for migration_pending), `sampleReplayStep()`, `sampleQuery()`. 10 s timeout. |
| `state.js` | Tonight engine: `init`, `on(fn)` (change batches tip/score/clock/final/feed/tick/slate/slate-error), `store`, `summary()`, `nextUp()`, `visible()`, `counts()`, filters/sorts, `stamped`/`revealed` Sets, pure helpers (`normalize`, `applyLive`, `summarize`, …). Polls every 30 s, silent first merge, feed health on `html[data-feed]`. **Sample-only test hook:** `window.__sampleFeed.step()` loads the next live-replay-1..6. |
| `shell.js` | `initShell({page,…})`, `setPageDate(slate)`, `setMigrationPending`. Tab hrefs carry the sample query, aria-current, status pill. |
| `reveal.js` | `motionOn`, `reduceMotion`, `watch(el,cb,opts)` one-shot IntersectionObserver, `observeReveals()` (`[data-reveal]` gets `.in` at 30%), `onScrollFrame(fn)`, `replay(el,cls)`. |
| `court.js` | `courtGeometry`, `glanceCourt`, `countUp`, `claimCourt`/`updateClaimCourt`, `compareCourt`/`updateCompareCourt`, `stepCourt`. |
| `board.js` | `renderBoard(dl, cells)` (in-place dd updates), `signCls`. |
| `logo.js` | `logo(tri, cls, size)`: an img, or a team-colour chip fallback. |
| `calibration-chart.js` | `renderCalibration(host, buckets, {variant:'card'|'chapter'})`, `bucketLabel`. |
| `ambient.js` | `initAmbient()` court parallax. |

## Tonight (`static/js/tonight/`)
`tonight.js` coalesces `state.on` batches into one rAF render. On `slate` it calls renderLede, renderCourts, mountToolbar/
updateToolbar, renderGrid, mountRibbon/updateRibbon, setPageDate and seasonOnBatch, plus openFromHash and initToasts the first
time. It sets `html[data-ready="true"]`.
- `glance.js`: `renderLede(summary)`, `renderCourts(onOpen)`, `updateCourtStates()`.
- `tickets.js` (S2): `initTickets({onOpen})`, `renderGrid({replay})`, `updateTicket`, `ticketsOnBatch(changes)` (also
  updates the toolbar), `landStamp`. `toolbar.js`: `mountToolbar({renderGrid})`, `updateToolbar`, `showAllGames`.
- `drawer.js` (S3): `initDrawer`, `openDetail(id, opener)`, `closeDrawer`, `openFromHash`. `toasts.js`: `initToasts`, `toast`.
- `ribbon.js`: `mountRibbon`, `updateRibbon(summary)`.
- `season.js`: `mountSeason(perf)`, `seasonOnBatch(batch)`, `mountModelCard(model)`, `seasonError(retry)`, `modelError(retry)`.

## Model (`static/js/model/`)
`model.js` fetches model, performance?season=all and featured-pick→game in parallel. It renders chapters as data lands
(`show(section, ok)` and `numberChapters()`), shows an error panel with retries if /api/model fails, writes the footer
(ET) and sets `html[data-ready]`.
- `claim.js`: `initClaim(model)` (M1/M2; flips at 30%).
- `alltime.js` (S4): `initAlltime(section,{model,perfAll})` → `{setModel}` or null.
- `weights.js`: `initWeights(section, model)` → bool.
- `tryouts.js`: `initTryouts(section, model)` → bool.
- `seasons.js` (S5): `initSeasons(section, model)` → `{rowCardMount}` or null.
- `rowcard.js`: `renderRowCard(mount, {detail, rollingWindow})`.
- `walkthrough.js`: `buildWalkModel`, `initWalkthrough(section, detail, model)` → bool.
- `calibration.js`: `initCalibration(section, model)`.

## CSS
`components.css`: shell/nav, board, court-strip (all variants and claim states), legend, card, calibration SVG, ticket and stamp
(appended by S2), and a global reduced-motion rule. `tonight.css`: lede, court rows, toolbar, grid, ribbon, season,
W/L, calibration card, drawer and toasts (appended by S3). `model.css`: hero, chapter heads, ch6 and footer, plus the merged
chapter CSS (ch1/4/5, then ch2/3).

## Backend (`app.py`)
- `/model` and `/model.html` serve `public/model.html` (B7). `vercel.json` has a rewrite and header blocks for both.
- `/api/model` adds leaderboard `roc_auc`, `calibration_ece`, `test_games`, `is_production`; `feature_importance`;
  `elo` (from `ELO_PARAMS` in app.py; a test checks they equal `src/elo.py`); and `training` when the column exists
  (`MissingColumnError` falls back and sets migration_pending).
- `/api/featured-pick` (B4).
- `src/model_metadata.build_training_summary`; `src/model.py` writes `training` into the metadata.
- Migration file only: `supabase/migrations/20261006000100_model_runs_training.sql`.

## Sample data
Generated by `scripts/build_sample_data.py` through the real Flask routes over fake tables. Post-steps:
`settled_featured_game()` (a settled `game-0022600195.json` for the walkthrough) and `shorten_production_model()`. The
replay files `live-replay-0..6` follow the handoff script (end of night +117.01). `performance-all.json` and
`performance-2026-27.json` exist.
