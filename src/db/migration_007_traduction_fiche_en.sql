-- Traduction anglaise de la synthèse d'un lieu (lieu_derive.donnees),
-- générée à la volée par LLM et mise en cache ici plutôt que retraduite à
-- chaque affichage — invalidée quand donnees_en_source_hash diffère de
-- source_hash (contenu français régénéré depuis la dernière traduction).
alter table lieu_derive add column if not exists donnees_en jsonb;
alter table lieu_derive add column if not exists donnees_en_source_hash text;
