alter table public.games        enable row level security;
alter table public.elo          enable row level security;
alter table public.features     enable row level security;
alter table public.predictions  enable row level security;
alter table public.bankroll     enable row level security;
alter table public.workflow_log enable row level security;
alter table public.book_odds    enable row level security;
alter table public.model_runs   enable row level security;

revoke all on public.games, public.elo, public.features, public.predictions,
              public.bankroll, public.workflow_log, public.book_odds, public.model_runs
  from anon, authenticated;

revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
