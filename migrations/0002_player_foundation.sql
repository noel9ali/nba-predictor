-- 0002_player_foundation.sql  (player-data-work; NOT applied by the agent, apply manually)
-- Player identity, name aliases, per-game box scores and derived absences.
-- Writers upsert on each table's primary key. Idempotent: safe to re-run.

create table if not exists public.players (
  player_id   bigint primary key,
  full_name   text not null,
  first_name  text,
  last_name   text,
  position    text,
  birth_date  date,
  is_active   boolean not null default false,
  updated_at  timestamptz not null default now()
);

-- Join key for every name-based feed (injury report now, prop odds later).
-- provider examples: 'nba_api' (display name), 'normalized' (player_names.normalize_name),
-- 'nba_injury_report' ('Last, First' as printed), later 'the_odds_api'.
create table if not exists public.player_aliases (
  provider       text not null,
  provider_name  text not null,
  player_id      bigint not null,
  updated_at     timestamptz not null default now(),
  primary key (provider, provider_name)
);
create index if not exists player_aliases_player_idx on public.player_aliases (player_id);

create table if not exists public.player_games (
  game_id     text not null check (game_id ~ '^[0-9]{10}$'),
  player_id   bigint not null,
  team_id     bigint not null,
  game_date   date not null,
  season      text not null,
  is_home     boolean not null,
  started     boolean,
  minutes     numeric,
  pts integer, reb integer, oreb integer, dreb integer, ast integer, stl integer, blk integer,
  tov integer, pf integer, fgm integer, fga integer, fg3m integer, fg3a integer, ftm integer, fta integer,
  plus_minus  integer,
  primary key (game_id, player_id)
);
create index if not exists player_games_player_date_idx on public.player_games (player_id, game_date);
create index if not exists player_games_team_date_idx on public.player_games (team_id, game_date);

create table if not exists public.player_absences (
  game_id          text not null check (game_id ~ '^[0-9]{10}$'),
  player_id        bigint not null,
  team_id          bigint not null,
  game_date        date not null,
  basis            text not null check (basis in ('inferred', 'boxscore_comment', 'report')),
  reason           text,
  typical_minutes  numeric,
  primary key (game_id, player_id)
);
create index if not exists player_absences_team_date_idx on public.player_absences (team_id, game_date);

alter table public.players         enable row level security;
alter table public.player_aliases  enable row level security;
alter table public.player_games    enable row level security;
alter table public.player_absences enable row level security;
revoke all on public.players, public.player_aliases, public.player_games, public.player_absences
  from anon, authenticated;
