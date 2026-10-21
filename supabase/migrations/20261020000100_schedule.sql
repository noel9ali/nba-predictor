-- Today's slate as the predict stage sees it (src/predict.py upserts it every run), so /api/slate can list
-- games as "pick pending" before their predictions rows exist. Additive. Idempotent: safe to re-run.
create table if not exists public.schedule (
  game_id text primary key,
  game_date date not null,
  home_team text not null,
  away_team text not null,
  tip_time_utc timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists schedule_game_date_idx on public.schedule (game_date);
alter table public.schedule enable row level security;
