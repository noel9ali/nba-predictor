create table if not exists public.book_odds (
  id          bigint generated always as identity primary key,
  game_id     text not null references public.predictions (game_id) on delete cascade,
  captured_at timestamptz not null default now(),
  bookmaker   text not null,
  home_price  integer,
  away_price  integer,
  constraint book_odds_game_book_key unique (game_id, bookmaker)
);
alter table public.book_odds enable row level security;
