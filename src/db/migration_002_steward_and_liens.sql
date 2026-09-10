-- Migration incrémentale pour une base Supabase déjà déployée avec schema.sql.
-- Regroupe tous les ajouts en attente à cette date (rôle steward, liens/photo,
-- catégories via donnees jsonb — pas de colonne dédiée, Portfolio, admins,
-- campagnes prioritaires, lecture publique pour Observatoire/Portfolio,
-- historique des modifications, blocage de contributeur, litiges).
-- À exécuter une fois dans l'éditeur SQL Supabase.

alter table contributeurs drop constraint if exists contributeurs_role_check;
alter table contributeurs add constraint contributeurs_role_check
    check (role in ('fondateur', 'equipe', 'partenaire', 'usager', 'steward', 'autre'));

alter table lieu_derive add column if not exists sources jsonb;
alter table lieu_derive add column if not exists lien_externe text;
alter table lieu_derive add column if not exists photo_url text;
alter table lieu_derive add column if not exists inclus_portfolio boolean not null default false;
alter table lieu_derive add column if not exists campagne_texte text;
alter table lieu_derive add column if not exists campagne_objectif text;
alter table lieu_derive add column if not exists campagne_contact text;

create table if not exists admins (
    user_id uuid primary key references auth.users(id),
    cree_le timestamptz not null default now()
);
alter table admins enable row level security;
drop policy if exists "chacun voit s'il est admin" on admins;
create policy "chacun voit s'il est admin" on admins for select using (user_id = auth.uid());

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
alter table campagnes_prioritaires enable row level security;
drop policy if exists "lecture publique campagnes" on campagnes_prioritaires;
create policy "lecture publique campagnes" on campagnes_prioritaires for select using (true);
drop policy if exists "authentifie gere campagnes" on campagnes_prioritaires;
create policy "authentifie gere campagnes" on campagnes_prioritaires
    for all using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

-- Observatoire ET Portfolio étant publics, lieu_derive/tiers_lieux deviennent
-- publics en lecture sans condition (contenu déjà pensé comme une synthèse
-- partageable). reponses reste plus prudent : public seulement si non
-- confidentiel (le flag existe déjà dans le schéma depuis le premier plan).
drop policy if exists "lecture publique lieu_derive" on lieu_derive;
create policy "lecture publique lieu_derive" on lieu_derive for select using (true);
drop policy if exists "lecture publique tiers_lieux" on tiers_lieux;
create policy "lecture publique tiers_lieux" on tiers_lieux for select using (true);
drop policy if exists "lecture publique reponses non confidentielles" on reponses;
create policy "lecture publique reponses non confidentielles" on reponses
    for select using (confidentiel = false);

-- Historique (journal d'écriture append-only, indépendant de `reponses` qui
-- ne garde que la valeur courante), blocage de contributeur (modération) et
-- litiges. La modération elle-même (bloquer/débloquer un contributeur,
-- ouvrir/résoudre un litige) passe exclusivement par le store service_role
-- côté app, après vérification en Python que l'auteur de l'action est admin
-- ou un contributeur interne (fondateur/équipe/steward) non bloqué de ce
-- même lieu — même logique que la curation Portfolio. Ces policies ne
-- couvrent donc que la lecture (et l'écriture du journal par son propre
-- contributeur, au fil de l'entretien normal).

alter table contributeurs add column if not exists bloque boolean not null default false;
alter table contributeurs add column if not exists bloque_le timestamptz;
alter table contributeurs add column if not exists bloque_par uuid references auth.users(id);

create table if not exists journal_modifications (
    id uuid primary key default gen_random_uuid(),
    tiers_lieu_id uuid not null references tiers_lieux(id),
    contributeur_id uuid not null references contributeurs(id),
    type text not null,
    champ_id text,
    valeur jsonb,
    cree_le timestamptz not null default now()
);
alter table journal_modifications enable row level security;
drop policy if exists "lecture authentifiee historique" on journal_modifications;
create policy "lecture authentifiee historique" on journal_modifications
    for select using (auth.role() = 'authenticated');
drop policy if exists "contributeur ecrit son historique" on journal_modifications;
create policy "contributeur ecrit son historique" on journal_modifications
    for insert with check (
        contributeur_id in (select id from contributeurs where user_id = auth.uid())
    );

create table if not exists litiges (
    id uuid primary key default gen_random_uuid(),
    tiers_lieu_id uuid not null references tiers_lieux(id),
    contributeur_vise_id uuid references contributeurs(id),
    signale_par uuid not null references auth.users(id),
    description text not null,
    statut text not null default 'ouvert',
    cree_le timestamptz not null default now(),
    resolu_le timestamptz
);
alter table litiges enable row level security;
drop policy if exists "lecture authentifiee litiges" on litiges;
create policy "lecture authentifiee litiges" on litiges
    for select using (auth.role() = 'authenticated');

create index if not exists idx_journal_tiers_lieu on journal_modifications(tiers_lieu_id, cree_le desc);
create index if not exists idx_litiges_tiers_lieu on litiges(tiers_lieu_id);
