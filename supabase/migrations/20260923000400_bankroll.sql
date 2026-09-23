create table if not exists public.bankroll (
  date       date primary key,
  balance    double precision not null,
  updated_at timestamptz not null default now()
);
alter table public.bankroll enable row level security;
