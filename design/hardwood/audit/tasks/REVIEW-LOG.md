# Review log (lead)

| ID | Wave | Retries | Review notes |
|---|---|---|---|
| A1 | 1 | 0 | Accepted. 69/69. Chapters numbered by DOM position; fallback cards in ch3 and ch2. |
| A2 | 1 | 1 | Retry 1: fallback fired only for `=== null`, not a missing field. Fixed. 26/26. |
| A4 | 1 | 0 | Accepted. 12/12. DEN toast now "Tonight +$36.28". |
| A5 | 1 | 0 | Accepted. 36/36 + unit test. |
| A7 | 1 | 0 | No code change needed (already gated on SAMPLE); regression test added. 18/18. |
| B1 | 1 | 0 | Accepted. 95/95 (incl. reduced motion). |
| D8 | 1 | 0 | Accepted. 49/49. Card 645px → 193px at 1440. |
| B3 | 1 | 1 | Retry 1: ', unofficial' was added to no-bet stamps too; now only bet stamps. 175/175. |
| B7 | 2 | 0 | Accepted. 19/19; every row ≤ 1.2 s. Lead took the missing 768 screenshot. |
| A3 | 2 | 1 | Retry 1: whyCopy had dropped the existing log-loss sentence; builder comment wrong. Sample diff checked semantically (only model fields). 45/45 e2e, 291/291 Python. |
| A6 | 2 | 1 | Retry 1: at ≤520px the 5-cell board lost cell 4's bottom border. 56/56. No before-shots (audit shots serve). |
| B2 | 3 | 0 | Accepted. 117/117 (every night, keyboard + mouse, 3 widths). |
| B4 | 3 | 0 | Accepted. 39/39. Lead moved before-shots into after/. |
| D11 | 4 | 0 | Accepted. 6/6 (1440 only; text change is width-independent). |
| B5 | 3 | 1 | Retry 1 (lead-initiated): .stub notch rules leaked onto the Model mini ticket; scoped to .ticket .stub. Spec's right:-10px was 2px off; agent used -8px per the 1px acceptance test. 155/155. |
| C1 | 4 | 0 | Accepted. 24/24; chapter variant output unchanged. |
| C9 | 4 | 0 | Accepted. 24/24. |
| B6 | 3 | 2 + lead | Retry 1: overflow:hidden hid the truncated note. Retry 2: stamp raised onto the team rows/score. Lead fix: stamp back at bottom 30px on desktop; note box shrinks to its text; on ≤420px a taller spacer holds the stamp above the note. 55/56 (the one fail was D1's in-progress header overflow at 320). |
| C6 | 4 | 1 | Retry 1: SVG drawn at a 300px minimum and scaled (text ~9px at 320, names 48px past the card at 400); test hadn't caught it. Now 1:1. 1705/1705. |
| C2 | 5 | 1 + lead | Retry 1 left y labels 14px off their gridlines, y title over the ticks, a broken collision check, card variant changed, chart still scaled. Lead rewrote the geometry (shared by C1/C2), capped .cal-svg at 560px, fixed the test's rotated-text measurement, added 320. 38/38 C2, 24/24 C1. |
| D1 | 5 | 1 + lead | Retry 1: brand overlapped by sample tag/status (test only checked heights). Lead tweak: status text visually hidden (kept for screen readers) ≤480px instead of an ellipsis; brand/tag/gaps tightened ≤360px so the sample tag isn't clipped at 320. Header 235px → ≤ 95px. 49/49. |
| D2 | 6 | 0 | Accepted with a lead one-liner: the skip-if-unchanged check compared textContent (now with NBSPs) so it rebuilt every batch; now keyed on data-k. 104/104. |
| C7 | 5 | 1 + lead | Retry 1: labels sat on the strip border, '19–20' wrapped, 700px breakpoint moved to 560 (restored). Lead: labels back to left-aligned (prototype) and .scounts/.slabels selectors scoped to direct children. 77/77. |
| D3 | 7 | 0 | Accepted. 124/124 (+B4/D11/D2 still green). |
| C8 | 6 | 0 | Accepted. 122/122. |
| D9 | 8 | – | NOT accepted (uncommitted): 'SORT' label lifted above its row at 1440 (align-self:start) and clipped at 400. Needs a correction. |
| D5 | 6 | lead | Subagent's stamp move covered 'Back of ticket' (its test used a 15px tolerance). Lead: final-ticket .lines min-height 98px + stamp bottom 56px; test back to 0 tolerance. Dead space 94px → 18px. 107/107, B5 155/155. |
| D12 | 7 | 0 | Accepted. Gap kicker→step kicker 206px → 40px at 1440 (30/36 at 400/768); court position unchanged between states. 12/12. Lead took the base-state after shots. |
| C3 | 4 | 0 | Accepted. 33/33 (+B2 117/117). Step 1 domain $950–$1,200 at 400 (was to ~$1,350); step 3 extends to tonight's range. Lead restored committed screenshots that regression runs had overwritten. |
| D9 | 8 | 1 + lead | Retry 1: SORT label lifted above its row at 1440 (align-self:start). Lead: label indented 12px on the two-row layout so it lines up with ALL. 36/36. |
| C5 | 6 | 0 | Accepted. One hand-written '$0.00' → fmt.money(0); everything else already used cents via fmt.money. 25/25. |
| C4 | 5 | lead | Subagent 190/208: read overlay opacity mid-fade, treated hidden step-3 bar/line as obstacles, base-line check only for x<200. Lead rewrote placeLabels (step-based visibility, per-step obstacles, getBBox boxes, ruling-9 hide) and fixed the test's step-2 false positives. 196/196, C3 33/33, B2 117/117. |
| D6 | 7 | 0 | Accepted. 45/45. Lead retook the screenshots (the subagent's were taken before the tickets slid in). |
| D10 | 9 | 0 | Accepted. 399/399. |
| D4 | 8 | 0 | Accepted. wl()/seasonLabel() now replace every digit-hyphen; drawer records, tooltip and past-night copy use wl(). Sweep across scenes, drawers, tooltips and Model seasons: 126/126. |
| D7 | 9 | 0 | Accepted. 96/96. Lead took the after shots. |
