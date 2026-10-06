# Decisions and spec conflicts (settled; don't re-open)

Handoff README "Designer rulings" win over everything else. Beyond those:

1. **Accuracy is 68.1%** everywhere (ruling 6). The sample `test.accuracy` is 0.6811, and the Tonight calibration card shows "68.1% of 1,596"
   (the card spec said 68.2%).
2. **Times are in ET** (ruling 11): the model footer says "retrained Oct 5, 2026, 10:05 PM ET" and the hero kicker "retrained Oct 5, 2026"
   (the sample trained_at is 02:05Z on Oct 6).
3. **The featured pick** in the real API is the largest edge among the latest settled night's bets. The sample `featured-pick.json`
   comes from the real route and gives `0022600195` (SAC).
4. **Walkthrough step 2** follows the data: "SAC better on 4 of 6 · GSW better on assists and steals + blocks". The spec's
   "5 of 6" contradicts its own sample tape (GSW stocks 15.2 > SAC 13.9). Reported to Noel.
5. **Records** always use an en dash, ticket team lines included (`Miami Heat · 5–7`), per ruling 4.
6. **The replay test hook** is `window.__sampleFeed.step()`, created only in sample mode. No `window.NBA` and no `advance` export
   (live-feed AC1).
7. **The `feeddown` scene** makes live-scores throw from the first request, so the banner shows at once and the games stay scheduled.
8. **Bankroll step 3** hides an "all cash" or "all lose" label that sits within 18px of the Tonight label (ruling 9).
9. **Old dashboard files** at the same paths were replaced: `api.js`, `format.js`, `model.js` (deleted, then recreated).
   Other old files are still there; delete them in D after grepping.
10. **Model CSS:** the subagents wrote `model-a.css` and `model-b.css`, which were merged into `model.css`, so the file layout matches the README.
11. **B3 Elo constants** live in `app.py`, because vercel.json `excludeFiles` drops `src/elo.py` from the function bundle.
12. **B2 `training`** needs a DB column. Only the migration file was written; applying it is Noel's call. The API handles the column
    being missing.
13. **Preview deploys:** the CLI login has expired and pushing the branch doesn't auto-deploy. Create the preview through the Vercel connector
    `create_deployment` with `gitSource {type:'github', org:'noel9ali', repo:'nba-predictor', ref:'hardwood-build', sha}`.
    No `target`, which makes it a preview.
14. **`tests/test_security.py`** `CDN_SOURCES` now includes `/model` and `/model.html` (B7).
