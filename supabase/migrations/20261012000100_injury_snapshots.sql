-- 0001_injury_snapshots.sql  (player-data-work; NOT applied by the agent, apply manually)
-- Append-only archive of the official NBA injury report, one row per player per published report.
-- Writers insert with ON CONFLICT (source, report_time, team_id, player_name_raw) DO NOTHING, so
-- re-fetching an unchanged report inserts nothing. Rows are never updated or deleted.
-- Idempotent: safe to re-run.

create table if not exists public.injury_snapshots (
  snapshot_id      bigint generated always as identity primary key,
  captured_at      timestamptz not null,           -- when we fetched the report
  report_time      timestamptz not null,           -- the report's own timestamp (PDF header, ET converted to UTC)
  game_id          text,                           -- zero-padded nba_api id, null until matched
  game_date        date not null,
  game_time_et     text,                           -- as printed, e.g. '07:30 (ET)'
  matchup          text,                           -- as printed, e.g. 'CLE@ATL' (away@home)
  team_id          bigint not null,
  player_id        bigint,                         -- null until matched (see injury_unmatched report)
  player_name_raw  text not null,                  -- as printed, e.g. 'Moore Jr., Wendell'
  status_raw       text not null,
  status           text not null check (status in ('out', 'doubtful', 'questionable', 'probable', 'available')),
  reason           text,
  source           text not null,                  -- 'nba_official_pdf'
  raw_file         text,                           -- cached PDF file name under data/raw/injury_reports/
  constraint injury_snapshots_report_player_key unique (source, report_time, team_id, player_name_raw),
  constraint injury_snapshots_game_id_text check (game_id is null or game_id ~ '^[0-9]{10}$')
);

create index if not exists injury_snapshots_game_player_time_idx
  on public.injury_snapshots (game_id, player_id, report_time desc);
create index if not exists injury_snapshots_date_idx
  on public.injury_snapshots (game_date, report_time desc);

alter table public.injury_snapshots enable row level security;
revoke all on public.injury_snapshots from anon, authenticated;
