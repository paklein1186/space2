-- Lieux candidats proposés par extraction automatique (IA) depuis un
-- document de la base de connaissances — voir agent/extraction_lieux.py.
-- Jamais créés comme lieux directement : un admin accepte ou rejette
-- chaque candidat depuis le panneau d'administration.
create table if not exists candidats_lieux (
    id uuid primary key default gen_random_uuid(),
    nom text not null,
    description text not null default '',
    source_label text not null,
    commune text,
    pays text,
    citation text,
    statut text not null default 'propose' check (statut in ('propose', 'accepte', 'rejete')),
    tiers_lieu_id uuid references tiers_lieux(id) on delete set null,
    cree_le timestamptz not null default now(),
    traite_le timestamptz,
    traite_par text
);
alter table candidats_lieux enable row level security;
-- Pas de policy : accessible uniquement via get_admin_store() (clé service_role).

-- Même piège que migration_005/008/012 : un nouveau type_appel
-- ("extraction_lieux") doit être ajouté à la contrainte, sinon log_usage()
-- échoue avec "violates check constraint llm_calls_type_appel_check"
-- (désormais non bloquant pour l'appel LLM lui-même, voir agent/usage.py,
-- mais l'appel resterait quand même non comptabilisé sans cette migration).
alter table llm_calls drop constraint llm_calls_type_appel_check;
alter table llm_calls add constraint llm_calls_type_appel_check
    check (type_appel in ('entretien', 'enrichissement', 'rag_query', 'import_questionnaire',
                           'crawl_extraction', 'traduction_fiche', 'extraction_lieux'));
