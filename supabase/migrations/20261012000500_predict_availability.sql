-- 0005_predict_availability.sql  (player-data-work; NOT applied by the agent, apply manually)
-- Predict-time availability: scenario blending, factor contributions, status-change flags.
-- Additive and nullable only; old consumers keep working. Idempotent: safe to re-run.

create table if not exists public.prediction_scenarios (
  game_id        text not null check (game_id ~ '^[0-9]{10}$'),
  model_name     text not null,
  scenario_key   text not null,            -- 'base' or '<player_id>=1|<player_id>=0|...'
  weight         double precision not null check (weight >= 0 and weight <= 1),
  home_win_prob  double precision not null,
  label          text,                     -- 'Jokić plays, Murray out'
  predicted_at   timestamptz,
  primary key (game_id, model_name, scenario_key)
);

create table if not exists public.prediction_factors (
  game_id      text not null check (game_id ~ '^[0-9]{10}$'),
  model_name   text not null,
  factor_key   text not null,
  label        text not null,
  "group"      text not null check ("group" in ('base', 'form', 'availability', 'rest')),
  prob_points  double precision not null,  -- percentage points; base rate + sum = stored probability
  sort_order   integer not null,
  primary key (game_id, model_name, factor_key)
);

-- What the availability step saw at prediction time (key players' statuses), for the status-change flag.
create table if not exists public.prediction_availability_inputs (
  game_id                    text not null check (game_id ~ '^[0-9]{10}$'),
  model_name                 text not null,
  predicted_at               timestamptz not null,
  as_of                      timestamptz not null,
  home_win_prob              double precision,
  prob_range_low             double precision,
  prob_range_high            double precision,
  key_statuses               jsonb,
  status_changed_after_pred  boolean,
  primary key (game_id, model_name)
);

alter table public.predictions
  add column if not exists prob_range_low            double precision,
  add column if not exists prob_range_high           double precision,
  add column if not exists status_changed_after_pred boolean;

-- Extend the allowed skip reasons with the (default-off) availability gate.
alter table public.predictions drop constraint if exists predictions_skip_reason_chk;
alter table public.predictions add constraint predictions_skip_reason_chk
  check (skip_reason is null or skip_reason in ('no_odds', 'missing_data', 'availability_uncertain'));

alter table public.prediction_scenarios           enable row level security;
alter table public.prediction_factors             enable row level security;
alter table public.prediction_availability_inputs enable row level security;
revoke all on public.prediction_scenarios, public.prediction_factors, public.prediction_availability_inputs
  from anon, authenticated;
