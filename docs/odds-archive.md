# Odds archive and closing-line capture (proposal on branch `odds-archive-and-pplay`)

Goal: keep every Odds API response the pipeline already pays for, as an append-only time series, so that model vs market,
closing-line value (CLV) and line movement against injury news can be measured later. Nothing here changes a prediction,
a stake or a table in Supabase.

## 1. Audit of what existed (read from the code, nothing run against the API)

| question | answer |
|---|---|
| The call | `odds.get_tonights_odds()`: one `GET /v4/sports/basketball_nba/odds?regions=us&markets=h2h&oddsFormat=american`, 1 credit for the whole slate. Called once per priced predict tick (`predict.py`), capped at `ODDS_DAILY_CALL_CAP = 12`/day via `data\odds_budget.json`. |
| What the caller gets | a dict of the best price per side over five preferred books (DraftKings, FanDuel, BetMGM, BetRivers, BetUS). Other bookmakers in the response are dropped. |
| What is stored | `market_odds` through `market_odds.write_moneyline_rows` -> `player_store.upsert`: with `NBA_PLAYER_STORE=local` (default) the local mirror `data\player_data\player_data.sqlite` (git-ignored via `data/player_data/`), with `supabase` the table from migration `20261012000700_market_odds.sql` (I could not check whether it is applied). Only the preferred books, only `h2h`, one row per book and side. |
| Identity | `game_id` is the **Odds API event id**, not the NBA game id, and the row has no team names and **no `commence_time`**, so a stored row cannot be joined to `predictions` or to a tip time afterwards. |
| `captured_at` | UTC, taken after the response arrived (seconds precision). Point in time. The existing test pins that it is not `commence_time`. |
| Time series? | Yes by accident: `odds_id` is a hash that includes `captured_at`, so a second call for the same game later is a new row; two writes in the same second collapse (upsert). |
| Quota headers | `x-requests-used` / `-remaining` were only printed. Not stored. |
| `book_odds` | read by `app.py` (odds-at-bet grid) but **nothing in `src/` writes it** (grep). Probably empty or legacy; worth a look in Supabase. |

## 2. What this branch adds (zero extra credits)

`src/odds_archive.py`, wired into `odds.get_tonights_odds()` and the `get_bookmakers()` debug helper. Every response
(including failed ones, to keep the quota headers) is appended to
`data\odds_history\odds_history.sqlite` (git-ignored, directory created on first use; `NBA_ODDS_HISTORY_DB` overrides).

* `odds_calls`: `captured_at` (UTC, ms), `purpose` (`pricing` | `closing` | `debug`), HTTP status, events, `requests_remaining/used/last`.
* `odds_snapshots`: one row per `(captured_at, event_id, bookmaker_key, market, selection)` with `commence_time`,
  home/away team names, `price_american`, the book's own `last_update`, and `nba_game_id` (filled by
  `link_game_ids` from the scoreboard after each priced call, by team pair + tip time; otherwise the team pair and
  `commence_time` identify the game). **All bookmakers and markets in the response are kept.**
* Append-only and idempotent: primary key above plus `INSERT OR IGNORE`; re-archiving the same response is a no-op,
  a later capture of the same game adds rows.
* Non-fatal: `safe_archive` never raises (an `ERROR:` line is printed); `get_tonights_odds` still returns the same dict.
* Tests: `tests\test_odds_archive.py` (mocked responses; the offline runner points the archive at a temp dir).
* About 200 rows per call, ~60k rows a month: negligible.

## 3. Closing-line capture (flag `config.ODDS_CLOSING_CAPTURE`, shipped OFF)

`predict.maybe_capture_closing()` runs on every predict tick before the pricing filters: when a not-yet-started game tips
2 to 17 minutes ahead (a 15-minute tick lands exactly once in that window, i.e. about tip minus 10) and that tip time has no
closing capture yet (ledger table `closing_captures`), it spends **one** call (`purpose='closing'`), archives it, links game
ids and marks every tip time due at that tick. Guards: own daily cap `ODDS_CLOSING_DAILY_CALL_CAP = 8`, a monthly reserve
(`ODDS_CLOSING_MONTHLY_RESERVE = 100`: no closing call when the last `x-requests-remaining` is at or below it), unreadable
budget or ledger state means no call, and any exception is reported and swallowed.

### Credit arithmetic (simulated on the cached 2024-25 and 2025-26 schedules with the real tick grid)

Ticks :05/:20/:35/:50 from 10:05 to 22:05 ET, 75-minute window, one pricing call per tick that prices a new game:

| | pricing only (today) | pricing + closing |
|---|---|---|
| calls per game day, mean / max (2025-26) | 4.8 / 9 | 9.3 / 18 |
| calls per game day, mean / max (2024-25) | 4.7 / 15 | 9.1 / 29 |
| busiest month (2025-26: Jan) | 163 | 316 |
| busiest month (2024-25: Mar) | 148 | 287 |
| season total | 791 (2025-26) | 1,526 |
| days over the 12/day cap | 0 (2025-26), 1 (2024-25) | 22 and 17 if one shared cap of 12 |

Against the 500/month plan the busiest month with closing capture uses 316 (63%), leaving ~180 for retries, manual runs and
playoff days. The shared 12/day cap would block closing calls on ~20 days a season, hence the separate closing cap (pricing 12 +
closing 8 = 20 max a day). The monthly reserve guard stops closing calls before the plan runs out.

**One scheduling gap:** the last predict tick is 22:05 ET, so tip times after ~22:20 ET (7:30 pm PT and later) get no closing slot
(49 and 56 tip times a season). Extending the task to 22:35 ET (in `scheduler\`, not changed on this branch) leaves 15 a season,
the 11 pm ET tips.

### Recommendation
1. Merge the archive part for opening night: it costs nothing, is non-fatal, and starts the history immediately.
2. Leave `ODDS_CLOSING_CAPTURE` OFF for the opener (it adds a call path to the live predict task the day it goes live). Turn it
   on after a week of the archive running cleanly, together with the 22:35 end time for the predict task; expect ~9 calls on a
   typical night and up to ~320 in the busiest month. Do not raise the pricing cap.
3. After ~400 games with both snapshots run `scripts\market_vs_model.py` (see its docstring for the sample sizes needed).
4. Playoff nights have few distinct tip times, so they use fewer calls than regular-season Saturdays.
