-- Schéma Supabase (Postgres) pour la plateforme "Lieux hybrides et territoires".
-- À exécuter dans l'éditeur SQL de votre projet Supabase.
-- L'authentification (lien magique) est gérée par Supabase Auth (table auth.users) ;
-- on référence simplement auth.users(id) depuis nos tables.

create table if not exists tiers_lieux (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references auth.users(id),
    nom text not null,
    pays text,
    region text,
    latitude double precision,
    longitude double precision,
    statut_progression text default 'en_cours',
    cree_le timestamptz not null default now()
);

create table if not exists contributeurs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id),
    tiers_lieu_id uuid not null references tiers_lieux(id) on delete cascade,
    role text not null check (role in ('fondateur', 'equipe', 'partenaire', 'usager', 'steward', 'autre')),
    cree_le timestamptz not null default now(),
    unique (user_id, tiers_lieu_id, role)
);

create table if not exists sessions_entretien (
    id uuid primary key default gen_random_uuid(),
    tiers_lieu_id uuid not null references tiers_lieux(id) on delete cascade,
    contributeur_id uuid not null references contributeurs(id) on delete cascade,
    module_courant text,
    section_courante text,
    completed_sections jsonb not null default '[]'::jsonb,
    statut text not null default 'en_cours' check (statut in ('en_cours', 'terminee')),
    derniere_activite_le timestamptz not null default now()
);

create table if not exists reponses (
    id uuid primary key default gen_random_uuid(),
    tiers_lieu_id uuid not null references tiers_lieux(id) on delete cascade,
    contributeur_id uuid not null references contributeurs(id) on delete cascade,
    champ_id text not null,
    valeur jsonb,
    confidentiel boolean not null default false,
    maj_le timestamptz not null default now(),
    unique (tiers_lieu_id, contributeur_id, champ_id)
);

create table if not exists notes_libres (
    id uuid primary key default gen_random_uuid(),
    tiers_lieu_id uuid not null references tiers_lieux(id) on delete cascade,
    contributeur_id uuid not null references contributeurs(id) on delete cascade,
    section_id text,
    texte text not null,
    cree_le timestamptz not null default now()
);

-- Donnée dérivée par lieu (jamais dans reponses — voir §5 du plan d'architecture).
create table if not exists lieu_derive (
    tiers_lieu_id uuid primary key references tiers_lieux(id) on delete cascade,
    donnees jsonb not null,
    sources jsonb,                  -- {section: [champ_id, ...]} — provenance de chaque synthèse
    profil_semantique_texte text not null,
    prompt_version text not null,
    model text not null,
    source_hash text not null,
    valide_manuellement boolean not null default false,
    corrections_manuelles jsonb,
    lien_externe text,               -- renseigné manuellement (ex. fiche tiers-lieux.xyz)
    photo_url text,                  -- renseigné manuellement
    inclus_portfolio boolean not null default false,  -- sélection admin pour la vitrine publique
    campagne_texte text,             -- appel/campagne de besoins (Portfolio public)
    campagne_objectif text,
    campagne_contact text,
    genere_le timestamptz not null default now()
);

-- Comptes admin (global, pas lié à un lieu) : peuvent nommer d'autres admins,
-- curer le Portfolio, gérer les campagnes prioritaires.
create table if not exists admins (
    user_id uuid primary key references auth.users(id),
    cree_le timestamptz not null default now()
);

-- Campagnes de collecte ciblée (fenêtre temporelle), définies par un admin.
create table if not exists campagnes_prioritaires (
    id uuid primary key default gen_random_uuid(),
    titre text not null,
    description text,
    champ_ids jsonb not null default '[]'::jsonb,
    date_debut timestamptz not null,
    date_fin timestamptz not null,
    cree_par uuid references auth.users(id),
    cree_le timestamptz not null default now()
);

-- Traçabilité et suivi des coûts de chaque appel LLM.
create table if not exists llm_calls (
    id uuid primary key default gen_random_uuid(),
    type_appel text not null check (type_appel in ('entretien', 'enrichissement', 'rag_query', 'import_questionnaire')),
    tiers_lieu_id uuid references tiers_lieux(id) on delete set null,
    model text not null,
    tokens_in integer not null,
    tokens_out integer not null,
    cout_estime numeric not null,
    cree_le timestamptz not null default now()
);

create index if not exists idx_reponses_tiers_lieu on reponses(tiers_lieu_id);
create index if not exists idx_notes_libres_tiers_lieu on notes_libres(tiers_lieu_id);
create index if not exists idx_sessions_contributeur on sessions_entretien(contributeur_id);

-- Row Level Security.
-- Principe : écriture réservée au propriétaire/contributeur concerné ; lecture
-- ouverte à tout utilisateur authentifié sur tiers_lieux/reponses/notes_libres/
-- lieu_derive, nécessaire pour l'Annuaire (portfolio partagé de tous les lieux
-- recensés) et pour que l'assistant RAG puisse répondre sur l'ensemble du
-- corpus, pas seulement les lieux de l'utilisateur courant.
alter table tiers_lieux enable row level security;
alter table contributeurs enable row level security;
alter table sessions_entretien enable row level security;
alter table reponses enable row level security;
alter table notes_libres enable row level security;
alter table lieu_derive enable row level security;
alter table llm_calls enable row level security;
alter table admins enable row level security;
alter table campagnes_prioritaires enable row level security;

