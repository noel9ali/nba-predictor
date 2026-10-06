-- B2: the training run writes its size summary (dates, game counts, home win rate, per season)
-- next to the leaderboard; the Model page reads it from /api/model.training.
alter table public.model_runs add column if not exists training jsonb;
