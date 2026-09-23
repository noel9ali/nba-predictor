create table if not exists public.model_runs (
  id               bigint generated always as identity primary key,
  trained_at       timestamptz not null unique,
  production_model text not null,
  best_model       text not null,
  cutoff_date      date,
  test_games       integer,
  features         jsonb not null,
  available_models jsonb not null,
  leaderboard      jsonb not null,  -- array of objects; keys = data/model_leaderboard.csv columns
  created_at       timestamptz not null default now()
);
alter table public.model_runs enable row level security;
