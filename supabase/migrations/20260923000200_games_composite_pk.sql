alter table public.games drop constraint games_pkey;
alter table public.games add constraint games_pkey primary key ("GAME_ID", "TEAM_ID");
