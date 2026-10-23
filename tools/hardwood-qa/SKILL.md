---
name: hardwood-qa
description: Check the Hardwood Tonight and Model pages for broken data, layout and chart label collisions, machine-sounding copy, awkward motion and accessibility problems. Use after any frontend change, before a deploy, or when Noel says "QA the frontend", "check the visuals" or "audit the pages".
---

# hardwood-qa

One command checks every Tonight scene and the Model page at 1440, 768 and 400 px wide, in a real browser, with the production CSP.

## Run it

From the repo root:

```
node .claude/skills/hardwood-qa/scripts/qa.mjs
```

Needs `playwright` with a Chromium (`npm i -D playwright && npx playwright install chromium`). It starts its own static server on `public/`. To test a running server instead, set `BASE=http://127.0.0.1:5057`.

Options (environment variables): `WIDTHS=1440,400`, `PAGES=model` (only pages whose name contains that text), `ONLY=lint` (or `page`, `motion`), `OUT=qa-out`, `BASELINE=path/to/report.json`.

Exit code 1 means a new A or B issue. Read `qa-out/report.md`; screenshots of the worst spots are in `qa-out/shots/`.

## What it checks

| Severity | Meaning | Examples |
|---|---|---|
| A | Wrong or broken data | `undefined` or `NaN` on screen, "0 of 0", empty cells, raw model keys like `gradient-boosting-gridsearch`, dev notes visible outside `?sample=1`, accuracy numbers or model names hard-coded in source |
| B | Functional or accessibility | Focus hidden under the ribbon, tooltip leaving its card, page wider than the window, console errors, animations still running with reduced motion |
| C | Chart and label collisions | Overlapping SVG labels, dashed rules through a label, labels past the chart edge |
| D | Layout, copy and polish | Tokens that wrap mid-value ("4–" / "1"), hyphens where en dashes belong, ellipsized text, tap targets under 44 px, machine-sounding phrases, spaced em dashes, reveals that take over 1.2 s, layout shift |

Pages covered: all eleven Tonight scenes, a past date, Model in sample mode, and three production-like Model variants with a mocked API (normal, featured game 404, null production model).

## Working loop

1. Run it. Fix A and B first, then C, then D.
2. Re-run with `PAGES=<the page you touched>` until clean.
3. Look at the screenshots. Checks catch geometry, not taste; `references/taste.md` says what Noel cares about beyond that.
4. When a finding is intended, either put `qa-ok` on the source line (lint hits) or save the report as the baseline: `cp qa-out/report.json .claude/skills/hardwood-qa/baseline.json`. Known issues are then listed separately and never fail the run.
5. Do not loosen a check to get green. Fix the page, or baseline it with a reason.

## Extending

Add a scene to `SCENES` or a page to `PAGES` at the top of `scripts/qa.mjs`. Add banned phrases to `BANNED`. Add a file to `MODEL_NAME_OK` only if it must name a model family.
