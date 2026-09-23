alter table public.games       alter column "GAME_ID" type text using lpad("GAME_ID"::text, 10, '0');
alter table public.elo         alter column "GAME_ID" type text using lpad("GAME_ID"::text, 10, '0');
alter table public.features    alter column "GAME_ID" type text using lpad("GAME_ID"::text, 10, '0');
alter table public.predictions alter column game_id   type text using lpad(game_id::text, 10, '0');

alter table public.games       add constraint games_game_id_len       check (char_length("GAME_ID") = 10);
alter table public.elo         add constraint elo_game_id_len         check (char_length("GAME_ID") = 10);
alter table public.features    add constraint features_game_id_len    check (char_length("GAME_ID") = 10);
alter table public.predictions add constraint predictions_game_id_len check (char_length(game_id) = 10);