create policy "chacun voit s'il est admin" on admins for select using (user_id = auth.uid());

create policy "lecture publique campagnes" on campagnes_prioritaires for select using (true);
create policy "authentifie gere campagnes" on campagnes_prioritaires
    for all using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

-- Observatoire et Portfolio sont des pages publiques (sans connexion) : lecture
-- ouverte à tous sur tiers_lieux/lieu_derive (contenu déjà pensé comme une
-- synthèse partageable), et sur reponses uniquement si non confidentiel.
create policy "lecture publique tiers_lieux" on tiers_lieux for select using (true);
create policy "lecture publique lieu_derive" on lieu_derive for select using (true);
create policy "lecture publique reponses non confidentielles" on reponses
    for select using (confidentiel = false);

create policy "lecture publique des lieux" on tiers_lieux
    for select using (auth.role() = 'authenticated');
create policy "owner modifie ses lieux" on tiers_lieux
    for insert with check (owner_user_id = auth.uid());
create policy "owner met a jour ses lieux" on tiers_lieux
    for update using (owner_user_id = auth.uid()) with check (owner_user_id = auth.uid());
create policy "owner supprime ses lieux" on tiers_lieux
    for delete using (owner_user_id = auth.uid());

create policy "utilisateur gere ses contributions" on contributeurs
    for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "utilisateur gere ses sessions" on sessions_entretien
    for all using (
        contributeur_id in (select id from contributeurs where user_id = auth.uid())
    );

create policy "lecture publique des reponses" on reponses
    for select using (auth.role() = 'authenticated');
create policy "contributeur ecrit ses reponses" on reponses
    for insert with check (
        contributeur_id in (select id from contributeurs where user_id = auth.uid())
    );
create policy "contributeur met a jour ses reponses" on reponses
    for update using (
        contributeur_id in (select id from contributeurs where user_id = auth.uid())
    );

create policy "lecture publique des notes" on notes_libres
    for select using (auth.role() = 'authenticated');
create policy "contributeur ecrit ses notes" on notes_libres
    for insert with check (
        contributeur_id in (select id from contributeurs where user_id = auth.uid())
    );

-- lieu_derive et llm_calls : cette architecture n'a pas de backend séparé
-- (Streamlit appelle directement l'API Supabase avec la clé publique, voir
-- §3 du plan — pas de couche API dédiée pour l'instant). Toute personne
-- authentifiée peut donc écrire ces tables, au même titre que l'app elle-même.
create policy "lecture publique des donnees derivees" on lieu_derive
    for select using (auth.role() = 'authenticated');
create policy "ecriture des donnees derivees" on lieu_derive
    for insert with check (auth.role() = 'authenticated');
create policy "mise a jour des donnees derivees" on lieu_derive
    for update using (auth.role() = 'authenticated');

create policy "lecture publique du suivi des couts" on llm_calls
    for select using (auth.role() = 'authenticated');
create policy "ecriture du suivi des couts" on llm_calls
    for insert with check (auth.role() = 'authenticated');
