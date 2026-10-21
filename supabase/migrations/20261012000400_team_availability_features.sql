-- 0004_team_availability_features.sql  (player-data-work; NOT applied by the agent, apply manually)
-- Availability-adjusted team features and rest, one row per team per game per as_of per rating type.
-- Writers upsert on the primary key. Idempotent: safe to re-run.
-- Deviation from the spec: rating_type is part of the key so both rating types can be evaluated side by side.

create table if not exists public.team_availability_features (
  game_id          text not null check (game_id ~ '^[0-9]{10}$'),
  team_id          bigint not null,
  as_of            timestamptz not null,       -- history: tip time minus 60 minutes
  rating_type      text not null,              -- 'rapm_lite_v1' (box_value_v1 fallback) | 'box_value_v1'
  basis            text not null check (basis in ('realized', 'report')),
  rating_baseline  numeric,                    -- minutes-weighted rating of the full healthy rotation
  rating_expected  numeric,                    -- the same with projected minutes (sum exp_min / 240 x rating)
  value_out        numeric,                    -- baseline minus expected
  star_out         smallint,                   -- 1 if a top-2 player by rating has p_play < 0.5
  top3_avail       numeric,                    -- mean p_play of the top 3 by rating
  minutes_lost     numeric,                    -- projected minutes missing from the usual top-8 rotation
  n_key_uncertain  smallint,                   -- top-5-by-impact players with 0.1 < p_play < 0.9
  rest_days        smallint,                   -- days since the previous game this season (1 = back-to-back), capped
  is_b2b           smallint,
  games_last_7     smallint,                   -- games in the 7 days before this one
  feature_version  text not null,
  primary key (game_id, team_id, as_of, rating_type)
);
create index if not exists team_availability_features_game_idx on public.team_availability_features (game_id);

alter table public.team_availability_features enable row level security;
revoke all on public.team_availability_features from anon, authenticated;
