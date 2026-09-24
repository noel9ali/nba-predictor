alter table public.predictions
  add column if not exists season          text,
  add column if not exists tip_time_utc    timestamptz,
  add column if not exists bookmaker       text,
  add column if not exists implied_prob    double precision,
  add column if not exists edge            double precision,
  add column if not exists bankroll_at_bet double precision,
  add column if not exists kelly_full      double precision,
  add column if not exists kelly_fraction  double precision,
  add column if not exists model_name      text,
  add column if not exists predicted_at    timestamptz,
  add column if not exists status          text not null default 'scheduled',
  add column if not exists home_score      integer,
  add column if not exists away_score      integer,
  add column if not exists skip_reason     text;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'predictions_status_chk' and conrelid = 'public.predictions'::regclass) then
    alter table public.predictions add constraint predictions_status_chk check (status in ('scheduled','final','postponed','void'));
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'predictions_skip_reason_chk' and conrelid = 'public.predictions'::regclass) then
    alter table public.predictions add constraint predictions_skip_reason_chk check (skip_reason is null or skip_reason in ('no_odds','missing_data'));
  end if;
end $$;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'predictions_season_fmt_chk' and conrelid = 'public.predictions'::regclass) then
    alter table public.predictions add constraint predictions_season_fmt_chk check (season is null or season ~ '^\d{4}-\d{2}$');
  end if;
end $$;
