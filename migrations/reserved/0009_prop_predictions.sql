-- RESERVED: do not apply until prop models and product requirements are approved.
create table if not exists public.prop_predictions (
  game_id text not null,
  player_id bigint not null,
  stat text not null,
  line numeric not null,
  model_name text not null,
  mean numeric,
  dist jsonb,
  p_over numeric,
  p_under numeric,
  bookmaker text,
  price_over integer,
  price_under integer,
  edge numeric,
  bet_side text,
  bet_amount numeric,
  result_value numeric,
  profit_loss numeric,
  predicted_at timestamptz not null,
  primary key (game_id, player_id, stat, line, model_name)
);
-- This file is intentionally reserved and must not be applied by the migration runner.

