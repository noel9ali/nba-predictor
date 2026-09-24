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

do $$
begin
  if to_regprocedure('public.rls_auto_enable()') is not null then
    revoke execute on function public.rls_auto_enable() from public, anon, authenticated;
  end if;
end $$;

-- Close default privileges for objects this migration role (postgres) creates in schema public, so a
-- future table/function/sequence added without an explicit grant/RLS step isn't openly readable/writable
-- by the anon/authenticated keys by default. Supabase-platform default ACLs owned by other grantor roles
-- (e.g. supabase_admin) are out of reach from migrations; those are mitigated by RLS being enabled on
-- every table plus the rls_auto_enable() event trigger auto-enabling RLS on newly created tables.
alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on functions from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;

-- Per the Postgres docs (ALTER DEFAULT PRIVILEGES), per-schema default privileges are ADDED to,
-- not substituted for, the global default; a per-schema REVOKE only reverses a per-schema GRANT
-- and cannot claw back Postgres's built-in global default of EXECUTE to PUBLIC on functions. Once
-- the per-schema functions row above is emptied of anon/authenticated, a future function with no
-- explicit revoke of its own falls straight back to that global PUBLIC-execute default, which
-- anon/authenticated inherit as members of PUBLIC. Close the global default directly.
alter default privileges for role postgres revoke execute on functions from public;
