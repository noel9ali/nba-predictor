create table if not exists public.workflow_log (
  id          bigint generated always as identity primary key,
  run_date    date not null,
  kind        text not null default 'manual' check (kind in ('morning','predict','manual')),
  trigger     text not null default 'schedule' check (trigger in ('schedule','manual')),
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  status      text not null check (status in ('running','success','partial','failed')),
  pipeline_ok boolean,
  predict_ok  boolean,
  sms_sent    boolean,
  notes       text,
  log_tail    text check (log_tail is null or char_length(log_tail) <= 20000)
);
alter table public.workflow_log enable row level security;
