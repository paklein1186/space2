-- Même piège que migration_005 (crawl_extraction) : un nouveau type_appel
-- ("traduction_fiche", voir agent/traduction.py) doit être ajouté à la
-- contrainte, sinon log_llm_call() échoue avec "violates check constraint
-- llm_calls_type_appel_check" — désormais non bloquant pour l'appel LLM
-- lui-même (voir agent/usage.py), mais la traduction restait quand même
-- non comptabilisée sans cette migration.
alter table llm_calls drop constraint llm_calls_type_appel_check;
alter table llm_calls add constraint llm_calls_type_appel_check
    check (type_appel in ('entretien', 'enrichissement', 'rag_query', 'import_questionnaire',
                           'crawl_extraction', 'traduction_fiche'));
