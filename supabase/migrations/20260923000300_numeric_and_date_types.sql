do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_PTS' and data_type = 'double precision'
  ) then
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
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'games'
       and column_name = 'PLUS_MINUS' and data_type = 'double precision'
  ) then
    alter table public.games
      alter column "PLUS_MINUS" type double precision using nullif(trim("PLUS_MINUS"), '')::double precision;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'elo'
       and column_name = 'GAME_DATE' and data_type = 'date'
  ) then
    alter table public.elo
      alter column "GAME_DATE" type date using nullif(trim("GAME_DATE"), '')::date;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'predictions'
       and column_name = 'home_win_prob' and data_type = 'double precision'
  ) then
    alter table public.predictions
      alter column home_win_prob type double precision using nullif(trim(home_win_prob), '')::double precision,
      alter column away_win_prob type double precision using nullif(trim(away_win_prob), '')::double precision,
      alter column odds          type integer          using round(nullif(trim(odds), '')::numeric)::integer;
  end if;
end $$;
