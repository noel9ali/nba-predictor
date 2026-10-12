create table if not exists public.player_rate_stats (
  player_id bigint not null,
  as_of timestamptz not null,
  stat text not null,
  rate_per_min numeric not null,
  minutes_basis numeric not null default 0,
  version text not null,
  primary key (player_id, as_of, stat)
);
alter table public.player_rate_stats enable row level security;

