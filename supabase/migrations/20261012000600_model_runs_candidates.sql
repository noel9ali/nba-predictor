-- 0006_model_runs_candidates.sql  (player-data-work; NOT applied by the agent, apply manually)
-- Candidate models (evaluated, never auto-promoted) and the feature-set version, shown by /api/model.
-- Additive and nullable. Idempotent: safe to re-run.
alter table public.model_runs add column if not exists candidates jsonb;
alter table public.model_runs add column if not exists feature_set_version text;
