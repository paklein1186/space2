-- Commune et code postal des lieux (issus du géocodage Nominatim de la réponse
-- "adresse"), exposés à Changethegame via GET /lieux. Rattrapage des lieux
-- existants : python3 -m src.geocode_backfill
alter table tiers_lieux add column if not exists commune text;
alter table tiers_lieux add column if not exists code_postal text;
