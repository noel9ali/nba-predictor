alter table public.features
  alter column "AWAY_roll_PTS"    type double precision using nullif(trim("AWAY_roll_PTS"), '')::double precision,
  alter column "AWAY_roll_FG_PCT" type double precision using nullif(trim("AWAY_roll_FG_PCT"), '')::double precision,
  alter column "AWAY_roll_REB"    type double precision using nullif(trim("AWAY_roll_REB"), '')::double precision,
  alter column "AWAY_roll_AST"    type double precision using nullif(trim("AWAY_roll_AST"), '')::double precision,
  alter column "AWAY_roll_TOV"    type double precision using nullif(trim("AWAY_roll_TOV"), '')::double precision,
  alter column "AWAY_roll_STOCKS" type double precision using nullif(trim("AWAY_roll_STOCKS"), '')::double precision,
  alter column "HOME_rest_days"   type double precision using nullif(trim("HOME_rest_days"), '')::double precision,
  alter column "AWAY_rest_days"   type double precision using nullif(trim("AWAY_rest_days"), '')::double precision,
  alter column rest_diff          type double precision using nullif(trim(rest_diff), '')::double precision,
  alter column "HOME_PLUS_MINUS"  type double precision using nullif(trim("HOME_PLUS_MINUS"), '')::double precision,
  alter column "AWAY_PLUS_MINUS"  type double precision using nullif(trim("AWAY_PLUS_MINUS"), '')::double precision,
  alter column "GAME_DATE"        type date using ("GAME_DATE" at time zone 'UTC')::date,
  alter column "AWAY_GAME_DATE"   type date using nullif(trim("AWAY_GAME_DATE"), '')::date;

alter table public.games
  alter column "PLUS_MINUS" type double precision using nullif(trim("PLUS_MINUS"), '')::double precision;

alter table public.elo
  alter column "GAME_DATE" type date using "GAME_DATE"::date;

alter table public.predictions
  alter column home_win_prob type double precision using nullif(trim(home_win_prob), '')::double precision,
  alter column away_win_prob type double precision using nullif(trim(away_win_prob), '')::double precision,
  alter column odds          type integer          using round(nullif(trim(odds), '')::numeric)::integer;
