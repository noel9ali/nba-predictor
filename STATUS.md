# STATUS — Mon Oct 19, 2026 (pre-opening night)

## Verified (read-only)
- Checkout `C:\Users\noel9\Desktop\nba-predictor`: main = origin/main = 97ddf29 (only untracked backups/archives). Fast-forward is a no-op.
- Scheduler (both Ready; the .bat files point at this checkout):
  - NBA-Predictor-Daily: daily 06:00 ET, next run Tue Oct 20 06:00. Last result 0xC000013A (terminated) at Oct 19 10:12; logs/workflow.log has no entry from that run (last write 01:46).
  - NBA-Predictor-Injury-Snapshot: ALREADY registered; repeats from 11:00 today; not run yet.
  - Both: WakeToRun = False, StartWhenAvailable = True, DisallowStartIfOnBatteries = True. A sleeping or on-battery laptop will not run the 06:00 job on time.
- .env key names (all set, values not read): ODDS_API_KEY, TWILIO_API_SID, TWILIO_CLIENT_SECRET, TWILIO_ACCOUNT_SID, TWILIO_FROM, TWILIO_TO, FLASK_*, SUPABASE_URL / PUBLISHABLE_KEY / SECRET_KEY / JWKS_URL, NBA_SCHEMA_V2.
- Power (Performance plan): sleep on AC = never; on battery the sleep timeout is short. Lid action not conclusively read (`powercfg /requests` needs admin).
- Offline tests: `venv\Scripts\python.exe scripts\run_offline_tests.py` -> exit 0, "OK". Bare `python` is the Windows Store stub; use the venv.

## Done after approval (Oct 19, ~10:55 ET)
- Migration beta_flag applied to aopkwfeocvgkzejxjruw. Verified: bankroll 23 beta rows + 1 live row (2026-09-01, $1000, is_beta=false); predictions 174, all beta, none live.
- Vercel production deploy dpl_Akef9UoR8yt7pgumbacCgEV5ckEp from 97ddf29: READY, aliased to nba-predictor-tau.vercel.app.
- Live API vs tests/contract_shapes.py: SLATE, PERFORMANCE, FEATURED_PICK, LIVE_SCORES, INJURIES all OK (performance: season 2026-27, bankroll $1000, beta_seasons [2025-26]). Not checked live: MODEL, DAYS, PREDICTIONS, GAME_DETAIL (covered by offline tests).
- /api/injuries reports migration_pending=true (expected: Oct 12 player-data migrations not applied, scope A). /api/featured-pick returns game_id 0022501197 while the slate is empty (offseason oddity, harmless).
- Test SMS via Twilio API key: SID SM663a5499c508d80d63f61be0d829a0b8, status queued (confirm it reached your phone).
- Odds API: HTTP 200, x-requests-remaining 500, used 0 (checked on /sports, no quota cost).
- Player-data scope A: nothing applied or deployed.

## Still open
- Keep the laptop plugged in and awake overnight; WakeToRun is off and the task will not start on battery.

## Tuesday-morning checklist
- [ ] workflow_log has a new success row for Oct 20
- [ ] predictions rows = tonight's slate
- [ ] book_odds filled for the slate
- [ ] SMS received
- [ ] live bankroll row $1,000 (2026-09-01, is_beta = false)
