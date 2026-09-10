-- Migration incrémentale pour une base Supabase déjà déployée avec schema.sql.
-- Regroupe tous les ajouts en attente à cette date (rôle steward, liens/photo,
-- catégories via donnees jsonb — pas de colonne dédiée, Portfolio, admins,
-- campagnes prioritaires, lecture publique pour Observatoire/Portfolio).
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
