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

## NOT done (Supabase apply_migration was denied by the permission classifier)
- Beta-flag migration 20261019000100_beta_flag.sql — not applied.
- Vercel production deploy of 97ddf29 — not attempted.
- Test SMS and Odds API quota check — not attempted.
- Player-data scope A: nothing applied or deployed (nothing to do).

## Needed before Tue 06:00
1. Apply the migration (allow mcp__claude_ai_Supabase__apply_migration, or use the Supabase SQL editor).
2. Vercel production deploy from main 97ddf29, then check the API against tests/contract_shapes.py.
3. Laptop plugged in and awake overnight.

## Tuesday-morning checklist
- [ ] workflow_log has a new success row for Oct 20
- [ ] predictions rows = tonight's slate
- [ ] book_odds filled for the slate
- [ ] SMS received
- [ ] live bankroll row $1,000 (2026-09-01, is_beta = false)
