-- 0003_player_ratings.sql  (player-data-work; NOT applied by the agent, apply manually)
-- Point-in-time player ratings and per-game minutes projections. Writers upsert on the primary keys.
-- Idempotent: safe to re-run.

-- One row per player per as_of date per rating type. as_of = the date the rating was computed;
-- it uses only games strictly before that date.
create table if not exists public.player_ratings (
  player_id      bigint not null,
  as_of          date not null,
  rating_type    text not null,           -- 'rapm_lite_v1' | 'box_value_v1'
  value          numeric not null,        -- points per 100 possessions relative to average
  minutes_basis  numeric not null,        -- minutes in the training window (sample size)
  se             numeric,
  version        text not null,
  primary key (player_id, as_of, rating_type)
);
create index if not exists player_ratings_type_asof_idx on public.player_ratings (rating_type, as_of);

-- One row per rostered player per upcoming game each time projections run.
create table if not exists public.player_minutes_projection (
  game_id   text not null check (game_id ~ '^[0-9]{10}$'),
  player_id bigint not null,
  as_of     timestamptz not null,
  team_id   bigint not null,
  p_play    numeric not null check (p_play >= 0 and p_play <= 1),
  exp_min   numeric not null,              -- p_play x min_if_play
  min_if_play numeric,                     -- expected minutes if he plays (additive; props use it)
  min_p10   numeric,
  min_p90   numeric,
  role      text not null check (role in ('starter', 'rotation', 'bench', 'inactive')),
  basis     text not null,
  version   text not null,
  primary key (game_id, player_id, as_of)
);
create index if not exists player_minutes_projection_game_idx on public.player_minutes_projection (game_id, as_of);

alter table public.player_ratings            enable row level security;
alter table public.player_minutes_projection enable row level security;
revoke all on public.player_ratings, public.player_minutes_projection from anon, authenticated;
