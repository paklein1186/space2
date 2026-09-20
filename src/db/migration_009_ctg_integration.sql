-- Intégration Changethegame (ctg) : synthèse publique par lieu, lien lieu <->
-- entité ctg, événements publics remontés de ctg, accès externes.

-- Synthèse PUBLIQUE (générée à partir des seules réponses publiques — voir
-- agent/enrichissement_public.py), distincte de `donnees` qui peut refléter
-- des réponses confidentielles/internes.
alter table lieu_derive add column if not exists donnees_publiques jsonb;
alter table lieu_derive add column if not exists donnees_publiques_source_hash text;
alter table lieu_derive add column if not exists donnees_publiques_maj timestamptz;

alter table tiers_lieux add column if not exists ctg_entity_id text;
create unique index if not exists tiers_lieux_ctg_entity_id_key
    on tiers_lieux (ctg_entity_id) where ctg_entity_id is not null;

-- Événements publics remontés de ctg (membres, discussions, mises à jour,
-- quêtes, besoins) pour un lieu lié. Écriture par l'API (service_role) ;
-- lecture par les utilisateurs connectés (dataset "activite_ctg" du RAG).
create table if not exists evenements_ctg (
    id uuid primary key default gen_random_uuid(),
    tiers_lieu_id uuid not null references tiers_lieux(id) on delete cascade,
    ctg_event_id text not null unique,
    type text not null check (type in ('membre', 'discussion', 'mise_a_jour', 'quete', 'besoin')),
    titre text,
    texte text,
    url text,
    survenu_le timestamptz,
    cree_le timestamptz not null default now()
);
alter table evenements_ctg enable row level security;
create policy "lecture evenements ctg (connectes)" on evenements_ctg
    for select using (auth.role() = 'authenticated');

-- Accès externes : membres de guildes / loueurs de l'agent côté ctg. Pas de
-- policy = accessible uniquement via la clé service_role (l'email est une
-- donnée personnelle).
create table if not exists acces_externes (
    email text primary key,
    source text not null default 'ctg',
    guilde_id text,
    statut text not null default 'actif' check (statut in ('actif', 'revoque')),
    maj_le timestamptz not null default now()
);
alter table acces_externes enable row level security;
