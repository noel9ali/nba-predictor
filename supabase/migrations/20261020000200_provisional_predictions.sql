-- Temporary ("provisional") picks from the 6 AM run, with the best-book price for the picked side. Kept apart from
-- predictions on purpose: they are never bet, settled or counted in any record. /api/slate shows one only while the
-- game has no predictions row; the pre-tip predict stage writes the real prediction. Additive. Idempotent.
create table if not exists public.provisional_predictions (
  game_id text primary key,
  game_date date not null,
  home_team text not null,
  away_team text not null,
  home_win_prob double precision not null,
  away_win_prob double precision not null,
  predicted_winner text not null,
  odds integer,
  bookmaker text,
  implied_prob double precision,
  edge double precision,
  model_name text,
  predicted_at timestamptz not null default now()
);
create index if not exists provisional_predictions_game_date_idx on public.provisional_predictions (game_date);
alter table public.provisional_predictions enable row level security;
