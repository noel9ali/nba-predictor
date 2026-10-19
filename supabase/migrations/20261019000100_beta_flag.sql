-- Beta vs live. Everything before the 2026-27 season was beta testing: keep it, flagged, and start the live
-- bankroll fresh. New rows default to live (is_beta = false); the pipeline never writes the flag.
alter table public.predictions add column if not exists is_beta boolean not null default false;
alter table public.bankroll    add column if not exists is_beta boolean not null default false;

update public.predictions set is_beta = true where game_date < '2026-09-01' and not is_beta;
update public.bankroll    set is_beta = true where date      < '2026-09-01' and not is_beta;

-- Live bankroll starts here (src/config.py LIVE_START_DATE); the first live balance is the starting bankroll.
insert into public.bankroll (date, balance, is_beta) values ('2026-09-01', 1000, false)
on conflict (date) do nothing;
