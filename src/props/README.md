# Props groundwork (reserved)

There are no user-facing prop predictions in this package.  The planned flow is:

1. use `player_minutes_projection` to project participation and minutes;
2. use `player_rate_stats` for shrunk points, rebounds, assists, threes, steals,
   blocks, and turnovers per minute;
3. form a distribution from the rate and minute uncertainty;
4. compare the distribution with a market line and size through
   `betting.stake(..., exposure_left=...)`.

The current provider is The Odds API.  Its documented NBA markets include
`player_points`, `player_rebounds`, `player_assists`, `player_threes`,
`player_blocks`, `player_steals`, `player_turnovers`, PRA and alternate-line
markets.  Prop odds are requested per event; each market/region consumes
credits.  Historical prop endpoints require a paid plan.  The free-plan
quota and current bookmaker coverage were not verified with a live request.

Open issues before implementation:

* same-game correlation between game bets and props and the exposure cap;
* line churn and which captured line is authoritative;
* voiding rules when a player does not play;
* name matching quality through `player_aliases`;
* an appropriate count/normal model for each stat.

