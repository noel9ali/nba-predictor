# Common rules for every audit fix task (Oct 7 2026)

Repo (git worktree, branch `fix/hardwood-audit`): `C:\Users\noel9\Desktop\nba-predictor\.claude\worktrees\hardwood-audit`
All paths below are relative to it. Use the Bash tool (Git Bash) for commands; prefix with
`cd /c/Users/noel9/Desktop/nba-predictor/.claude/worktrees/hardwood-audit &&`.

## Hard rules (the fix is rejected if any is broken)
1. **Strict CSP.** No inline `<script>` or `<style>`, no `style="…"` attributes in HTML strings or templates,
   no `el.setAttribute('style', …)`, no `innerHTML` containing `style=`. Set dynamic values with
   `el.style.setProperty('name', value)` or SVG attributes (`x`, `y`, `width`, `transform`, …). Self-hosted fonts only.
2. **Don't touch `src/`** (the Python pipeline). **Escape all API text**: any API string that goes into an HTML
   string passes through `esc()` from `public/static/js/format.js`, or use `textContent`.
3. **Don't redesign.** Fix only what your task describes. Match the prototype
   (`handoff/reference/prototypes/tonight.html`, `model.html`; source in `handoff/reference/prototypes/src/`).
4. **No horizontal page scroll** at any width 320–1920px. **Reduced motion** (`prefers-reduced-motion: reduce`)
   must show end states.
5. **Edit only the files listed under "Files owned" in your task.** Other subagents are editing other files at
   the same time. If you believe another file must change, stop and say so in your report instead of editing it.
   You may always create your own test file `tests/e2e/audit/<ID>.mjs` and your screenshots.
6. **No git commands that change state** (no commit, checkout, stash, reset, push). The lead reviews and commits.
7. Never run `vercel deploy`, never change env vars, never write to Supabase, never print `.env` values.
8. Keep the code style of the file you edit: same naming, comment density, ES modules, no new dependencies.

## The page under test
- A Flask server with the production CSP headers is already running at **http://127.0.0.1:5057**, serving this
  worktree's `public/` (edits show up on reload). Do not start or stop it. If it isn't answering
  (`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5057/`), say so in your report.
- Sample mode: `/?sample=1&scene=<scene>` with scene ∈ live, nextup, sofar, final, nobets, before, failed,
  offseason, edges, stale, feeddown, early, replay. Past mode: `/?sample=1&date=2026-11-16`.
  Model page: `/model?sample=1`. In replay, `await page.evaluate(() => window.__sampleFeed.step())` advances the feed.
- Both pages set `html[data-ready]` when the first data has landed.

## Test harness
`tests/e2e/audit/lib.mjs` (Playwright, already installed) exports:
`open(path, width, {reducedMotion, height, route})` → page (waits for data-ready + fonts; `page.errors` collects
console errors), `scrollTo(page, selector, waitMs)`, `shot(page, name, selector?)` → saves
`design/hardwood/audit/after/<name>.png`, `check(name, ok, detail)`, `report()`, `intersects(rectA, rectB, tol)`,
`done(page)`, `close()`, `WIDTHS` = [400, 768, 1440].

Write your acceptance test as `tests/e2e/audit/<ID>.mjs`, e.g.:
```js
import { open, done, close, check, report, shot, scrollTo, WIDTHS } from './lib.mjs';
for (const w of WIDTHS) {
  const p = await open('/?sample=1&scene=live', w);
  const v = await p.evaluate(() => document.querySelector('[data-testid=hero]').textContent);
  check(`${w}: hero has text`, v.length > 0, v);
  check(`${w}: no console errors`, p.errors.length === 0, p.errors.join(' | '));
  await done(p);
}
await close(); report();
```
Run it with `node tests/e2e/audit/<ID>.mjs` from the repo root. It must exit 0. Every test also checks
`page.errors` is empty (this catches CSP violations, which Chromium reports as console errors).

## Workflow
1. Read your task file fully, then the source files it names (and the screenshot under `design/hardwood/audit/shots/`).
2. **Before** editing: write the test, run it (expect FAIL), and take before-screenshots named
   `<ID>-before-<width>` (400, 768, 1440) of the region your task is about.
3. Make the fix in the owned files only.
4. Run the test until it passes. Take after-screenshots named `<ID>-<width>`.
5. Run `node tests/js/pure.test.mjs` if you touched `format.js`, `state.js`, `calibration-chart.js`, or
   anything that file imports; it must still pass.
6. Return ONLY: files changed, a short summary of the change, the full output of your acceptance test, and the
   screenshot paths. Mention anything you could not do.
