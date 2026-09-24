create or replace view public.v_nightly with (security_invoker = true) as
select game_date,
       season,
       count(*)                                                    as games,
       count(*) filter (where correct = 1)                         as picks_won,
       count(*) filter (where correct = 0)                         as picks_lost,
       count(*) filter (where bet_amount > 0)                      as bets,
       count(*) filter (where bet_amount > 0 and profit_loss > 0)  as bets_won,
       count(*) filter (where bet_amount > 0 and profit_loss < 0)  as bets_lost,
       coalesce(sum(bet_amount) filter (where bet_amount > 0), 0)  as staked,
       coalesce(sum(profit_loss), 0)                               as net_pl
  from public.predictions
 group by game_date, season;

create or replace function public.team_form(p_season text, p_before date)
returns table (team_id bigint, tricode text, wins int, losses int, last10 text)
language sql stable security invoker set search_path = public as $$
  with g as (
    select "TEAM_ID" as team_id, "TEAM_ABBREVIATION" as tricode, "WL" as wl, "GAME_DATE" as d,
           row_number() over (partition by "TEAM_ID" order by "GAME_DATE" desc) as rn
      from games
     where "SEASON" = p_season and "GAME_DATE" < p_before and "WL" in ('W','L')
  )
  select team_id, max(tricode),
         (count(*) filter (where wl = 'W'))::int,
         (count(*) filter (where wl = 'L'))::int,
         string_agg(wl, '' order by d desc) filter (where rn <= 10)
    from g group by team_id;
$$;

revoke all on public.v_nightly from anon, authenticated;
revoke execute on function public.team_form(text, date) from public, anon, authenticated;
grant execute on function public.team_form(text, date) to service_role;
