-- Per-column guard: check each column individually (not just one representative column)
-- so a partially-converted table (e.g. one column hand-fixed out-of-band before Gate M)
-- still converts every remaining column instead of silently skipping the whole batch.
do $$
declare
  clauses text[] := '{}';
begin
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_PTS' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_roll_PTS" type double precision using nullif(trim("AWAY_roll_PTS"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_FG_PCT' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_roll_FG_PCT" type double precision using nullif(trim("AWAY_roll_FG_PCT"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_REB' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_roll_REB" type double precision using nullif(trim("AWAY_roll_REB"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_AST' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_roll_AST" type double precision using nullif(trim("AWAY_roll_AST"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_TOV' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_roll_TOV" type double precision using nullif(trim("AWAY_roll_TOV"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_roll_STOCKS' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_roll_STOCKS" type double precision using nullif(trim("AWAY_roll_STOCKS"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'HOME_rest_days' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "HOME_rest_days" type double precision using nullif(trim("HOME_rest_days"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_rest_days' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_rest_days" type double precision using nullif(trim("AWAY_rest_days"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'rest_diff' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column rest_diff type double precision using nullif(trim(rest_diff), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'HOME_PLUS_MINUS' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "HOME_PLUS_MINUS" type double precision using nullif(trim("HOME_PLUS_MINUS"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_PLUS_MINUS' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_PLUS_MINUS" type double precision using nullif(trim("AWAY_PLUS_MINUS"), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'GAME_DATE' and data_type <> 'date'
  ) then
    clauses := array_append(clauses, $c$alter column "GAME_DATE" type date using ("GAME_DATE" at time zone 'UTC')::date$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'features'
       and column_name = 'AWAY_GAME_DATE' and data_type <> 'date'
  ) then
    clauses := array_append(clauses, $c$alter column "AWAY_GAME_DATE" type date using nullif(trim("AWAY_GAME_DATE"), '')::date$c$);
  end if;

  if array_length(clauses, 1) > 0 then
    execute 'alter table public.features ' || array_to_string(clauses, ', ');
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
declare
  clauses text[] := '{}';
begin
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'predictions'
       and column_name = 'home_win_prob' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column home_win_prob type double precision using nullif(trim(home_win_prob), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'predictions'
       and column_name = 'away_win_prob' and data_type <> 'double precision'
  ) then
    clauses := array_append(clauses, $c$alter column away_win_prob type double precision using nullif(trim(away_win_prob), '')::double precision$c$);
  end if;
  if exists (
    select 1 from information_schema.columns
     where table_schema = 'public' and table_name = 'predictions'
       and column_name = 'odds' and data_type <> 'integer'
  ) then
    clauses := array_append(clauses, $c$alter column odds type integer using round(nullif(trim(odds), '')::numeric)::integer$c$);
  end if;

  if array_length(clauses, 1) > 0 then
    execute 'alter table public.predictions ' || array_to_string(clauses, ', ');
  end if;
end $$;
