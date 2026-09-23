update public.predictions p
   set season = g."SEASON"
  from (select distinct "GAME_ID", "SEASON" from public.games) g
 where g."GAME_ID" = p.game_id and p.season is null;

update public.predictions set status = 'final'
 where actual_winner is not null and status = 'scheduled';

insert into public.bankroll (date, balance)
select min(game_date) - 1, 1000.0 from public.predictions
on conflict (date) do nothing;

insert into public.bankroll (date, balance)
select game_date, 1000.0 + sum(sum(profit_loss)) over (order by game_date)
  from public.predictions
 where profit_loss is not null
 group by game_date
on conflict (date) do update set balance = excluded.balance, updated_at = now();
