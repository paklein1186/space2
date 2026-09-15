-- web_crawl.py enregistre l'usage de l'extraction Haiku (scan admin ET,
-- depuis peu, le "Transmettre un site/document/texte" de l'entretien) sous
-- type_appel="crawl_extraction", jamais ajouté à la contrainte d'origine —
-- chaque appel réel (site avec du contenu utile) faisait donc échouer
-- log_usage() avec "violates check constraint llm_calls_type_appel_check",
-- non rattrapé, qui remontait jusqu'à faire planter la fonctionnalité
-- entière plutôt que la seule télémétrie.
alter table llm_calls drop constraint llm_calls_type_appel_check;
alter table llm_calls add constraint llm_calls_type_appel_check
    check (type_appel in ('entretien', 'enrichissement', 'rag_query', 'import_questionnaire', 'crawl_extraction'));
